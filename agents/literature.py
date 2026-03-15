from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, UTC
from difflib import SequenceMatcher
from typing import Any, Awaitable, Callable
from xml.etree.ElementTree import Element

import requests
from openai import OpenAI

from config import settings
from schemas import AgentEvent, AnalyzedPaper, LiteratureSummary, Paper

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS = (
    "title,authors,year,abstract,citationCount,influentialCitationCount,"
    "tldr,isOpenAccess,openAccessPdf,externalIds,venue,publicationVenue,paperId"
)
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
REQUEST_TIMEOUT = (5, 20)
STOPWORDS = {
    "the", "and", "or", "a", "an", "of", "in", "on", "to", "for", "with", "at", "by",
    "how", "does", "do", "is", "are", "what", "why", "when", "where", "who", "about",
}

EventEmitter = Callable[[AgentEvent], Awaitable[None]]


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def _emit(emitter: EventEmitter | None, agent: str, event: str, message: str, data: dict[str, Any] | None = None) -> None:
    if emitter is None:
        return
    await emitter(
        AgentEvent(
            timestamp=_utc_now_iso(),
            agent=agent,
            event=event,  # type: ignore[arg-type]
            message=message,
            data=data,
        )
    )


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", title.lower())).strip()


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9\-]{3,}", text.lower())
    return {t for t in tokens if t not in STOPWORDS}


def _paper_relevance_score(query: str, paper: Paper) -> float:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return 0.0
    corpus = " ".join(filter(None, [paper.title, paper.abstract or "", paper.tldr or "", paper.doi or "", paper.pmid or ""]))
    paper_tokens = _tokenize(corpus)
    overlap = query_tokens.intersection(paper_tokens)
    score = float(len(overlap))
    # Small boost for exact medication keyword matches.
    lower_query = query.lower()
    lower_title = (paper.title or "").lower()
    if "ozempic" in lower_query and ("ozempic" in lower_title or "semaglutide" in lower_title):
        score += 5.0
    return score


def _build_pubmed_query(
    query: str,
    gene_name: str | None = None,
    tissue_context: str | None = None,
) -> str:
    """PubMed query using field tags to suppress non-biomedical noise."""
    lower_query = query.lower()
    if "ozempic" in lower_query or "semaglutide" in lower_query:
        return '(ozempic OR semaglutide OR "GLP-1 receptor agonist")'
    if "kidney" in lower_query or "renal" in lower_query or "ckd" in lower_query:
        return '("chronic kidney disease" OR kidney OR renal OR CKD)'
    if "tp53" in lower_query or "p53" in lower_query:
        return '(TP53 OR p53 OR "tumor suppressor")'
    if gene_name:
        # [Gene Name] is a recognised PubMed field; "[Title]" anchors the symbol
        # so that short symbols like "LCT" don't pull unrelated chemistry papers.
        gene = gene_name.upper()
        term = f'({gene}[Gene Name] OR "{gene}"[Title])'
        if tissue_context:
            term = f'{term} AND "{tissue_context}"[MeSH Terms]'
        return term
    tokens = sorted(_tokenize(query))
    return " OR ".join(tokens[:6]) if tokens else query


def _build_academic_query(
    query: str,
    gene_name: str | None = None,
    tissue_context: str | None = None,
) -> str:
    """General-purpose query for Semantic Scholar / Tavily (no field tags)."""
    lower_query = query.lower()
    if "ozempic" in lower_query or "semaglutide" in lower_query:
        return '(ozempic OR semaglutide OR "GLP-1 receptor agonist")'
    if "kidney" in lower_query or "renal" in lower_query or "ckd" in lower_query:
        return '("chronic kidney disease" OR kidney OR renal OR CKD)'
    if "tp53" in lower_query or "p53" in lower_query:
        return '(TP53 OR p53 OR "tumor suppressor")'
    if gene_name:
        # Wrap gene in biomedical context to avoid non-genomic hits.
        gene = gene_name.upper()
        term = f'"{gene} gene" OR "{gene} protein"'
        if tissue_context:
            term = f'({term}) "{tissue_context}"'
        return term
    tokens = sorted(_tokenize(query))
    return " OR ".join(tokens[:6]) if tokens else query


def _titles_match(a: str, b: str) -> bool:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() > 0.90


def _xml_text(elem: Element | None, default: str = "") -> str:
    if elem is None:
        return default
    return (elem.text or default).strip()


