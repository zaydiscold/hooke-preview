from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import requests
from openai import OpenAI

from config import settings


@dataclass
class CheckResult:
    ok: bool
    detail: str
    extra: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if self.extra is None:
            payload.pop("extra")
        return payload


def check_nebius() -> CheckResult:
    if not settings.nebius_api_key:
        return CheckResult(ok=False, detail="missing NEBIUS_API_KEY")
    try:
        client = OpenAI(base_url=settings.nebius_base_url, api_key=settings.nebius_api_key)
        models = client.models.list()
        count = len(getattr(models, "data", []))
        return CheckResult(ok=True, detail="connected", extra={"models_found": count})
    except Exception as exc:
        return CheckResult(ok=False, detail=str(exc))


def check_tavily() -> CheckResult:
    if not settings.tavily_api_key:
        return CheckResult(ok=False, detail="missing TAVILY_API_KEY")
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": settings.tavily_api_key, "query": "TP53", "max_results": 1},
            timeout=(5, 20),
        )
        resp.raise_for_status()
        return CheckResult(
            ok=True,
            detail="connected",
            extra={"results": len(resp.json().get("results", []))},
        )
    except Exception as exc:
        return CheckResult(ok=False, detail=str(exc))


def check_semantic_scholar() -> CheckResult:
    try:
        resp = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": "TP53", "limit": 1, "fields": "title"},
            timeout=(5, 20),
        )
        ok = resp.status_code == 200
        detail = "connected" if ok else f"http_{resp.status_code}"
        return CheckResult(ok=ok, detail=detail, extra={"status_code": resp.status_code})
    except Exception as exc:
        return CheckResult(ok=False, detail=str(exc))


def check_alphagenome() -> CheckResult:
    if not settings.google_api_key:
        return CheckResult(ok=False, detail="missing GOOGLE_API_KEY")
    try:
        from alphagenome.models import dna_client

        # Lightweight availability check: verify import + client creation only.
        dna_client.create(settings.google_api_key)
        return CheckResult(
            ok=True,
            detail="client_created",
            extra={"sequence_window": dna_client.SEQUENCE_LENGTH_1MB},
        )
    except Exception as exc:
        return CheckResult(ok=False, detail=str(exc))


if __name__ == "__main__":
    report = {
        "nebius": check_nebius().to_dict(),
        "tavily": check_tavily().to_dict(),
        "semantic_scholar": check_semantic_scholar().to_dict(),
        "alphagenome": check_alphagenome().to_dict(),
    }
    print(json.dumps(report, indent=2))
