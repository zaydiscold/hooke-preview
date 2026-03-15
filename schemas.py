from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Discriminator, Field, Tag


class InvestigateRequest(BaseModel):
    query: str


class Paper(BaseModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    s2_id: Optional[str] = None
    citation_count: int = 0
    tldr: Optional[str] = None
    abstract: Optional[str] = None
    is_open_access: bool = False
    pdf_url: Optional[str] = None
    source: str = "unknown"
    venue_type: str = "unknown"
    mesh_terms: list[str] = Field(default_factory=list)


class AnalyzedPaper(Paper):
    key_finding: str = ""
    methodology: str = ""
    evidence_strength: Literal["strong", "moderate", "weak"] = "moderate"
    relevant_to_query: str = ""
    gap_identified: Optional[str] = None


def _paper_discriminator(v: Any) -> str:
    if isinstance(v, dict):
        return "analyzed" if "key_finding" in v else "paper"
    return "analyzed" if isinstance(v, AnalyzedPaper) else "paper"


PaperItem = Annotated[
    Union[
        Annotated[Paper, Tag("paper")],
        Annotated[AnalyzedPaper, Tag("analyzed")],
    ],
    Discriminator(_paper_discriminator),
]


class LiteratureSummary(BaseModel):
    papers: list[PaperItem] = Field(default_factory=list)
    consensus_points: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    source_count: dict[str, int] = Field(default_factory=dict)


class GenomicResult(BaseModel):
    gene: str
    region: Optional[str] = None
    top_tissue: Optional[str] = None
    expression_direction: Optional[str] = None
    quantile_score: Optional[float] = None
    interpretation: str


class QueryClassification(BaseModel):
    mode: Literal[1, 2, 3]
    research_plan: str
    gene_name: Optional[str] = None
    variant: Optional[str] = None
    tissue_context: Optional[str] = None


class DeepAnalysis(BaseModel):
    """Intermediate research analysis produced by R1 for Mode 3."""
    analyzed_papers: list[AnalyzedPaper] = Field(default_factory=list)
    consensus_points: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    gene_name: Optional[str] = None
    gene_rationale: Optional[str] = None
    hypotheses: list[str] = Field(default_factory=list)


class ResearchBrief(BaseModel):
    title: str
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    genomic_insight: Optional[str] = None
    evidence_synthesis: Optional[str] = None
    confidence_assessment: Optional[str] = None
    research_gap: str
    proposed_experiment: str
    citations: list[str] = Field(default_factory=list)


class AgentEvent(BaseModel):
    timestamp: str
    agent: str
    event: Literal["start", "progress", "complete", "error", "done"]
    message: str
    data: Optional[dict[str, Any]] = None


class PipelineResult(BaseModel):
    classification: QueryClassification
    literature: LiteratureSummary
    genomic: Optional[GenomicResult] = None
    analysis: Optional[DeepAnalysis] = None
    brief: ResearchBrief

