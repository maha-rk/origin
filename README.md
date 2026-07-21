# ORIGIN

**Find the cause, not the symptom.**

ORIGIN is an autonomous multi-agent system that investigates real-world
environmental and land-use claims — deforestation, protected-area
encroachment, water risk, carbon offset legitimacy — against real,
verifiable evidence, and produces a traceable, confidence-scored verdict.
It is not a chatbot and not a RAG-style retrieval answer: give it a claim
tied to a physical location, and eleven agents fan out across real
satellite, ecological, and climate data sources to check it, then
cross-reference every finding against the claim's exact wording before a
verdict is synthesized.

Built solo for the AI House × Google for Developers **AI Agent Builder
Series 2026** hackathon.

## What it does

1. **Understand the claim.** Location Grounding resolves the claim's
   location to coordinates; Claim Decomposition splits compound claims
   ("reduced emissions by 40% *and* has no protected areas nearby") into
   independently checkable parts — the two run concurrently.
2. **Gather evidence in parallel.** Seven agents fan out at once against
   real registries: tree-cover loss (Global Forest Watch), protected areas
   (WDPA), water/disaster risk (GDACS), satellite visual inspection
   (Gemini multimodal), vegetation trend (Google Earth Engine NDVI), carbon
   offset project registries (Carbonmark), and long-run climate trend
   (NASA POWER).
3. **Cross-reference and decide.** Cross-Reference judges each piece of
   evidence against the claim's exact wording — including negation ("no
   deforestation" + a real tree-loss finding = contradiction, not
   support) — then Verdict Synthesis produces a direction score, an
   evidence-coverage score, and a written verdict with full source
   citations. It never asserts a claim is definitively true or false;
   everything is framed as evidence for a human reviewer to weigh.

If the location can't be resolved with reasonable confidence, ORIGIN stops
and asks for a more specific location. It never guesses harder or attempts
entity resolution (mapping a company name to a specific facility) — that's
a deliberately separate, unscoped problem.

## Tech stack

**Google:**
- **Gemini** (via **Vertex AI** Express Mode) — multimodal visual
  inspection of satellite imagery, evidence cross-referencing, verdict
  synthesis, claim decomposition, location-signal extraction. Every call
  uses Gemini's native structured-output mode (`response_schema`), not
  prompt-and-hope JSON.
- **Google ADK** (Agent Development Kit) — the whole pipeline is a real
  `SequentialAgent`/`ParallelAgent` graph, not sequential function calls
  dressed up as agents. Location Grounding and Claim Decomposition run
  concurrently; all seven evidence agents fan out together once a location
  resolves.
- **A2A** (Agent2Agent protocol) — every inter-agent handoff is a real,
  structured `a2a.types.Message`, not an ad hoc dict.
- **MCP** (Model Context Protocol) — a real `FastMCP` server
  (`mcp_servers/origin_tools.py`) exposes the data-fetching tools; Land
  Analysis, Ecology, and Water Risk route through it as a genuine stdio
  subprocess, not an in-process function call pretending to be one.
- **Google Earth Engine** — real NDVI (vegetation-health) queries via the
  Sentinel-2 collection.

**Real data sources (no fabricated or seeded data anywhere):**
Global Forest Watch, WDPA, GDACS, Nominatim/OpenStreetMap, Carbonmark
(aggregating Verra/Gold Standard/Puro registries), NASA POWER, Esri World
Imagery (the actual satellite crop Gemini's visual inspection reads).

**Delivery:** FastAPI + Server-Sent Events — the browser sees each agent's
result the moment it lands, not a spinner-then-answer.

## Getting started

### Prerequisites
- Python (developed and tested on 3.14)
- A [Gemini API key](https://aistudio.google.com/apikey) — see
  `agents/gemini_config.py` if you hit a `limit: 0` quota wall on a plain
  AI Studio key; this project routes through Vertex AI Express Mode
  instead, which has a separate, genuinely free quota pool.
- A [Global Forest Watch](https://www.globalforestwatch.org/) account and
  API key — run `python3 scripts/gfw_create_key.py` to generate one (your
  password stays local, typed via `getpass`, never leaves your terminal).

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# fill in GEMINI_API_KEY and GFW_API_KEY
```

`EARTH_ENGINE_PROJECT` is optional — Vegetation Trend degrades gracefully
(reports "no signal") without it. To enable it, register a Cloud project
for Earth Engine's free noncommercial Community tier
(console.cloud.google.com/earth-engine) and run `earthengine authenticate`
once locally.

### Run

```bash
uvicorn server.app:app --reload
```

Open `http://localhost:8000`. The Investigations tab is where you submit a
claim; Layers explains the real tech stack in more depth; Saved reports is
a history of everything you've investigated.

There's also a CLI for a single claim without the UI:

```bash
python3 -m orchestrator.pipeline "the palm oil expansion at -9.98,-63.0 in Rondonia, Brazil caused no deforestation"
```

## Project structure

```
agents/            Gemini-backed reasoning agents (location grounding,
                    claim decomposition, visual inspection, cross-reference,
                    verdict synthesis)
data_clients/       Thin, real API clients per data source (GFW, WDPA,
                    GDACS, Earth Engine, Carbonmark, NASA POWER, Nominatim)
orchestrator/       ADK pipeline composition, A2A messaging, MCP client,
                    evidence/claims log
mcp_servers/        The MCP tool server the pipeline's evidence agents
                    call into
server/             FastAPI app + the frontend (vanilla HTML/CSS/JS, no
                    build step)
docs/brief.md       The original project brief and scope boundaries
```

## Known limitations

- **GDACS has a confirmed coverage gap over South Asia** — a large swath
  including Bengaluru, Chennai, Hyderabad, and even Colombo 404s on every
  geometry/radius tested, while Mumbai, Delhi, and Bangladesh work fine on
  the identical code path. This is a real gap in GDACS's own spatial
  index, not a bug in this project — Water Risk treats it as "no
  coverage" (an honest absence of signal), never a fabricated result.
- **Cloud Run isn't wired in** — there's no live deployment, so the app
  currently only runs locally. It would need a billing-enabled GCP
  project, which this build has avoided so far the same way it avoided
  one for Earth Engine (solved instead via Vertex AI Express Mode's
  genuinely free quota pool, an option that doesn't exist for Cloud Run).
- **The claims log runs on local SQLite, not BigQuery**
  (`orchestrator/claims_log.py`) — same billing constraint. The row shape
  is deliberately BigQuery-insert-ready if that changes.
- **ReliefWeb** was evaluated and skipped — its API now requires a
  pre-approved `appname` (manual registration, confirmed via a live 403),
  not worth blocking on external approval outside anyone's control.
- Entity resolution (mapping "Company X" to a specific facility) is a
  deliberate non-goal, not a gap — see `docs/brief.md` for the reasoning.
