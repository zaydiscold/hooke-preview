# Hooke

![GitHub last commit](https://img.shields.io/github/last-commit/zaydiscold/hooke-preview)
![GitHub Repo stars](https://img.shields.io/github/stars/zaydiscold/hooke-preview?style=flat)
![Status](https://img.shields.io/badge/status-preview-475569)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)
![Frontend](https://img.shields.io/badge/frontend-HTML%2FCSS%2FJS-f59e0b)
![Streaming](https://img.shields.io/badge/streaming-SSE-0f172a)

Hooke is an agent-orchestrated research assistant for hard-science questions.
It runs a FastAPI backend, retrieves evidence from scientific and web sources,
optionally adds genomic follow-up, and returns a citation-grounded research
brief in a streaming interface.

## Overview

This repository contains a local research workflow for questions that need
source collection, synthesis, and explicit next-step reasoning. A user submits
a question, Hooke classifies the request into one of three investigation modes,
runs the relevant agents, and streams both intermediate logs and the final
brief to the browser.

## What the app does

Hooke provides these capabilities:

- Retrieves literature from PubMed, Semantic Scholar, Tavily, OpenAlex, and
  arXiv through the literature pipeline.
- Selects among three investigation modes: literature-only, parallel genomic
  follow-up, or literature-first gene discovery followed by genomic analysis.
- Streams agent progress and final output to the frontend through server-sent
  events.
- Uses AlphaGenome when available and falls back to Ensembl-based genomic
  interpretation when needed.
- Produces a structured research brief with findings, research gaps, proposed
  experiments, and citations.
- Generates compact lucky-mode starter queries for exploratory research.

## Architecture

The application is split into a small number of focused components:

- `main.py`: FastAPI entrypoint, static file serving, lucky-query handling, and
  SSE endpoints.
- `orchestrator.py`: query classification, mode routing, and pipeline control.
- `agents/literature.py`: source retrieval, filtering, and paper analysis.
- `agents/genomic.py`: AlphaGenome and Ensembl-backed genomic analysis.
- `agents/synthesis.py`: brief generation and JSON normalization.
- `static/index.html`: single-page interface for queries, logs, and research
  briefs.
- `health_check.py`: provider and API connectivity checks.

## Requirements

Set up the app from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

The environment file must define these variables:

- `NEBIUS_API_KEY`
- `OPENROUTER_API_KEY`
- `TAVILY_API_KEY`
- `GOOGLE_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY` for higher Semantic Scholar rate limits
- `PUBMED_EMAIL`

## Run locally

Start the development server with Uvicorn:

```bash
uvicorn main:app --reload --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Health check

Run the connectivity check before a demo or local test session:

```bash
python3 health_check.py
```

This script verifies whether the configured providers are reachable.

## Example questions

These prompts match the current demo flow:

1. How does Ozempic actually work at the molecular level, and why does it cause
   muscle loss?
2. What tissues is the `LCT` gene most active in, and why can some adults
   digest milk while others cannot?
3. Why do some people get severe kidney disease, and what genes are involved?
4. What makes some cancer tumors resistant to PD-1 or PD-L1 immunotherapy?

## Operational notes

Keep these constraints in mind when you run the app:

- Semantic Scholar can rate-limit unauthenticated requests.
- AlphaGenome is optional; Hooke falls back to Ensembl-based interpretation if
  AlphaGenome is unavailable.
- Prompt-injection evaluation is not implemented yet. Promptfoo is a planned
  addition for future prompt-injection testing and security review.
- Generated cache files remain local and are excluded from git.
