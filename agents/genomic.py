from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from math import floor
from typing import Any, Awaitable, Callable

import requests
from alphagenome.models import dna_client

from config import settings
from schemas import AgentEvent, GenomicResult

EventEmitter = Callable[[AgentEvent], Awaitable[None]]

TISSUE_ONT = {
    "brain": "UBERON:0000955",
    "lung": "UBERON:0002048",
    "liver": "UBERON:0002107",
    "kidney": "UBERON:0002113",
    "breast": "UBERON:0000310",
    "blood": "UBERON:0000178",
    "intestine": "UBERON:0002108",
}

ALPHAGENOME_SUPPORTED_LENGTHS = (16384, 131072, 524288, 1048576)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def _emit(emitter: EventEmitter | None, event: str, message: str, data: dict[str, Any] | None = None) -> None:
    if emitter is None:
        return
    await emitter(
        AgentEvent(
            timestamp=_utc_now_iso(),
            agent="genomic",
            event=event,  # type: ignore[arg-type]
            message=message,
            data=data,
        )
    )


def _extract_gene_fallback(query: str) -> str | None:
    tokens = [token.strip(",.():;[]{}") for token in query.split()]
    for token in tokens:
        if token.isupper() and 2 <= len(token) <= 10 and token.isalpha():
            return token
    return None


def _fetch_gene_coords(gene: str) -> tuple[str, int, int]:
    url = f"https://rest.ensembl.org/lookup/symbol/homo_sapiens/{gene}"
    resp = requests.get(url, params={"content-type": "application/json"}, timeout=(5, 20))
    resp.raise_for_status()
    payload = resp.json()
    return payload["seq_region_name"], int(payload["start"]), int(payload["end"])


def _fetch_sequence(chrom: str, start: int, end: int) -> str:
    region = f"{chrom}:{start}-{end}"
    url = f"https://rest.ensembl.org/sequence/region/human/{region}"
    resp = requests.get(url, params={"content-type": "text/plain"}, timeout=(5, 20))
    resp.raise_for_status()
    return resp.text.strip()


def _pick_supported_window_length(gene_length: int) -> int:
    desired = min(max(gene_length + 20000, ALPHAGENOME_SUPPORTED_LENGTHS[0]), ALPHAGENOME_SUPPORTED_LENGTHS[-1])
    supported = [length for length in ALPHAGENOME_SUPPORTED_LENGTHS if length >= desired]
    return supported[0] if supported else ALPHAGENOME_SUPPORTED_LENGTHS[-1]


