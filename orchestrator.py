from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from agents import run_genomic_agent, run_literature_agent, synthesize_brief
from config import get_fast_client, settings
from schemas import (
    AgentEvent,
    AnalyzedPaper,
    DeepAnalysis,
    PipelineResult,
    QueryClassification,
)

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


def _strip_think_tags(content: str) -> str:
    """Remove DeepSeek-R1 <think>...</think> reasoning blocks."""
    text = content or ""
    if "</think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    elif "<think>" in text:
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    return text.strip()


def _safe_parse_json(content: str) -> dict:
    text = _strip_think_tags(content)
    if not text:
        return {}
    # Strip markdown code fences
    block = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if block:
        text = block.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        obj = re.search(r"(\{.*\})", text, flags=re.DOTALL)
        if obj:
            try:
                return json.loads(obj.group(1))
            except json.JSONDecodeError:
                pass
        return {}


# ---------------------------------------------------------------------------
# Query classification -- OpenRouter (fast, cheap)
# ---------------------------------------------------------------------------

def classify_query(query: str) -> QueryClassification:
    client = get_fast_client()
    prompt = (
        "Classify query into Mode 1/2/3 and return strict JSON.\n"
        "Mode 1: pure literature query, no specific gene.\n"
        "Mode 2: explicit gene mentioned (run literature+genomic parallel).\n"
        "Mode 3: disease/mechanism query where gene should be inferred from literature first.\n"
        "Examples:\n"
        "- 'How does Ozempic work?' => mode 1\n"
        "- 'What does TP53 do?' => mode 2 gene_name=TP53\n"
        "- 'Why do some people get severe kidney disease?' => mode 3\n"
        '{"mode":1|2|3,"research_plan":"...","gene_name":"optional","variant":"optional","tissue_context":"optional"}\n'
        f"Query: {query}"
    )
    response = client.chat.completions.create(
        model=settings.openrouter_fast_model,
        messages=[
            {"role": "system", "content": "You are a strict orchestrator. Return JSON only."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    parsed = _safe_parse_json(response.choices[0].message.content or "")
    if not parsed:
        mode = 2 if any(tok.isupper() and 2 <= len(tok) <= 10 and tok.isalpha() for tok in query.split()) else 1
        return QueryClassification(mode=mode, research_plan="Fallback classification.")
    return QueryClassification(
        mode=int(parsed.get("mode", 1)),  # type: ignore[arg-type]
        research_plan=str(parsed.get("research_plan") or "Classified by orchestrator."),
        gene_name=parsed.get("gene_name"),
        variant=parsed.get("variant"),
        tissue_context=parsed.get("tissue_context"),
    )


# ---------------------------------------------------------------------------
# Deep Research Analysis -- Frontier reasoning model (OpenRouter GPT-5.4)
# ---------------------------------------------------------------------------

def deep_research_analysis(query: str, raw_papers: list[dict]) -> DeepAnalysis:
    """Frontier structured analysis via OpenRouter research model.

    Produces: analyzed papers, consensus/conflicts/gaps, gene target, hypotheses.
    """
    client = get_fast_client()
    top = raw_papers[:10]
    if not top:
        return DeepAnalysis()

    compact_papers = []
    for i, p in enumerate(top, start=1):
        abstract = (p.get("abstract") or "")[:800]
        compact_papers.append({
            "index": i,
            "title": p.get("title", ""),
            "year": p.get("year"),
            "journal": p.get("journal"),
            "doi": p.get("doi"),
            "pmid": p.get("pmid"),
            "citation_count": p.get("citation_count", 0),
            "abstract": abstract,
            "tldr": (p.get("tldr") or "")[:200],
        })

    prompt = (
        "Analyze these papers for the user query. Return strict JSON:\n"
        "{\n"
        '  "analyzed_papers": [{"title":"...", "key_finding":"...", "methodology":"...", '
        '"evidence_strength":"strong|moderate|weak", "relevant_to_query":"...", "gap_identified":"..."}],\n'
        '  "consensus_points": ["point with [Author Year] citation..."],\n'
        '  "conflicts": ["conflict with citations..."],\n'
        '  "gaps": ["gap identified..."],\n'
        '  "gene_name": "HGNC SYMBOL or null if no clear gene target",\n'
        '  "gene_rationale": "why this gene is the best target for genomic follow-up",\n'
        '  "hypotheses": ["testable hypothesis 1...", "testable hypothesis 2..."]\n'
        "}\n\n"
        "RULES: cite [Author Year] or [PMID:xxxxx]. gene_name = single most relevant gene (HGNC). "
        "Generate 2-3 testable hypotheses. Distinguish strong evidence from speculation.\n\n"
        f"Query: {query}\n\n"
        f"Papers:\n{json.dumps(compact_papers, ensure_ascii=False)}"
    )

    response = client.chat.completions.create(
        model=settings.openrouter_research_model,
        messages=[
            {"role": "system", "content": "You are a biomedical research analyst. Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    parsed = _safe_parse_json(response.choices[0].message.content or "")
    if not parsed:
        return DeepAnalysis()

    analyzed: list[AnalyzedPaper] = []
    for item in parsed.get("analyzed_papers", []):
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        source_paper = next((p for p in top if p.get("title", "").strip() == title), None)
        if source_paper is None:
            source_paper = next(
                (p for p in top if title.lower()[:40] in p.get("title", "").lower()),
                None,
            )
        base = source_paper or {"title": title}
        analyzed.append(AnalyzedPaper(
            title=base.get("title", title),
            authors=base.get("authors", []),
            year=base.get("year"),
            journal=base.get("journal"),
            doi=base.get("doi"),
            pmid=base.get("pmid"),
            s2_id=base.get("s2_id"),
            citation_count=base.get("citation_count", 0),
            tldr=base.get("tldr"),
            abstract=base.get("abstract"),
            is_open_access=base.get("is_open_access", False),
            pdf_url=base.get("pdf_url"),
            source=base.get("source", "unknown"),
            venue_type=base.get("venue_type", "unknown"),
            key_finding=str(item.get("key_finding", "")),
            methodology=str(item.get("methodology", "")),
            evidence_strength=str(item.get("evidence_strength", "moderate")).lower(),  # type: ignore[arg-type]
            relevant_to_query=str(item.get("relevant_to_query", "")),
            gap_identified=item.get("gap_identified"),
        ))

    gene = parsed.get("gene_name")
    if isinstance(gene, str):
        gene = gene.strip() or None

    return DeepAnalysis(
        analyzed_papers=analyzed,
        consensus_points=list(parsed.get("consensus_points", [])),
        conflicts=list(parsed.get("conflicts", [])),
        gaps=list(parsed.get("gaps", [])),
        gene_name=gene,
        gene_rationale=str(parsed.get("gene_rationale") or ""),
        hypotheses=list(parsed.get("hypotheses", [])),
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(query: str, emitter: EventEmitter | None = None) -> PipelineResult:
    await _emit(emitter, "orchestrator", "start", "Classifying query (OpenRouter/Gemini Flash)...")
    classification = await asyncio.to_thread(classify_query, query)
    await _emit(
        emitter,
        "orchestrator",
        "progress",
        f"Mode {classification.mode} selected.",
        classification.model_dump(),
    )

    literature = None
    genomic = None
    analysis = None

    if classification.mode == 1:
        # Pure literature -- use Nebius Llama for analysis (existing flow)
        literature = await run_literature_agent(query, emitter)

    elif classification.mode == 2:
        # Explicit gene -- parallel literature + genomic (existing flow)
        literature, genomic = await asyncio.gather(
            run_literature_agent(
                query, emitter,
                gene_name=classification.gene_name,
                tissue_context=classification.tissue_context,
            ),
            run_genomic_agent(query, classification.gene_name, emitter),
        )

    else:
        # Mode 3: search (raw) -> deep analysis -> genomic -> high-quality synthesis
        await _emit(emitter, "literature", "start", "Searching literature sources (raw mode)...")
        literature = await run_literature_agent(query, emitter, analysis_mode="raw")

        await _emit(
            emitter,
            "analysis",
            "start",
            f"Running deep research analysis ({settings.openrouter_research_model})...",
        )
        raw_papers = [p.model_dump() for p in literature.papers]
        analysis = await asyncio.to_thread(deep_research_analysis, query, raw_papers)
        await _emit(
            emitter, "analysis", "complete",
            f"Analysis complete. Gene target: {analysis.gene_name or 'none'}. {len(analysis.hypotheses)} hypotheses generated.",
            analysis.model_dump(),
        )

        gene = analysis.gene_name
        if gene:
            genomic = await run_genomic_agent(query, gene, emitter)
        else:
            await _emit(emitter, "genomic", "progress", "No gene target identified; skipping genomic analysis.")

    await _emit(emitter, "synthesis", "start", "Synthesizing citation-grounded research brief...")
    brief = await asyncio.to_thread(synthesize_brief, query, literature, genomic, analysis)
    await _emit(emitter, "synthesis", "complete", "Research brief generated.")

    result = PipelineResult(
        classification=classification,
        literature=literature,
        genomic=genomic,
        analysis=analysis,
        brief=brief,
    )
    await _emit(emitter, "orchestrator", "done", "Pipeline complete.", {"mode": classification.mode})
    return result
