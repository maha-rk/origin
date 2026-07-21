<div align="center">

# 🌿 ORIGIN

**Find the cause, not the symptom.**

![Gemini](https://img.shields.io/badge/Gemini-Vertex%20AI-7a4fa0)
![Google ADK](https://img.shields.io/badge/Google%20ADK-Multi--Agent-4c8f68)
![MCP](https://img.shields.io/badge/MCP-Real%20Tool%20Calls-163826)
![A2A](https://img.shields.io/badge/A2A-Agent2Agent-2f5d43)
![Earth Engine](https://img.shields.io/badge/Earth%20Engine-NDVI-1f8a8c)
![Global Forest Watch](https://img.shields.io/badge/Global%20Forest%20Watch-Tree%20Loss-a9762c)
![FastAPI](https://img.shields.io/badge/FastAPI-Live%20SSE-3a6a8c)
![Python](https://img.shields.io/badge/Python-3.14-1c1b19)

</div>

---

Most "AI agent" demos ask an LLM a question and print whatever it says
back. That always bothered me — a model can sound completely certain about
something it just made up. So ORIGIN doesn't work that way. You give it a
claim about a place — "this site had no deforestation," "there's no
protected area nearby," "this project reduced emissions by 40%" — and it
refuses to just answer. It goes and checks: real satellite data, real
government registries, real vegetation indices, actually pulled for the
actual coordinates in your claim. Only after eleven agents come back with
real findings does anything get synthesized into a verdict, and even then
it's phrased as evidence for a human to weigh, not a verdict handed down
from on high.

I built the whole thing solo, and most of the actual work went into
resisting the urge to fake anything — no seeded data, no "trust me" scores,
no black-box confidence numbers. If ORIGIN says a claim is contradicted,
you can click through to the exact hectare count, the exact NDVI delta,
the exact source it came from.

## How it actually works

**1. Understand the claim.** Location Grounding pulls a place out of the
claim text and resolves it to coordinates. Claim Decomposition splits
compound claims ("reduced emissions by 40% *and* has no protected areas
nearby") into pieces that can be checked independently. These two run at
the same time — neither needs the other's output.

**2. Go find out.** Seven agents fan out in parallel, each hitting a real
data source: tree-cover loss from Global Forest Watch, protected-area
proximity from WDPA, water/disaster risk from GDACS, a Gemini vision pass
over actual satellite imagery, vegetation trend from Earth Engine's NDVI,
carbon-offset project registries via Carbonmark, and long-run climate
trend from NASA POWER. If a source has nothing to say, it says nothing —
no fabricated "insufficient data" filler dressed up as a real result.

**3. Weigh it, then decide.** Cross-Reference goes through every finding
and checks it against the claim's *exact* wording — this is the part that
actually catches things, like noticing "no deforestation" plus a real
tree-loss finding is a contradiction, not two unrelated facts. Verdict
Synthesis then turns that into a direction score, a coverage score, and a
written verdict with every citation intact. It won't tell you a claim is
definitively true or false — it tells you what the evidence says and lets
you decide.

If it can't pin down a location with real confidence, it stops and asks
instead of guessing. It also won't try to resolve "Company X" into a
specific facility — that's a different, harder problem, and bolting a bad
guess onto it would undermine everything downstream that depends on the
location being right.

## What's actually real here

- **Gemini**, through Vertex AI, does the multimodal vision pass on
  satellite imagery, the evidence cross-referencing, verdict writing,
  claim splitting, and location extraction — every call uses Gemini's
  native structured-output mode, not a prompt begging for JSON and a
  regex cleaning up whatever came back.
- **Google ADK** composes the whole thing as a real
  `SequentialAgent`/`ParallelAgent` graph. The concurrency is real, too —
  Location Grounding and Claim Decomposition genuinely run at the same
  time, and all seven evidence agents genuinely fan out together the
  moment a location resolves.
- **A2A** carries every handoff between agents as a structured
  `a2a.types.Message`, not a dict I made up and called a protocol.
- **MCP** — a real `FastMCP` server (`mcp_servers/origin_tools.py`) hosts
  the data-fetching tools, and three of the evidence agents call into it
  as an actual subprocess, not a function call wearing an MCP costume.
- **Earth Engine** runs real NDVI queries against Sentinel-2 imagery.

None of the underlying data is fabricated or seeded: Global Forest Watch,
WDPA, GDACS, Nominatim, Carbonmark, NASA POWER, and Esri World Imagery (the
actual image Gemini looks at) are all live, real, and queried fresh per
investigation.

**Delivery** is FastAPI over Server-Sent Events, so you watch each agent
report back the moment it finishes instead of staring at a spinner.

## Getting started

### Prerequisites
- Python (developed and tested on 3.14)
- A [Gemini API key](https://aistudio.google.com/apikey) — if you hit a
  `limit: 0` quota wall on a plain AI Studio key, see
  `agents/gemini_config.py`. This routes through Vertex AI Express Mode
  instead, which has its own genuinely free quota pool.
- A [Global Forest Watch](https://www.globalforestwatch.org/) account and
  API key — `python3 scripts/gfw_create_key.py` will generate one for you
  (your password stays local, typed via `getpass`, never leaves your
  terminal).

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

`EARTH_ENGINE_PROJECT` is optional — Vegetation Trend just reports "no
signal" without it. To turn it on, register a Cloud project for Earth
Engine's free noncommercial Community tier
(console.cloud.google.com/earth-engine) and run `earthengine authenticate`
once.

### Run

```bash
uvicorn server.app:app --reload
```

Open `http://localhost:8000`. Investigations is where you submit a claim;
Layers walks through the actual stack in more depth; Saved reports is
everything you've investigated so far.

There's also a CLI if you just want one claim without the UI:

```bash
python3 -m orchestrator.pipeline "the palm oil expansion at -9.98,-63.0 in Rondonia, Brazil caused no deforestation"
```

## Deploying it

`render.yaml` is already set up for [Render](https://render.com)'s free
tier — no card required to sign up. To deploy:

1. Push this repo to your own GitHub account (fork it, or just push to a
   repo you own).
2. On Render, choose **New > Blueprint** and point it at that repo. It'll
   pick up `render.yaml` automatically.
3. Render will ask for `GEMINI_API_KEY` and `GFW_API_KEY` — paste the same
   values from your `.env`.
4. Deploy. First load after the service has been idle takes 30-60 seconds
   to wake back up — that's Render's free tier sleeping after 15 minutes
   of no traffic, not a bug.

Two things worth knowing about the free tier specifically: `EARTH_ENGINE_PROJECT`
is deliberately left unset in `render.yaml`, since Earth Engine's OAuth
credential is a local file `earthengine authenticate` writes to your own
machine, not something that travels with the repo — Vegetation Trend just
reports "no signal" in the deployed version, the same graceful skip it
does for anyone who hasn't run that command locally either. And the SQLite
claims log resets on every new deploy (no persistent disk on the free
tier), so Saved Reports only holds what's been investigated since the
last push, not a permanent history.

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