def _fetch_structure_metadata(gene: str) -> dict[str, Any]:
    uniprot_url = "https://rest.uniprot.org/uniprotkb/search"
    resp = requests.get(
        uniprot_url,
        params={
            "query": f'gene_exact:{gene} AND organism_id:9606 AND reviewed:true',
            "fields": "accession,protein_name,gene_names",
            "format": "json",
            "size": 1,
        },
        timeout=(5, 20),
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        return {}

    top = results[0]
    accession = top.get("primaryAccession")
    if not accession:
        return {}

    protein_name = (
        top.get("proteinDescription", {})
        .get("recommendedName", {})
        .get("fullName", {})
        .get("value")
    )

    af_resp = requests.get(
        f"https://alphafold.ebi.ac.uk/api/prediction/{accession}",
        timeout=(5, 20),
    )
    if af_resp.status_code == 404:
        return {
            "protein_name": protein_name,
            "uniprot_accession": accession,
        }
    af_resp.raise_for_status()
    payload = af_resp.json()
    if not payload:
        return {
            "protein_name": protein_name,
            "uniprot_accession": accession,
        }

    model = payload[0]
    return {
        "protein_name": protein_name,
        "uniprot_accession": accession,
        "structure_model_id": model.get("modelEntityId") or model.get("entryId"),
        "structure_source": "AlphaFold DB",
        "structure_source_url": f"https://alphafold.ebi.ac.uk/entry/{accession}",
        "structure_pdb_url": model.get("pdbUrl"),
        "structure_cif_url": model.get("cifUrl"),
        "structure_pae_url": model.get("paeDocUrl"),
        "structure_pae_image_url": model.get("paeImageUrl"),
        "structure_confidence": model.get("globalMetricValue"),
    }


def _pick_tissues(query: str) -> list[str]:
    q = query.lower()
    selected: list[str] = []
    for keyword, ont in TISSUE_ONT.items():
        if keyword in q:
            selected.append(ont)
    if not selected:
        selected = [TISSUE_ONT["blood"], TISSUE_ONT["lung"], TISSUE_ONT["brain"]]
    return selected[:3]


def _run_alphagenome_sync(gene: str, query: str) -> GenomicResult:
    chrom, start, end = _fetch_gene_coords(gene)
    gene_length = max(1, end - start + 1)
    window_length = _pick_supported_window_length(gene_length)
    flank = max(0, floor((window_length - gene_length) / 2))
    window_start = max(1, start - flank)
    window_end = window_start + window_length - 1
    seq = _fetch_sequence(chrom, window_start, window_end)
    centered = seq[:window_length].center(window_length, "N")
    model = dna_client.create(settings.google_api_key)
    output = model.predict_sequence(
        sequence=centered,
        requested_outputs=[dna_client.OutputType.DNASE, dna_client.OutputType.CAGE],
        ontology_terms=_pick_tissues(query),
    )

    dnase = output.dnase.values
    cage = output.cage.values
    dnase_peak = float(dnase.max()) if hasattr(dnase, "max") else None
    cage_peak = float(cage.max()) if hasattr(cage, "max") else None

    from config import get_nebius_client
    client = get_nebius_client()
    interp = client.chat.completions.create(
        model=settings.nebius_fast_model,
        messages=[
            {
                "role": "system",
                "content": "You are a computational genomics interpreter. Return concise plain text only.",
            },
            {
                "role": "user",
                "content": (
                    f"Gene: {gene}\nQuery: {query}\n"
                    f"Region: chr{chrom}:{start}-{end}\n"
                    f"DNASE peak: {dnase_peak}\nCAGE peak: {cage_peak}\n"
                    "Interpret the likely biological significance in 3-4 sentences."
                ),
            },
        ],
    )
    interpretation = (interp.choices[0].message.content or "").strip()
    structure = _fetch_structure_metadata(gene)
    return GenomicResult(
        gene=gene,
        region=f"chr{chrom}:{start}-{end}",
        top_tissue=None,
        expression_direction="elevated" if (cage_peak or 0) > 0 else "unknown",
        quantile_score=dnase_peak,
        **structure,
        interpretation=interpretation or "Genomic interpretation unavailable.",
    )


def _run_ensembl_fallback_sync(gene: str, query: str) -> GenomicResult:
    chrom, start, end = _fetch_gene_coords(gene)
    from config import get_nebius_client
    client = get_nebius_client()
    interp = client.chat.completions.create(
        model=settings.nebius_fast_model,
        messages=[
            {"role": "system", "content": "You are a computational genomics assistant."},
            {
                "role": "user",
                "content": (
                    f"Gene: {gene}\nRegion: chr{chrom}:{start}-{end}\nQuery: {query}\n"
                    "AlphaGenome was unavailable. Give a cautious interpretation using known gene locus context."
                ),
            },
        ],
    )
    structure = _fetch_structure_metadata(gene)
    return GenomicResult(
        gene=gene,
        region=f"chr{chrom}:{start}-{end}",
        **structure,
        interpretation=(interp.choices[0].message.content or "").strip() or "Fallback interpretation unavailable.",
    )


async def run_genomic_agent(query: str, gene_name: str | None, emitter: EventEmitter | None = None) -> GenomicResult:
    gene = gene_name or _extract_gene_fallback(query)
    if not gene:
        raise ValueError("No gene found for genomic analysis.")

    await _emit(emitter, "start", f"Running genomic analysis for {gene}")
    try:
        result = await asyncio.to_thread(_run_alphagenome_sync, gene, query)
        await _emit(
            emitter,
            "complete",
            "AlphaGenome analysis complete.",
            {
                "gene": gene,
                "region": result.region,
                "structure_model_id": result.structure_model_id,
                "uniprot_accession": result.uniprot_accession,
            },
        )
        return result
    except Exception as exc:
        await _emit(emitter, "error", f"AlphaGenome failed, using Ensembl fallback: {exc}")
        fallback = await asyncio.to_thread(_run_ensembl_fallback_sync, gene, query)
        await _emit(
            emitter,
            "complete",
            "Fallback genomic analysis complete.",
            {
                "gene": gene,
                "region": fallback.region,
                "structure_model_id": fallback.structure_model_id,
                "uniprot_accession": fallback.uniprot_accession,
            },
        )
        return fallback
