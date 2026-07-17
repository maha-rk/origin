# ORIGIN — Project Brief

**Tagline:** Find the cause, not the symptom.

An autonomous multi-agent claim-investigation system. Given a real-world claim tied to
a physical location (e.g. "Company X reduced emissions by 40% at its plant near
Mandya, Karnataka" or "this proposed development site has no environmental risk"),
the system investigates the claim against real, verifiable evidence and produces a
traceable, confidence-scored verdict — not a retrieval/RAG answer.

**Context:** Built for the AI House × Google for Developers AI Agent Builder Series
2026 hackathon. Submission deadline **August 5, 2026, 11:59 PM IST**. Solo build,
~4 weeks. Judged on: Analysis (50%, genuine multi-agent reasoning depth), Votes (25%),
Feedback (25%).

**Required stack:** Gemini, ADK (Agent Development Kit), A2A (agent-to-agent
protocol), MCP, Vertex AI, Cloud Run, BigQuery.

**Demo domain:** environmental/sustainability claims (site development, land-use,
emissions), using real free data sources only — no fabricated or seeded data.

## Confirmed real data sources
- Global Forest Watch (GFW) — land-use change, deforestation over time
- WDPA — World Database on Protected Areas (protected/sensitive area proximity)
- GDACS — disaster/flood events, if relevant to a claim
- ReliefWeb API — historical incident reports, if relevant
- Nominatim (OpenStreetMap) — free geocoding, no key required

## Agent architecture

1. **Location Grounding Agent** (new, lightweight, runs first) — see scope boundary below.
2. **Land Analysis Agent** — land-use classification, vegetation cover via GFW.
3. **Ecology/Protected-Area Agent** — proximity to protected areas via WDPA.
4. **Water Risk Agent** (opportunistic — see below) — flood/hydrology context via GDACS.
5. **Evidence Cross-Reference Agent** — checks for contradictions between claim and
   gathered evidence. This is where most of the judged "reasoning depth" lives.
6. **Verdict Synthesis Agent** — produces final report: supporting evidence,
   contradicting evidence, confidence score, cited sources. Never asserts absolute
   truth — frames output as evidence for human review.

## Deliberate scope boundaries (hard rules, not gaps to close later)

### Claim grounding
ORIGIN investigates claims tied to a physical location. Resolving a vague corporate
claim ("Company X") to a specific facility is a distinct, solvable problem
(entity resolution / disambiguation) that is deliberately scoped **out** to keep
effort on the actual differentiator — the investigation itself.

**Location Grounding Agent contract:**
- Input: raw claim text.
- Uses Gemini to extract any location signal already present in the text
  (coordinates, address, place name, descriptive phrases like "near Mandya").
- Attempts geocoding via Nominatim.
- **Hard rule: if the geocode doesn't resolve with reasonable confidence, the
  system stops and asks the user for a specific location.** It never attempts
  entity resolution and never "tries harder" to guess. This is permanent, not a
  gap to close later.
- "Reasonable confidence" is operationalized (Nominatim has no true confidence
  score): accept only if exactly one candidate result is returned with
  `importance >= 0.35`, OR exactly one candidate at neighbourhood/site-level
  granularity or finer (not a bare country/state/city match). Zero results,
  multiple ambiguous results, or low-granularity-only matches → stop and ask.
- Once resolved: coordinates + confidence get passed downstream to Land Analysis,
  Ecology, and Water Risk agents.

### Water Risk Agent
Runs opportunistically. If GDACS/hydrology data yields real signal for the
location, it contributes to the verdict. If data is thin/unavailable, it
contributes nothing — Verdict Synthesis only surfaces agents that had actual
signal, never a visible "insufficient data" placeholder for an empty agent.

### BigQuery
Role: evidence/claims log. Every investigation (claim text, resolved location,
evidence gathered per agent, final verdict, confidence, timestamp) is written to
BigQuery. Real capability, not a checklist item — enables a "history of
investigated claims" view if time allows, and gives a concrete answer to "why
BigQuery."

## Key design principles
- Every output must be source-cited and explainable — no black-box scores.
- Genuine A2A message passing between agents, not just sequential function calls.
- MVP first: prove the core investigation loop works before building out full
  orchestration.
- No ML training/datasets required — reasoning + live API calls only.
