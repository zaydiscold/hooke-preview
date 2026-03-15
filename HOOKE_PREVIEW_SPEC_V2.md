# HOOKE — Hackathon Preview Spec v2
**"If I have seen far, it is from standing on the shoulders of giants."**

---

## What Hooke Actually Is (Expanded)

Hooke is a domain-agnostic hard science research agent. The user is anyone doing rigorous, citation-dependent, structure-or-data-grounded research where the answer is not a Google search away. That includes biology but is not limited to it.

The core value is not "AI summarizes papers." It is:

> Given a research question, Hooke dispatches specialized agents to gather real data from authoritative scientific sources, synthesizes findings with citations, identifies a specific research gap, and proposes a concrete next experiment — in under 60 seconds.

The key differentiator from every existing tool (Undermind, SciSpace, Web of Science AI, Elicit): Hooke does not just retrieve and summarize. It takes action with computational tools — AlphaGenome, PDB, PubChem — and grounds the synthesis in actual data outputs, not just text.

---

## Expanded User Personas

### Persona 1 — Bench Biologist (original)
UCSF cancer researcher. Has a gene target, wants to know what's known and what experiment to run next. Comfortable with "chr17:43044295 A>G" as input.

### Persona 2 — Medicinal Chemist / Pharmaceutical Researcher
Designing a small molecule inhibitor. Wants to know: what's the binding affinity landscape for this target, what scaffolds have been tried, what ADMET liabilities exist, where are the unexplored regions of chemical space.
Tools Hooke adds for this user: PubChem API (compound data, bioactivity, structure), ChEMBL (drug-target interactions), RDKit via subprocess for SMILES parsing and property calculation, PDB for binding site structure.
Example query: "What small molecule scaffolds have been explored for KRAS G12C inhibition and what structural features distinguish the covalent vs non-covalent approaches?"

### Persona 3 — Materials Scientist
Working on MOFs (metal-organic frameworks) for carbon capture, or battery cathode materials, or catalyst design. Needs: recent synthesis literature, predicted crystal properties, known failure modes.
Tools: Materials Project API (free, crystal structure + property predictions), Crystallography Open Database, Tavily for recent preprints on arXiv Materials Science.
Example query: "What MOF topologies show highest CO2 selectivity over N2 at 1 bar and what synthesis challenges have prevented scale-up?"

### Persona 4 — Organic Chemist
Planning a multi-step synthesis. Needs retrosynthetic analysis, known reaction conditions from literature, reagent availability.
Tools: USPTO reaction database via PubChem, Reaxys-adjacent free sources, SMILES structure rendering.
Example query: "What are the most reliable synthetic routes to paclitaxel's oxetane ring and what are the key stereochemical challenges?"

### Persona 5 — Computational Physicist / Quantum Chemistry
Working on DFT calculations, needs to know what basis sets have been used for a specific system, what software packages are standard, what accuracy benchmarks exist.
Tools: Tavily + arXiv (physics.chem-ph, cond-mat sections), NIST Chemistry WebBook for spectroscopic data.

### What all these personas share:
- They work in hard science (experimental or computational)
- They deal with structures, sequences, compounds, or materials — not just text
- They need citations, not confident assertions
- They are not software engineers and shouldn't need to be
- They want a research brief, not a chat thread

---

## Architecture (Revised + Self-Critiqued)

### Core Pattern
```
Query -> Orchestrator (classifies + plans) -> Parallel Agent Dispatch -> Synthesis -> Streamed Output
```

### What Changed from V1

**Changed:** Mode 3 split into two distinct flows as requested.
**Added:** Chemistry agent stub (PubChem + ChEMBL) as a third parallel agent for compound/drug queries.
**Added:** Materials agent stub (Materials Project API) for non-bio hard science.
**Changed:** Structure agent elevated from stretch goal to Mode 4 proper.

### Revised Query Modes

**Mode 1 — Pure Literature**
No gene, compound, or material identifier present. General mechanistic or review question.
Dispatch: Literature Agent only.

**Mode 2 — Genomic Deep Dive**
Gene name, variant notation, or DNA sequence explicitly provided.
Dispatch: Literature Agent + AlphaGenome Agent in parallel.

**Mode 3 — Literature First, Then Genomic**
Open question mentions a disease/mechanism with a gene implicated but no specific variant.
Flow: Literature Agent -> orchestrator extracts key gene/locus from results -> AlphaGenome fires on extracted target.
Sequential, not parallel. This is intentional — you need the literature output to know what to query AlphaGenome with.

