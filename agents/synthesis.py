from __future__ import annotations

import json
import re
from pathlib import Path

from config import get_nebius_client, get_openrouter_client, settings
from schemas import DeepAnalysis, GenomicResult, LiteratureSummary, ResearchBrief

SOUL_PATH = Path(__file__).resolve().parent.parent / "SOUL.md"


def _load_soul() -> str:
    if SOUL_PATH.exists():
        return SOUL_PATH.read_text(encoding="utf-8")
    return ""


def _strip_think_tags(content: str) -> str:
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


def _fallback_brief(
    query: str,
    literature: LiteratureSummary,
    genomic: GenomicResult | None,
    analysis: DeepAnalysis | None = None,
) -> ResearchBrief:
    citations: list[str] = []
    for paper in literature.papers[:12]:
        if paper.doi:
            citations.append(f"{paper.title} ({paper.year or 'n/a'}) DOI: {paper.doi}")
        elif paper.pmid:
            citations.append(f"{paper.title} ({paper.year or 'n/a'}) PMID: {paper.pmid}")

    key_findings = []
    if analysis:
        key_findings = analysis.consensus_points[:5]
    if not key_findings:
        key_findings = literature.consensus_points[:5]
    if not key_findings:
        key_findings = [p.key_finding for p in literature.papers[:5] if hasattr(p, "key_finding") and p.key_finding]
    if not key_findings:
        key_findings = ["Evidence synthesis was limited by sparse analyzable paper metadata."]

    return ResearchBrief(
        title=f"Hooke Research Brief: {query[:80]}",
        summary="Generated using multi-source literature synthesis with citation constraints.",
        key_findings=key_findings,
        genomic_insight=genomic.interpretation if genomic else None,
        evidence_synthesis=None,
        confidence_assessment=None,
        research_gap=(analysis.gaps[0] if analysis and analysis.gaps else
                      literature.gaps[0] if literature.gaps else
                      "A decisive experiment is still needed to resolve the core uncertainty."),
        proposed_experiment="Design a targeted perturbation experiment in the highest-relevance tissue and validate with orthogonal readouts.",
        citations=citations,
    )


def synthesize_brief(
    query: str,
    literature: LiteratureSummary,
    genomic: GenomicResult | None,
    analysis: DeepAnalysis | None = None,
) -> ResearchBrief:
    soul = _load_soul()

    payload: dict = {
        "query": query,
        "literature_summary": {
            "paper_count": len(literature.papers),
            "top_papers": [
                {"title": p.title, "year": p.year, "doi": p.doi, "pmid": p.pmid}
                for p in literature.papers[:10]
            ],
            "consensus": literature.consensus_points[:5],
            "conflicts": literature.conflicts[:3],
            "gaps": literature.gaps[:3],
            "source_count": literature.source_count,
        },
    }
    if genomic:
        payload["genomic_result"] = genomic.model_dump()
    if analysis:
        payload["deep_analysis"] = {
            "gene_target": analysis.gene_name,
            "gene_rationale": analysis.gene_rationale,
            "consensus": analysis.consensus_points,
            "conflicts": analysis.conflicts,
            "gaps": analysis.gaps,
            "hypotheses": analysis.hypotheses,
            "analyzed_paper_count": len(analysis.analyzed_papers),
        }

    if analysis:
        return _synthesize_with_frontier(query, payload, soul, literature, genomic, analysis)
    return _synthesize_with_fast(query, payload, soul, literature, genomic, analysis)