def _first_sentence(text: str, max_chars: int = 240) -> str:
    """Return the first complete sentence from text, capped at max_chars."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    for sep in (". ", "! ", "? "):
        idx = text.find(sep, 0, max_chars)
        if idx > 0:
            return text[: idx + 1]
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.6:
        return truncated[:last_space] + "…"
    return truncated + "…"


def _search_pubmed_sync(query: str) -> tuple[list[Paper], list[str]]:
    from Bio import Entrez

    warnings: list[str] = []
    Entrez.email = settings.pubmed_email
    try:
        handle = Entrez.esearch(db="pubmed", term=query, retmax=20, sort="relevance")
        record = Entrez.read(handle)
        handle.close()
    except Exception as exc:
        return [], [f"PubMed esearch failed: {exc}"]

    id_list = record.get("IdList", [])
    if not id_list:
        return [], warnings

    try:
        handle = Entrez.efetch(db="pubmed", id=id_list, rettype="xml", retmode="xml")
        raw_xml = handle.read()
        handle.close()
    except Exception as exc:
        return [], [f"PubMed efetch failed: {exc}"]

    import xml.etree.ElementTree as ET

    root = ET.fromstring(raw_xml if isinstance(raw_xml, str) else raw_xml.decode("utf-8"))
    papers: list[Paper] = []
    for article in root.findall(".//PubmedArticle"):
        medline = article.find(".//MedlineCitation")
        if medline is None:
            continue
        art = medline.find("Article")
        if art is None:
            continue
        title = _xml_text(art.find("ArticleTitle"))
        if not title:
            continue

        authors: list[str] = []
        for au in art.findall(".//Author"):
            last = _xml_text(au.find("LastName"))
            initials = _xml_text(au.find("Initials"))
            if last:
                authors.append(f"{last} {initials}".strip())

        year = None
        year_elem = art.find(".//PubDate/Year")
        if year_elem is not None and year_elem.text and year_elem.text.isdigit():
            year = int(year_elem.text)

        doi = None
        for eid in art.findall(".//ELocationID"):
            if eid.get("EIdType") == "doi":
                doi = (eid.text or "").strip() or None
                break
        if doi is None:
            for aid in article.findall(".//ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = (aid.text or "").strip() or None
                    break

        abstract_parts: list[str] = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label", "")
            text = (ab.text or "").strip()
            if not text:
                continue
            abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts).strip() or None

        pmid_elem = medline.find("PMID")
        pmid = _xml_text(pmid_elem) if pmid_elem is not None else None
        journal_elem = art.find(".//Journal/Title")
        journal = _xml_text(journal_elem) if journal_elem is not None else None

        mesh_terms: list[str] = []
        for mh in medline.findall(".//MeshHeadingList/MeshHeading/DescriptorName"):
            term = _xml_text(mh)
            if term:
                mesh_terms.append(term)

        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=year,
                journal=journal,
                doi=doi,
                pmid=pmid,
                abstract=abstract,
                source="pubmed",
                venue_type="journal",
                mesh_terms=mesh_terms,
            )
        )

    return papers, warnings


def _search_s2_sync(query: str) -> tuple[list[Paper], list[str]]:
    warnings: list[str] = []
    url = (
        f"{S2_SEARCH_URL}?query={urllib.parse.quote(query)}&limit=20&fields={urllib.parse.quote(S2_FIELDS)}"
    )
    headers: dict[str, str] = {}
    if settings.semantic_scholar_api_key:
        headers["x-api-key"] = settings.semantic_scholar_api_key
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429:
            return [], ["Semantic Scholar rate limited (429). Set SEMANTIC_SCHOLAR_API_KEY for higher limits."]
        resp.raise_for_status()
    except Exception as exc:
        return [], [f"Semantic Scholar failed: {exc}"]

    items = resp.json().get("data") or []
    papers: list[Paper] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        authors = [a.get("name", "").strip() for a in (item.get("authors") or []) if a.get("name")]
        ext = item.get("externalIds") or {}
        venue = (item.get("venue") or "").lower()
        pub_venue = item.get("publicationVenue") or {}
        pub_venue_type = (pub_venue.get("type") or "").lower()
        if "biorxiv" in venue or "medrxiv" in venue or pub_venue_type == "repository":
            venue_type = "preprint"
        elif "conference" in pub_venue_type:
            venue_type = "conference"
        elif "journal" in pub_venue_type:
            venue_type = "journal"
        else:
            venue_type = "unknown"

        tldr_obj = item.get("tldr")
        tldr = tldr_obj.get("text") if isinstance(tldr_obj, dict) else None
        oa_pdf = item.get("openAccessPdf") or {}
        pdf_url = oa_pdf.get("url") if isinstance(oa_pdf, dict) else None
        journal = pub_venue.get("name") or item.get("venue") or None
        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=item.get("year"),
                journal=journal,
                doi=ext.get("DOI"),
                pmid=ext.get("PubMed"),
                s2_id=item.get("paperId"),
                citation_count=item.get("citationCount") or 0,
                tldr=tldr,
                abstract=item.get("abstract"),
                is_open_access=bool(item.get("isOpenAccess")),
                pdf_url=pdf_url,
                source="s2",
                venue_type=venue_type,
            )
        )
    return papers, warnings


def _search_tavily_sync(query: str) -> tuple[list[Paper], list[str]]:
    warnings: list[str] = []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": settings.tavily_api_key, "query": query, "max_results": 8},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except Exception as exc:
        return [], [f"Tavily search failed: {exc}"]

    papers: list[Paper] = []
    for item in results:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        papers.append(
            Paper(
                title=title,
                abstract=item.get("content"),
                source="tavily",
                venue_type="web",
            )
        )
    return papers, warnings


# ---------------------------------------------------------------------------
# OpenAlex — all-discipline academic source (240 M+ works, free, no auth)
# ---------------------------------------------------------------------------

OPENALEX_SEARCH_URL = "https://api.openalex.org/works"
_OA_SELECT = "id,doi,title,authorships,publication_year,primary_location,cited_by_count,type,abstract_inverted_index"


def _reconstruct_abstract_from_inverted_index(inv_index: dict[str, list[int]]) -> str:
    """OpenAlex stores abstracts as an inverted index; reconstruct plain text."""
    if not inv_index:
        return ""
    positions: dict[int, str] = {}
    for word, locs in inv_index.items():
        for pos in locs:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions))


def _search_openalex_sync(query: str) -> tuple[list[Paper], list[str]]:
    warnings: list[str] = []
    params = {
        "search": query,
        "per-page": "20",
        "select": _OA_SELECT,
        "mailto": settings.pubmed_email,  # polite-pool: 10 req/s
    }
    try:
        resp = requests.get(OPENALEX_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("results") or []
    except Exception as exc:
        return [], [f"OpenAlex search failed: {exc}"]

    papers: list[Paper] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue

        authors: list[str] = []
        for auth in (item.get("authorships") or []):
            author = auth.get("author") or {}
            display_name = (author.get("display_name") or "").strip()
            if display_name:
                authors.append(display_name)

        year = item.get("publication_year")

        doi = None
        raw_doi = (item.get("doi") or "").strip()
        if raw_doi.startswith("https://doi.org/"):
            doi = raw_doi[len("https://doi.org/"):]
        elif raw_doi:
            doi = raw_doi

        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        journal = (source.get("display_name") or "").strip() or None

        work_type = (item.get("type") or "").lower()
        if "preprint" in work_type or "repository" in (source.get("type") or "").lower():
            venue_type = "preprint"
        elif journal:
            venue_type = "journal"
        else:
            venue_type = "unknown"

        abstract = _reconstruct_abstract_from_inverted_index(
            item.get("abstract_inverted_index") or {}
        ) or None

        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=year,
                journal=journal,
                doi=doi,
                abstract=abstract,
                citation_count=item.get("cited_by_count") or 0,
                source="openalex",
                venue_type=venue_type,
            )
        )
    return papers, warnings


# ---------------------------------------------------------------------------
# arXiv — preprint server for physics / math / CS / bio (free Atom XML API)
# ---------------------------------------------------------------------------

ARXIV_API_URL = "http://export.arxiv.org/api/query"
_ARXIV_NS = "http://www.w3.org/2005/Atom"


def _search_arxiv_sync(query: str) -> tuple[list[Paper], list[str]]:
    import xml.etree.ElementTree as ET

    warnings: list[str] = []
    params = {
        "search_query": f"all:{query}",
        "max_results": "10",
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    try:
        resp = requests.get(ARXIV_API_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception as exc:
        return [], [f"arXiv search failed: {exc}"]

    ns = _ARXIV_NS
    papers: list[Paper] = []
    for entry in root.findall(f"{{{ns}}}entry"):
        title_elem = entry.find(f"{{{ns}}}title")
        title = (title_elem.text or "").strip().replace("\n", " ") if title_elem is not None else ""
        if not title:
            continue

        summary_elem = entry.find(f"{{{ns}}}summary")
        abstract = (summary_elem.text or "").strip().replace("\n", " ") if summary_elem is not None else None

        authors: list[str] = []
        for author_elem in entry.findall(f"{{{ns}}}author"):
            name_elem = author_elem.find(f"{{{ns}}}name")
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        year = None
        published_elem = entry.find(f"{{{ns}}}published")
        if published_elem is not None and published_elem.text:
            try:
                year = int(published_elem.text[:4])
            except (ValueError, IndexError):
                pass

        # Extract arXiv ID and construct DOI-like identifier.
        doi = None
        arxiv_id = None
        id_elem = entry.find(f"{{{ns}}}id")
        if id_elem is not None and id_elem.text:
            arxiv_url = id_elem.text.strip()
            if "arxiv.org/abs/" in arxiv_url:
                arxiv_id = arxiv_url.split("arxiv.org/abs/")[-1]
                doi = f"10.48550/arXiv.{arxiv_id}"

        papers.append(
            Paper(
                title=title,
                authors=authors,
                year=year,
                journal="arXiv",
                doi=doi,
                abstract=abstract,
                source="arxiv",
                venue_type="preprint",
            )
        )
    return papers, warnings


# ---------------------------------------------------------------------------
# OpenRouter abstract enrichment — last-resort web synthesis via Sonar model
# ---------------------------------------------------------------------------

def _enrich_abstracts_via_openrouter_sync(papers: list[Paper]) -> list[str]:
    """
    For papers that still have no abstract, use Perplexity Sonar (via OpenRouter)
    to do a live web search and synthesise a short summary.  We batch ≤5 at a time
    to stay cheap; each call is a single web-search model call.
    """
    from config import get_openrouter_client

    needs_enrichment = [p for p in papers if not (p.abstract or p.tldr)][:3]
    if not needs_enrichment:
        return []

    warnings: list[str] = []
    client = get_openrouter_client()

    for paper in needs_enrichment:
        year_str = f" ({paper.year})" if paper.year else ""
        journal_str = f" — {paper.journal}" if paper.journal else ""
        prompt = (
            f"Find the abstract or a concise 3–4 sentence summary of this academic paper. "
            f"Return ONLY the abstract/summary text, nothing else.\n\n"
            f"Title: {paper.title}{year_str}{journal_str}"
        )
        try:
            # Use perplexity/sonar for live web search; fallback to fast model
            resp = client.chat.completions.create(
                model="perplexity/sonar",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                timeout=15,
            )
            text = (resp.choices[0].message.content or "").strip()
            if len(text) > 40:
                paper.abstract = text
        except Exception as exc:
            warnings.append(f"OpenRouter enrichment failed for '{paper.title[:60]}': {exc}")

    return warnings


def _merge_papers(
    pubmed: list[Paper],
    s2: list[Paper],
    tavily: list[Paper],
    openalex: list[Paper] | None = None,
    arxiv: list[Paper] | None = None,
) -> list[Paper]:
    openalex = openalex or []
    arxiv = arxiv or []

    merged: list[Paper] = []
    used_s2: set[int] = set()

    for pm in pubmed:
        match_idx = None
        if pm.doi:
            for i, s2_paper in enumerate(s2):
                if i in used_s2:
                    continue
                if s2_paper.doi and s2_paper.doi.lower() == pm.doi.lower():
                    match_idx = i
                    break
        if match_idx is None:
            for i, s2_paper in enumerate(s2):
                if i in used_s2:
                    continue
                if _titles_match(pm.title, s2_paper.title):
                    match_idx = i
                    break

        if match_idx is None:
            merged.append(pm)
        else:
            used_s2.add(match_idx)
            s2_match = s2[match_idx]
            merged.append(
                Paper(
                    title=pm.title,
                    authors=pm.authors or s2_match.authors,
                    year=pm.year or s2_match.year,
                    journal=pm.journal or s2_match.journal,
                    doi=pm.doi or s2_match.doi,
                    pmid=pm.pmid or s2_match.pmid,
                    s2_id=s2_match.s2_id,
                    citation_count=max(pm.citation_count, s2_match.citation_count),
                    tldr=s2_match.tldr or pm.tldr,
                    abstract=pm.abstract or s2_match.abstract,
                    is_open_access=pm.is_open_access or s2_match.is_open_access,
                    pdf_url=s2_match.pdf_url or pm.pdf_url,
                    source="both",
                    venue_type=pm.venue_type if pm.venue_type != "unknown" else s2_match.venue_type,
                    mesh_terms=pm.mesh_terms,
                )
            )

    for i, s2_paper in enumerate(s2):
        if i not in used_s2:
            merged.append(s2_paper)

    # Add OpenAlex results, merging with existing by DOI/title.
    for oa in openalex:
        matched = False
        if oa.doi:
            for existing in merged:
                if existing.doi and existing.doi.lower() == oa.doi.lower():
                    # Enrich existing record with OA data where missing.
                    if not existing.abstract and oa.abstract:
                        existing.abstract = oa.abstract
                    if not existing.citation_count and oa.citation_count:
                        existing.citation_count = oa.citation_count
                    matched = True
                    break
        if not matched:
            for existing in merged:
                if _titles_match(oa.title, existing.title):
                    if not existing.abstract and oa.abstract:
                        existing.abstract = oa.abstract
                    matched = True
                    break
        if not matched:
            merged.append(oa)

    # Add arXiv preprints, deduplicating by title.
    for ax in arxiv:
        if any(_titles_match(ax.title, existing.title) for existing in merged):
            continue
        merged.append(ax)

    # Tavily as context-only sources; avoid duplicates.
    for tv in tavily:
        if any(_titles_match(tv.title, existing.title) for existing in merged):
            continue
        merged.append(tv)

    merged.sort(key=lambda p: p.citation_count, reverse=True)
    return merged


def _enrich_unpaywall_sync(papers: list[Paper]) -> None:
    candidates = [p for p in papers if p.doi and not p.pdf_url][:3]
    for paper in candidates:
        try:
            url = UNPAYWALL_URL.format(doi=urllib.parse.quote(paper.doi or "", safe=""))
            resp = requests.get(url, params={"email": settings.pubmed_email}, timeout=(3, 5))
            if resp.status_code != 200:
                continue
            data = resp.json()
            best = data.get("best_oa_location") or {}
            pdf = best.get("url_for_pdf")
            if pdf:
                paper.pdf_url = pdf
                paper.is_open_access = True
        except Exception:
            continue


def _safe_json_parse(content: str) -> Any:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        block_match = re.search(r"```json\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE)
        if block_match:
            return json.loads(block_match.group(1))
        arr_match = re.search(r"(\[.*\])", content, flags=re.DOTALL)
        if arr_match:
            return json.loads(arr_match.group(1))
        obj_match = re.search(r"(\{.*\})", content, flags=re.DOTALL)
        if obj_match:
            return json.loads(obj_match.group(1))
        raise


def _analyze_papers_sync(query: str, papers: list[Paper]) -> list[AnalyzedPaper]:
    top = papers[:8]
    if not top:
        return []

    formatted = []
    for i, paper in enumerate(top, start=1):
        abstract = (paper.abstract or "")
        if len(abstract) > 1200:
            abstract = abstract[:1200] + "..."
        formatted.append(
            {
                "index": i,
                "title": paper.title,
                "year": paper.year,
                "journal": paper.journal,
                "doi": paper.doi,
                "pmid": paper.pmid,
                "citation_count": paper.citation_count,
                "abstract": abstract,
                "tldr": (paper.tldr or "")[:280],
                "source": paper.source,
            }
        )

    prompt = (
        "Analyze these papers for the user query. Return valid JSON array only.\n\n"
        "For each paper, return:\n"
        '{"title":"...", "key_finding":"...", "methodology":"...", '
        '"evidence_strength":"strong|moderate|weak", "relevant_to_query":"...", "gap_identified":"..."}\n\n'
        f"User query: {query}\n\nPapers:\n{json.dumps(formatted, ensure_ascii=False)}"
    )
    from config import get_nebius_client
    client = get_nebius_client()
    response = client.chat.completions.create(
        model=settings.nebius_fast_model,
        messages=[
            {"role": "system", "content": "You are a scientific research analyst. Output strict JSON."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=2400,
    )
    content = response.choices[0].message.content or "{}"
    parsed = _safe_json_parse(content)
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        items = []

    by_title = {p.title: p for p in top}
    analyzed: list[AnalyzedPaper] = []
    for item in items:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        paper = by_title.get(title)
        if paper is None:
            # fuzzy fallback
            for p in top:
                if _titles_match(title, p.title):
                    paper = p
                    break
        if paper is None:
            continue
        analyzed.append(
            AnalyzedPaper(
                **paper.model_dump(),
                key_finding=str(item.get("key_finding", "")).strip(),
                methodology=str(item.get("methodology", "")).strip(),
                evidence_strength=str(item.get("evidence_strength", "moderate")).strip().lower(),  # type: ignore[arg-type]
                relevant_to_query=str(item.get("relevant_to_query", "")).strip(),
                gap_identified=(str(item.get("gap_identified", "")).strip() or None),
            )
        )

    # Ensure we always return analyzed papers even if LLM under-returns.
    if not analyzed:
        for paper in top:
            summary = paper.tldr or _first_sentence(paper.abstract or "")
            analyzed.append(
                AnalyzedPaper(
                    **paper.model_dump(),
                    key_finding=summary or "Summary not available in metadata.",
                    methodology="Not reported in metadata.",
                    evidence_strength="moderate",
                    relevant_to_query="Selected by query-match score.",
                    gap_identified=None,
                )
            )
    return analyzed


def _cross_corroborate_sync(query: str, analyzed: list[AnalyzedPaper]) -> tuple[list[str], list[str], list[str]]:
    if not analyzed:
        return [], [], []
    payload = [
        {
            "title": p.title,
            "year": p.year,
            "doi": p.doi,
            "pmid": p.pmid,
            "key_finding": p.key_finding,
            "evidence_strength": p.evidence_strength,
        }
        for p in analyzed
    ]
    prompt = (
        "Given analyzed papers, produce strict JSON with keys: consensus_points (array), conflicts (array), gaps (array).\n"
        "Only include claims supported directly by these items. Include citation references inline like [Title, Year].\n"
        f"Query: {query}\nItems: {json.dumps(payload, ensure_ascii=False)}"
    )
    from config import get_nebius_client
    client = get_nebius_client()
    response = client.chat.completions.create(
        model=settings.nebius_fast_model,
        messages=[
            {"role": "system", "content": "You are a strict scientific synthesis engine. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=1200,
    )
    content = response.choices[0].message.content or "{}"
    parsed = _safe_json_parse(content)
    return (
        list(parsed.get("consensus_points", [])) if isinstance(parsed, dict) else [],
        list(parsed.get("conflicts", [])) if isinstance(parsed, dict) else [],
        list(parsed.get("gaps", [])) if isinstance(parsed, dict) else [],
    )


def _search_all_sources_sync(
    query: str,
    gene_name: str | None = None,
    tissue_context: str | None = None,
) -> tuple[list[Paper], list[str], dict[str, int]]:
    warnings: list[str] = []
    pubmed: list[Paper] = []
    s2: list[Paper] = []
    tavily: list[Paper] = []
    openalex: list[Paper] = []
    arxiv: list[Paper] = []

    # PubMed understands field tags; S2 needs plain text; Tavily prefers natural language.
    pubmed_query = _build_pubmed_query(query, gene_name, tissue_context)
    s2_query = _build_academic_query(query, gene_name, tissue_context)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_search_pubmed_sync, pubmed_query): "pubmed",
            pool.submit(_search_s2_sync, s2_query): "s2",
            pool.submit(_search_tavily_sync, query): "tavily",
            pool.submit(_search_openalex_sync, query): "openalex",
            pool.submit(_search_arxiv_sync, query): "arxiv",
        }
        completed: set[Any] = set()
        source_map: dict[str, list[Paper]] = {
            "pubmed": pubmed, "s2": s2, "tavily": tavily,
            "openalex": openalex, "arxiv": arxiv,
        }
        try:
            for future in as_completed(futures, timeout=28):
                completed.add(future)
                backend = futures[future]
                try:
                    papers, warns = future.result(timeout=1)
                    warnings.extend(warns)
                    source_map[backend].extend(papers)
                except Exception as exc:
                    warnings.append(f"{backend} failed: {exc}")
        except FuturesTimeoutError:
            warnings.append("One or more literature sources timed out; using partial results.")
            for future, backend in futures.items():
                if future in completed:
                    continue
                if future.done():
                    try:
                        papers, warns = future.result(timeout=0)
                        warnings.extend(warns)
                        source_map[backend].extend(papers)
                    except Exception as exc:
                        warnings.append(f"{backend} failed after timeout: {exc}")
                else:
                    future.cancel()

    pubmed = source_map["pubmed"]
    s2 = source_map["s2"]
    tavily = source_map["tavily"]
    openalex = source_map["openalex"]
    arxiv = source_map["arxiv"]

    # Retry broad query if academic rewrite was too restrictive.
    if not pubmed and pubmed_query != query:
        retry_pubmed, retry_warns = _search_pubmed_sync(query)
        if retry_pubmed:
            pubmed = retry_pubmed
            warnings.append("PubMed fallback retry with original query succeeded.")
        warnings.extend(retry_warns)
    if not s2 and s2_query != query:
        retry_s2, retry_warns = _search_s2_sync(query)
        if retry_s2:
            s2 = retry_s2
            warnings.append("Semantic Scholar fallback retry with original query succeeded.")
        warnings.extend(retry_warns)

    merged = _merge_papers(pubmed, s2, tavily, openalex, arxiv)
    if merged:
        ranked = sorted(
            merged,
            key=lambda p: (_paper_relevance_score(query, p), p.citation_count),
            reverse=True,
        )
        # If biomedical sources scored zero relevance, push open-science sources up.
        if _paper_relevance_score(query, ranked[0]) <= 0:
            open_first = [p for p in ranked if p.source in ("openalex", "arxiv", "tavily")]
            others = [p for p in ranked if p.source not in ("openalex", "arxiv", "tavily")]
            merged = open_first + others
        else:
            merged = ranked

    _enrich_unpaywall_sync(merged)

    # Tertiary enrichment: fill missing abstracts via OpenRouter web search.
    enrichment_warns = _enrich_abstracts_via_openrouter_sync(merged)
    warnings.extend(enrichment_warns)

    counts = {
        "pubmed": len(pubmed),
        "s2": len(s2),
        "tavily": len(tavily),
        "openalex": len(openalex),
        "arxiv": len(arxiv),
        "merged": len(merged),
    }
    return merged, warnings, counts


async def run_literature_agent(
    query: str,
    emitter: EventEmitter | None = None,
    gene_name: str | None = None,
    tissue_context: str | None = None,
    analysis_mode: str = "full",
) -> LiteratureSummary:
    """Run the literature agent.

    analysis_mode:
      "full"  -- search + LLM analysis + cross-corroboration (Modes 1 & 2)
      "raw"   -- search only, skip LLM calls (Mode 3 delegates to R1)
    """
    await _emit(emitter, "literature", "start", f"Searching literature sources for: {query}")
    papers, warnings, source_counts = await asyncio.to_thread(
        _search_all_sources_sync, query, gene_name, tissue_context
    )
    await _emit(
        emitter,
        "literature",
        "progress",
        f"Found {source_counts.get('merged', 0)} papers — "
        f"PubMed:{source_counts.get('pubmed', 0)} "
        f"S2:{source_counts.get('s2', 0)} "
        f"OpenAlex:{source_counts.get('openalex', 0)} "
        f"arXiv:{source_counts.get('arxiv', 0)} "
        f"Tavily:{source_counts.get('tavily', 0)}",
        {"source_counts": source_counts, "warnings": warnings},
    )

    if analysis_mode == "raw":
        # Return raw papers as Paper (not AnalyzedPaper) -- Mode 3 uses R1 for analysis
        await _emit(emitter, "literature", "complete", f"Raw mode: returning {len(papers)} unanalyzed papers for R1 deep analysis.")
        return LiteratureSummary(
            papers=papers,
            consensus_points=[],
            conflicts=[],
            gaps=[],
            source_count=source_counts,
        )

    analyzed = await asyncio.to_thread(_analyze_papers_sync, query, papers)
    await _emit(emitter, "literature", "progress", f"Analyzed {len(analyzed)} papers.")

    consensus, conflicts, gaps = await asyncio.to_thread(_cross_corroborate_sync, query, analyzed)
    await _emit(
        emitter,
        "literature",
        "complete",
        "Cross-corroboration complete.",
        {"consensus": len(consensus), "conflicts": len(conflicts), "gaps": len(gaps)},
    )

    return LiteratureSummary(
        papers=analyzed,
        consensus_points=consensus,
        conflicts=conflicts,
        gaps=gaps,
        source_count=source_counts,
    )