**Mode 4 — Structure Query**
Protein name, PDB ID, or SMILES string present.
Dispatch: Literature Agent + PDB/PubChem Agent in parallel.

**Mode 5 — Materials Query**
Material name, composition, or crystal system mentioned (MOF, perovskite, zeolite, battery cathode, etc).
Dispatch: Literature Agent + Materials Project API agent in parallel.

### Self-Critique of Architecture

**Problem 1 — The orchestrator has too many jobs.**
It classifies the query, writes a research plan, decides which agents to dispatch, and formats dispatch parameters. That's four distinct cognitive tasks in one LLM call. Risk: it gets one right and botches the others.

Fix: Split into two calls. First call: classification + plan (returns structured JSON). Second call: parameter extraction for each dispatched agent (pulls specific gene name, variant notation, compound name, etc from the query). Two small focused calls > one giant call.

**Problem 2 — "Sequential" in Mode 3 hides a latency bomb.**
Mode 3 requires: literature search completes -> orchestrator reads results -> extracts gene -> AlphaGenome call. That's 30-60 seconds for literature + 20-40 seconds for AlphaGenome + LLM overhead. Demo could be 2 minutes. Judges are watching.

Fix: In the UI, make the wait feel alive. Stream the literature results as they arrive (don't wait for full completion). Show "Agent found APOL1 G1 variant mentioned in 4 papers. Initiating AlphaGenome query..." as a real-time log line. The wait feels shorter when you can see what's happening.

**Problem 3 — Synthesis agent quality depends entirely on subagent output quality.**
If Literature Agent returns vague summaries and AlphaGenome returns raw numpy arrays, the synthesis agent will produce garbage. Garbage in, garbage out, even with a good synthesis prompt.

Fix: Each subagent has a strict output schema it must produce. Literature Agent returns structured objects: {title, year, doi, consensus_point, gap_identified}. AlphaGenome Agent returns a plain-English interpretation object: {top_tissue, expression_direction, quantile_score, biological_interpretation}. The synthesis agent gets clean structured inputs, not raw tool outputs.

**Problem 4 — AlphaGenome's GTF file.**
The gene annotation feather file (gencode.v46.annotation.gtf.gz.feather) is fetched from Google Storage on first use. It is 50-200MB and can take 30-60 seconds to download. In a demo this will look like the app is hanging.

Fix: Pre-download and cache it at startup. In main.py startup event, trigger a background fetch of the GTF file and cache it locally. By the time a judge asks a genomic question, it's already there.

---

## Skeptic Mode — Full Adversarial Pass

### Assumption 1: "AlphaGenome's API just works"
**Reality:** It's a pip install that calls Google's servers. It requires a Google API key that has AlphaGenome enabled. The key provided (AIzaSy...) is a Google API key, not an AlphaGenome-specific token. It needs to be validated against the AlphaGenome API specifically — not just any Google API key works.

**Blocker risk: HIGH.** If the key doesn't have AlphaGenome access enabled, the genomic agent is dead and Mode 2/3 don't work.

**Mitigation:** Test this FIRST before writing any other code. Run the quickstart notebook's first 5 lines locally right now. If it fails, you fall back to NCBI BLAST as the genomic agent (slower, less impressive, but functional).

---

### Assumption 2: "Nebius Token Factory LLM is OpenAI API compatible and just works"
**Reality:** Nebius says it's OpenAI-compatible but every provider has quirks. JSON mode, function calling, streaming — all need to be tested. The model list and exact model string matters.

**Blocker risk: MEDIUM.** If JSON mode doesn't work cleanly, orchestrator classification breaks.

**Mitigation:** First code written should be a 10-line Nebius API test: can it return valid JSON? Does streaming work? What's the exact model string? Test before building orchestrator logic around assumptions.

---

### Assumption 3: "The orchestrator will correctly classify query types"
**Reality:** "What do we know about APOL1 and kidney disease?" — does the orchestrator know APOL1 is a gene and not a drug? Does it know to run AlphaGenome on it? LLMs without domain knowledge can misclassify.

**Blocker risk: MEDIUM.** Wrong classification means wrong agents fire, output is useless.

**Mitigation:** The system prompt must give explicit examples of each query type. Include a few-shot classification prompt with 2-3 examples per mode. Test with your 4 demo questions before the judging hour.

---

### Assumption 4: "Tavily returns academic papers with DOIs"
**Reality:** Tavily is a web search API, not a PubMed API. It will return whatever is top-ranked on the web. For recent biotech topics this is often news articles, company blogs, and review summaries — not primary literature with DOIs.

**Blocker risk: MEDIUM-HIGH.** If the judge asks "show me the papers" and the literature agent returns TechCrunch articles, you look like a RAG app and worse.

**Mitigation:** Use Tavily for discovery (find what's out there) but ALWAYS pair with Entrez/PubMed for primary citation retrieval. The literature agent should: (1) Tavily search to identify key topics and recent developments, (2) Entrez esearch to get actual PubMed results with PMIDs and DOIs, (3) merge and return only results with DOIs. This is non-trivial to code but it's the difference between a demo that looks like a research tool and one that looks like a fancy Google.

---

### Assumption 5: "asyncio.gather() for parallel dispatch is straightforward"
**Reality:** AlphaGenome's SDK uses synchronous blocking calls internally. You cannot just asyncio.gather() a synchronous function. It will block the event loop and your "parallel" dispatch will actually be sequential.

**Blocker risk: HIGH.** This will make Mode 2 feel slow and break the "parallel agents" story.

**Mitigation:** Wrap AlphaGenome calls in asyncio.to_thread() to run them in a thread pool. Same for any other synchronous library calls.

```python
import asyncio
async def run_genomic_agent(params):
    return await asyncio.to_thread(alphagenome_sync_call, params)

results = await asyncio.gather(
    run_literature_agent(params),
    run_genomic_agent(params)
)
```

---

### Assumption 6: "SSE streaming is easy to implement"
**Reality:** FastAPI SSE with EventSourceResponse requires the starlette sse-starlette package. The client-side EventSource API in vanilla JS requires proper Content-Type headers. If you're also streaming LLM output token-by-token AND agent log lines, you need a unified event queue that multiple async tasks can write to simultaneously.

**Blocker risk: MEDIUM.** This is non-trivial if you haven't done it before.

**Mitigation:** Keep streaming simple. Do NOT try to stream LLM token-by-token. Instead stream at the "agent step" level: each agent posts one event when it starts and one event when it completes. The final synthesis result streams as one block. This is 80% of the visual effect with 20% of the complexity.

---

### Assumption 7: "Chemistry/Materials modes are achievable today"
**Reality:** You asked to expand to chemistry and materials science. The APIs exist (PubChem, Materials Project). But the orchestrator classification logic, agent code, and synthesis prompts all need to be written and tested for these domains. That is a full day of work per domain.

**Blocker risk: CERTAIN for today's hackathon.**

**Mitigation:** Do NOT build these today. The spec documents the vision. For the hackathon, ship bio-only (Modes 1-3). In your pitch say: "Today you see bio and genomics. The same architecture extends to chemistry and materials science — same orchestrator, different agents." Judges reward vision stated clearly, not half-built features.

---

### Assumption 8: "Research brief quality will impress judges who are not biologists"
**Reality:** Most hackathon judges are investors, founders, or ML engineers. They cannot evaluate whether the BRCA1 research brief is scientifically accurate. What they CAN evaluate is: does it look authoritative, are there real citations, does the demo work without errors.

**Implication:** Optimize for legibility and structure over scientific density. The brief should look like something you'd email a collaborator, not a supplementary methods section. Use clear section headers. Keep it to half a page. Judges read fast.

---

### Assumption 9: "The demo will work under judge pressure with live internet"
**Reality:** PubMed Entrez can rate-limit at conferences. Tavily can timeout. AlphaGenome can be slow. The synthesis LLM can return malformed JSON. You are demoing live over Shack15 wifi.

**Mitigation:** Have pre-cached demo results. Before judging, run all 4 sample queries and save the outputs to JSON files. If a live call fails, serve the cached output. Show the streaming log anyway. Judges don't know it's cached. Having a cached fallback is standard practice, not cheating.

---

### Assumption 10: "The app will be bug-free enough to demo in 4 hours"
**Reality check:** You are solo. No tests. No staging environment. Networking issues, import errors, and async bugs will happen.

**Mitigation:** Ship the simplest possible version that works end-to-end first. One mode, one working demo question, streamed output. Then layer features. Never spend more than 20 minutes stuck on any single bug — have a fallback that skips that feature. A working Mode 1 (literature only) beats a broken Mode 2 every time.

---

## UI — Brutalist Direction

(Note: zayd.wtf returned 403. Drop the GitHub repo link to pull exact colors/fonts. Below is the direction based on your stated preference for brutalist.)

**Brutalist design principles for Hooke:**
- Monospace or near-monospace font everywhere (IBM Plex Mono, JetBrains Mono, Courier Prime)
- High contrast black/white base — no gray gradients, no soft shadows
- Visible borders, thick rules, raw structural honesty
- Color used sparingly and with intention — one accent (acid green #00FF41 or electric yellow #FFE400 or raw cyan #00FFFF)
- No rounded corners on input elements
- No icons that soften the UI
- The "thinking" feed should look like a terminal output — monospace, timestamped, scrolling
- Final brief should be in a contrasting panel — white bg, black text, stark

**Layout (single page):**
```
[HOOKE] ─────────────────────────────────────
If I have seen far, it is from standing on the
shoulders of giants.
─────────────────────────────────────────────
> [research question input, full width, monospace]
  [INVESTIGATE] button — thick border, no radius

─────────────────────────────────────────────
AGENT LOG                    | RESEARCH BRIEF
─────────────────────────────|───────────────
[streaming terminal feed]    | [final output
[01:32] Orchestrator: Mode 2 |  renders here
[01:33] Literature: searching|  with sections
[01:34] AlphaGenome: loading |  and citations]
[01:35] Synthesis: writing...|
─────────────────────────────────────────────
```

**CSS hints:**
- background: #0A0A0A or #111111
- text: #F0F0F0 or #FFFFFF
- accent: #00FF41 (terminal green) — used for borders, button hover, agent name prefix
- font-family: 'IBM Plex Mono', monospace
- border: 2px solid #F0F0F0 everywhere
- no box-shadow
- no transition animations except for text streaming

---

## Build Order (Revised, Time-Realistic)

**First 30 min — Scaffold + API validation**
Run AlphaGenome quickstart. Test Nebius LLM with JSON mode. Test Tavily search. If any fail, pivot immediately. Do not build on unvalidated integrations.

**Hour 1 — Working end-to-end pipeline (Mode 1 only)**
FastAPI app, one POST endpoint, Nebius orchestrator returns a plan, Literature agent (Tavily only, skip PubMed for now), synthesis agent returns a brief. Static HTML UI shows the output. No streaming yet. Just works.

**Hour 2 — Add streaming + AlphaGenome**
Wire SSE. Implement asyncio.to_thread wrapping for AlphaGenome. Add Mode 2 path. Test BRCA1 demo question end to end. Pre-cache the GTF file at startup.

**Hour 3 — Harden + UI**
Add PubMed Entrez to literature agent. Apply brutalist theme to UI. Add agent log panel. Test all 4 demo questions. Save cached fallback outputs.

**Hour 4 — Buffer + submission**
Record Loom demo video. Write README. Submit. Do not add features in this hour. Debug only.

---

## Pitch (Revised)

"Hooke is a hard science research agent — for biologists, chemists, and materials scientists. Like Dexter for finance and Shannon for security, Hooke is the domain specialist for lab science. It dispatches real computational tools in parallel — live literature from PubMed and Tavily, genomic predictions from Google DeepMind's AlphaGenome — synthesizes the outputs into a cited research brief, and proposes a concrete next experiment. The target user is the UCSF researcher who spends 3 hours reviewing papers before they can ask the right question. Hooke does that in 60 seconds. Today you're seeing the bio preview. The same architecture extends to chemistry and materials science — same orchestrator, different agents."

---

## Competitors to Know (for judge Q&A)

**Undermind** — literature search only, no computational tools, no synthesis, subscription-based.
**SciSpace** — paper Q&A and summarization, pure RAG, no agents.
**Elicit** — structured literature review, no genomic/structural tools.
**Perplexity for Science** — web search with citations, no domain-specific tools.
**BioArena** — closest competitor, builds workflows for protein design, but requires technical setup, not conversational.

**Hooke's differentiation:** It is the only tool that combines conversational input, live literature retrieval, AND a real computational biology model (AlphaGenome) in a single agentic pipeline, with zero setup for the end user.

---

*Rotate all API keys after the hackathon.*
*zayd.wtf theme: drop GitHub repo link to apply exact colors/fonts.*
