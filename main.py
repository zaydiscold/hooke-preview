from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from config import settings
from orchestrator import run_pipeline
from schemas import AgentEvent, InvestigateRequest

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm model endpoints with low-cost checks so first user request is smoother.
    from openai import OpenAI

    def _warmup() -> None:
        try:
            client = OpenAI(base_url=settings.nebius_base_url, api_key=settings.nebius_api_key, timeout=20)
            _ = client.models.list()
        except Exception:
            pass
        try:
            import requests
            requests.post(
                "https://api.tavily.com/search",
                json={"api_key": settings.tavily_api_key, "query": "TP53", "max_results": 1},
                timeout=(3, 8),
            )
        except Exception:
            pass

    await asyncio.to_thread(_warmup)
    yield


app = FastAPI(title="Hooke MVP", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


def _cache_key(query: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in query.strip())[:120]
    return safe.strip("_") or "query"


def _normalize_lucky_query(raw: str) -> str:
    cleaned = " ".join((raw or "").replace("\n", " ").replace("\t", " ").split()).strip(" \"'")
    cleaned = cleaned.rstrip("?.!,;:")
    tokens = re.findall(r"[A-Za-z0-9-]+", cleaned)
    stopwords = {
        "a", "activity", "an", "and", "at", "by", "can", "could", "does", "do", "enhance",
        "exacerbate", "exacerbating", "explain", "for", "how", "in", "is",
        "induction", "it", "its", "of", "on", "or", "promote", "selective",
        "targeted", "that", "the", "their", "to", "what", "whether", "why",
        "with", "without",
    }
    words = [token for token in tokens if token.lower() not in stopwords]
    if not words:
        return ""
    return " ".join(words[:8])


async def _replay_cached_events(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = payload.get("events", [])
    for ev in events:
        normalized = dict(ev) if isinstance(ev, dict) else {}
        if normalized.get("event") == "done":
            normalized["event"] = "complete"
        yield {"event": "message", "data": json.dumps(normalized)}
        await asyncio.sleep(0.12)


@app.post("/api/investigate")
async def investigate(req: InvestigateRequest) -> EventSourceResponse:
    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        all_events: list[dict[str, Any]] = []
        should_write_cache = True

        async def emitter(agent_event: AgentEvent):
            payload = agent_event.model_dump()
            all_events.append(payload)
            await queue.put(payload)

        async def run():
            try:
                await emitter(
                    AgentEvent(
                        timestamp=_utc_now_iso(),
                        agent="system",
                        event="start",
                        message="Investigation started.",
                        data={"query": req.query},
                    )
                )
                result = await run_pipeline(req.query, emitter)
                final_payload = {
                    "timestamp": _utc_now_iso(),
                    "agent": "result",
                    "event": "complete",
                    "message": "Final brief ready.",
                    "data": result.model_dump(),
                }
                all_events.append(final_payload)
                await queue.put(final_payload)
            except Exception as exc:
                cache_file = CACHE_DIR / f"{_cache_key(req.query)}.json"
                if not cache_file.exists():
                    demos = sorted(CACHE_DIR.glob("demo_*.json"))
                    if demos:
                        cache_file = demos[0]
                if cache_file.exists():
                    replay_msg = {
                        "timestamp": _utc_now_iso(),
                        "agent": "system",
                        "event": "progress",
                        "message": f"Live run failed, replaying cached result: {exc}",
                        "data": None,
                    }
                    await queue.put(replay_msg)
                    await queue.put({"__disable_cache_write__": True})
                    await queue.put({"__replay_cache__": str(cache_file)})
                    return
                err_payload = {
                    "timestamp": _utc_now_iso(),
                    "agent": "system",
                    "event": "error",
                    "message": f"Pipeline failed: {exc}",
                    "data": None,
                }
                await queue.put(err_payload)
            finally:
                await queue.put({"__end__": True})

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item.get("__disable_cache_write__"):
                    should_write_cache = False
                    continue
                if "__replay_cache__" in item:
                    replay_path = Path(item["__replay_cache__"])
                    async for replay_event in _replay_cached_events(replay_path):
                        yield replay_event
                    continue
                if item.get("__end__"):
                    if should_write_cache and all_events:
                        cache_path = CACHE_DIR / f"{_cache_key(req.query)}.json"
                        cache_path.write_text(
                            json.dumps(
                                {"query": req.query, "events": all_events},
                                ensure_ascii=False,
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                    break
                yield {"event": "message", "data": json.dumps(item)}
        finally:
            task.cancel()

    return EventSourceResponse(event_generator())


@app.get("/api/lucky")
async def lucky() -> dict[str, str]:
    """Generate one short exploratory research query via Nebius."""
    import random

    from openai import OpenAI

    domains = [
        "quantum biology",
        "brain organoids",
        "extremophile adaptation",
        "epigenetic inheritance",
        "non-coding RNA",
        "convergent evolution",
        "aging biology",
        "antibiotic resistance",
        "neural correlates of consciousness",
        "neurodegeneration",
        "horizontal gene transfer",
        "microbiome-host signaling",
        "bioelectric tissue patterning",
        "RNA editing",
        "mitochondrial signaling",
        "gut microbiota metabolism",
        "cellular senescence",
        "deep sea bioluminescence",
        "magnetoreception",
        "cryptobiosis",
    ]
    domain = random.choice(domains)

    client = OpenAI(
        base_url=settings.nebius_base_url,
        api_key=settings.nebius_api_key,
        timeout=15,
    )
    try:
        resp = client.chat.completions.create(
            model=settings.nebius_fast_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate one short exploratory hard-science query for a research app. "
                        "Return exactly one line. "
                        "The query must be 3 to 8 words, plain and compact, and usable as a starting point for exploratory research. "
                        "Focus on one mechanism, entity, or relationship, with at most one bridge concept. "
                        "Prefer noun phrases or very short question-like queries. "
                        "Do not write thesis questions, long clauses, or multi-part prompts. "
                        "Do not use words like can, could, does, whether, without, enhance, promote, exacerbate, explain why, or what determines. "
                        "Do not use punctuation except hyphens when necessary. "
                        "Examples: immunoproteasome senescent cells; senescent cells CD8 T cell recognition; microbiome host gene expression."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Domain: {domain}. "
                        "Generate one connected exploratory query that feels biologically sensible and narrow enough to investigate."
                    ),
                },
            ],
            max_tokens=32,
        )
        q = _normalize_lucky_query(resp.choices[0].message.content)
        if not q:
            raise ValueError("Lucky query was empty after normalization")
        return {"question": q, "domain": domain, "model": settings.nebius_fast_model}
    except Exception:
        fallbacks = [
            "mitochondrial signaling caloric restriction",
            "gut microbiota horizontal gene transfer",
            "bird magnetoreception quantum coherence",
            "programmed senescence escape mechanisms",
            "extracellular vesicle stress signaling",
            "early tumor driver mutations",
            "embryonic bioelectric body patterning",
        ]
        return {"question": random.choice(fallbacks), "domain": domain, "model": "fallback"}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "model": settings.nebius_fast_model}
