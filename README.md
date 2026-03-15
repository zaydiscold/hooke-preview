# Hooke

Hooke is a FastAPI research app for hard-science questions. It combines
literature retrieval, optional genomic follow-up, and a streaming investigation
UI that produces a concise research brief with source-backed findings.

## About

Hooke is built for questions that need more than a quick search result. You
submit a scientific question, Hooke classifies the request, gathers evidence
from multiple research sources, and returns a brief that highlights key
findings, open gaps, and a concrete next experiment.

## Features

- Literature retrieval from PubMed, Semantic Scholar, and Tavily
- Three investigation modes for literature-only, parallel genomic follow-up,
  and literature-first gene discovery
- Server-sent event streaming for live agent logs and final brief delivery
- AlphaGenome integration with an Ensembl-based fallback path
- Brutalist single-page interface for fast demos and local research workflows

## Tech stack

Hooke uses FastAPI for the backend, a lightweight vanilla HTML frontend for the
UI, and OpenAI-compatible providers for orchestration and synthesis calls.
Scientific retrieval and enrichment are handled through PubMed, Semantic
Scholar, Tavily, Ensembl, and AlphaGenome.

## Getting started

Start from the project root and install the Python dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your API keys to `.env` before you run the app.

## Environment variables

The app expects these values in `.env`:

- `NEBIUS_API_KEY`
- `OPENROUTER_API_KEY`
- `TAVILY_API_KEY`
- `GOOGLE_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY` for higher rate limits
- `PUBMED_EMAIL`

## Run locally

Launch the server with Uvicorn.

```bash
uvicorn main:app --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

## Health check

Run the provider check before a demo or local test session.

```bash
python3 health_check.py
```

This reports whether the required providers are configured and reachable.

## Example prompts

1. How does Ozempic actually work at the molecular level and why does it cause
   muscle loss?
2. What tissues is the LCT gene most active in and why can some adults digest
   milk while others cannot?
3. Why do some people get severe kidney disease and what genes are involved?
4. What makes some cancer tumors resistant to immunotherapy?

## Project structure

- `main.py`: FastAPI app, static file serving, and SSE endpoints
- `orchestrator.py`: query classification, deep analysis, and pipeline routing
- `agents/`: literature, genomic, and synthesis agent logic
- `static/index.html`: frontend interface
- `health_check.py`: provider connectivity checks

## Notes

- Semantic Scholar can rate-limit unauthenticated requests.
- If AlphaGenome is unavailable, Hooke falls back to Ensembl-based genomic
  interpretation.
- Generated cache files are excluded from git and stay local.