def _synthesize_with_fast(
    query: str,
    payload: dict,
    soul: str,
    literature: LiteratureSummary,
    genomic: GenomicResult | None,
    analysis: DeepAnalysis | None,
) -> ResearchBrief:
    """Modes 1/2 synthesis — Nebius Qwen3-235B-Instruct (fast, cheap)."""
    prompt = (
        "Generate a scientific research brief as strict JSON with these exact keys:\n"
        '{"title":"...","summary":"...","key_findings":["..."],"genomic_insight":"...",'
        '"research_gap":"...","proposed_experiment":"...","citations":["..."]}\n\n'
        "RULES:\n"
        "- No citation, no claim. Every key finding must end with [Author Year] or [PMID:xxxxx].\n"
        "- 4-6 key_findings from paper data.\n"
        "- summary: 2-3 sentences synthesising consensus.\n"
        "- proposed_experiment: specific and actionable.\n\n"
        f"Payload: {json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        client = get_nebius_client()
        response = client.chat.completions.create(
            model=settings.nebius_fast_model,
            messages=[
                {"role": "system", "content": f"You are Hooke, a hard-science research assistant.\n{soul}\nReturn strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=1800,
        )
        parsed = _safe_parse_json(response.choices[0].message.content or "")
        if not parsed:
            return _fallback_brief(query, literature, genomic, analysis)
        return ResearchBrief(
            title=str(parsed.get("title") or f"Hooke Research Brief: {query[:80]}"),
            summary=str(parsed.get("summary") or ""),
            key_findings=list(parsed.get("key_findings") or []),
            genomic_insight=parsed.get("genomic_insight"),
            evidence_synthesis=parsed.get("evidence_synthesis"),
            confidence_assessment=parsed.get("confidence_assessment"),
            research_gap=str(parsed.get("research_gap") or "Research gap not identified."),
            proposed_experiment=str(parsed.get("proposed_experiment") or "Design a targeted validation experiment."),
            citations=list(parsed.get("citations") or []),
        )
    except Exception:
        return _fallback_brief(query, literature, genomic, analysis)


def _build_brief_from_parsed(parsed: dict, query: str) -> ResearchBrief:
    return ResearchBrief(
        title=str(parsed.get("title") or f"Hooke Deep Research Brief: {query[:80]}"),
        summary=str(parsed.get("summary") or ""),
        key_findings=list(parsed.get("key_findings") or []),
        genomic_insight=parsed.get("genomic_insight"),
        evidence_synthesis=parsed.get("evidence_synthesis"),
        confidence_assessment=parsed.get("confidence_assessment"),
        research_gap=str(parsed.get("research_gap") or "Research gap not identified."),
        proposed_experiment=str(parsed.get("proposed_experiment") or "Design a targeted validation experiment."),
        citations=list(parsed.get("citations") or []),
    )


def _synthesize_with_frontier(
    query: str,
    payload: dict,
    soul: str,
    literature: LiteratureSummary,
    genomic: GenomicResult | None,
    analysis: DeepAnalysis | None,
) -> ResearchBrief:
    """Mode 3 synthesis — Nebius DeepSeek-V3.2 primary, OpenRouter as fallback."""
    prompt = (
        "You are Hooke, a hard-science research assistant. Produce a definitive research brief as strict JSON:\n"
        "{\n"
        '  "title": "...",\n'
        '  "summary": "3-5 sentence synthesis of all evidence",\n'
        '  "key_findings": ["finding with [citation]...", ...],\n'
        '  "evidence_synthesis": "paragraph connecting literature + genomic evidence",\n'
        '  "confidence_assessment": "how strong is the overall evidence and where are weaknesses",\n'
        '  "genomic_insight": "interpretation of genomic data in context of literature",\n'
        '  "research_gap": "the most critical unanswered question",\n'
        '  "proposed_experiment": "specific experimental design to address the gap",\n'
        '  "citations": ["Author (Year) DOI:... or PMID:...", ...]\n'
        "}\n\n"
        "RULES: Every claim must cite [Author Year] or [PMID:xxxxx]. 5-8 key_findings. "
        "evidence_synthesis weaves literature + genomic data. Be honest about limitations.\n\n"
        f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    # Primary: Nebius DeepSeek-V3.2
    try:
        client = get_nebius_client()
        response = client.chat.completions.create(
            model=settings.nebius_synthesis_model,
            messages=[
                {"role": "system", "content": f"{soul}\nReturn strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=2500,
        )
        parsed = _safe_parse_json(response.choices[0].message.content or "")
        if parsed:
            return _build_brief_from_parsed(parsed, query)
    except Exception:
        pass

    # Fallback: OpenRouter Gemini Flash (cheap, reliable)
    try:
        fb_client = get_openrouter_client()
        fb_response = fb_client.chat.completions.create(
            model=settings.openrouter_fallback_model,
            messages=[
                {"role": "system", "content": f"{soul}\nReturn strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=2500,
        )
        parsed = _safe_parse_json(fb_response.choices[0].message.content or "")
        if parsed:
            return _build_brief_from_parsed(parsed, query)
    except Exception:
        pass

    return _fallback_brief(query, literature, genomic, analysis)
