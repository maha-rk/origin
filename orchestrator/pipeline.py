"""Top-level ORIGIN pipeline: composes all agent steps via ADK's
SequentialAgent/ParallelAgent and executes them through an ADK Runner.

Land Analysis, Ecology, and Water Risk genuinely run concurrently once
Location Grounding resolves a location (ParallelAgent) — not sequential
function calls dressed up as agents.
"""

from __future__ import annotations

import uuid

from google.adk.agents import ParallelAgent, SequentialAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from orchestrator.a2a_messages import read_agent_message
from orchestrator.agents import (
    CrossReferenceStep,
    EcologyStep,
    LandAnalysisStep,
    LocationGroundingStep,
    VerdictSynthesisStep,
    WaterRiskStep,
)
from orchestrator.claims_log import log_investigation


def build_pipeline() -> SequentialAgent:
    return SequentialAgent(
        name="OriginPipeline",
        sub_agents=[
            LocationGroundingStep(name="LocationGrounding"),
            ParallelAgent(
                name="EvidenceGathering",
                sub_agents=[
                    LandAnalysisStep(name="LandAnalysis"),
                    EcologyStep(name="Ecology"),
                    WaterRiskStep(name="WaterRisk"),
                ],
            ),
            CrossReferenceStep(name="CrossReference"),
            VerdictSynthesisStep(name="VerdictSynthesis"),
        ],
    )


# Session state keys that carry an A2A Message from an agent handoff, in the
# order a live demo should narrate them — used to turn ADK's Event stream
# into human-readable progress instead of discarding it.
_MESSAGE_KEYS = [
    ("location_message", "Location Grounding"),
    ("land_message", "Land Analysis"),
    ("ecology_message", "Ecology"),
    ("water_message", "Water Risk"),
    ("cross_reference_message", "Cross-Reference"),
    ("verdict_message", "Verdict Synthesis"),
]


async def stream_investigation(claim_text: str, gemini_api_key: str, gfw_api_key: str):
    """Run one claim through the pipeline, yielding progress as each agent
    finishes — not just the final verdict. Land Analysis/Ecology/Water Risk
    genuinely fire concurrently (ParallelAgent), so their progress events can
    arrive interleaved, which is real signal, not an artifact to hide.

    Only the API key (a plain string) goes into session state, not a
    genai.Client — ADK's InMemorySessionService deep-copies initial state for
    isolation, and a Client holds a thread lock that can't be pickled. Each
    agent constructs its own lightweight client on demand instead.

    Yields dicts of shape {"type": "progress", "agent": ..., "summary": ...}
    while running, then exactly one {"type": "verdict", "data": ...} at the end.
    """
    pipeline = build_pipeline()
    runner = InMemoryRunner(agent=pipeline, app_name="origin")

    user_id = "origin-web"
    session_id = str(uuid.uuid4())
    context_id = str(uuid.uuid4())

    await runner.session_service.create_session(
        app_name="origin",
        user_id=user_id,
        session_id=session_id,
        state={
            "claim_text": claim_text,
            "gemini_api_key": gemini_api_key,
            "gfw_api_key": gfw_api_key,
            "context_id": context_id,
        },
    )

    seen_keys: set[str] = set()
    pipeline_error: Exception | None = None
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=genai_types.Content(
                role="user", parts=[genai_types.Part(text=claim_text)]
            ),
        ):
            delta = event.actions.state_delta if event.actions else {}
            for key, label in _MESSAGE_KEYS:
                if key in delta and key not in seen_keys:
                    seen_keys.add(key)
                    summary, data = read_agent_message(delta[key])
                    progress = {"type": "progress", "agent": label, "summary": summary}
                    # Carry map-relevant fields for the frontend's location panel —
                    # coordinates once resolved, then each agent's search radius so
                    # the map can show exactly what area was actually checked.
                    if key == "location_message" and data.get("resolved"):
                        progress["lat"] = data.get("lat")
                        progress["lon"] = data.get("lon")
                    elif key in ("land_message", "ecology_message", "water_message"):
                        progress["radius_km"] = data.get("radius_km")
                    yield progress
            if "pipeline_failed" in delta:
                yield {
                    "type": "progress",
                    "agent": "Pipeline",
                    "summary": f"Stopped: {delta.get('failure_reason', 'unresolved location')}",
                }
    except Exception as e:  # noqa: BLE001 - deliberately broad: any failure
        # anywhere in the agent graph (malformed LLM JSON, a data-source
        # outage, an MCP subprocess crash) must still produce a real verdict
        # event, not a dead SSE connection the frontend can only interpret
        # as "lost connection." A live demo hitting an unlucky transient
        # failure should degrade to an honest "investigation failed"
        # message, not a silent hang.
        pipeline_error = e

    if pipeline_error is not None:
        yield {
            "type": "progress",
            "agent": "Pipeline",
            "summary": f"Investigation failed: {pipeline_error}",
        }
        verdict = {
            "resolved": False,
            "reason": f"Investigation failed unexpectedly: {pipeline_error}",
        }
        yield {"type": "verdict", "data": verdict}
        return

    session = await runner.session_service.get_session(
        app_name="origin", user_id=user_id, session_id=session_id
    )
    verdict = session.state.get(
        "verdict", {"resolved": False, "reason": "Pipeline did not produce a verdict."}
    )

    location = None
    location_message = session.state.get("location_message")
    if location_message is not None:
        _, location = read_agent_message(location_message)

    try:
        log_investigation(claim_text, location, verdict)
    except Exception as e:  # noqa: BLE001 - logging must never block verdict delivery
        print(f"claims_log write failed (non-fatal): {e}")

    yield {"type": "verdict", "data": verdict}


async def run_investigation(claim_text: str, gemini_api_key: str, gfw_api_key: str) -> dict:
    """Non-streaming convenience wrapper — runs the pipeline and returns just
    the final verdict dict (used by the CLI)."""
    verdict = {}
    async for event in stream_investigation(claim_text, gemini_api_key, gfw_api_key):
        if event["type"] == "verdict":
            verdict = event["data"]
    return verdict


def main() -> None:
    import asyncio
    import json
    import os
    import sys

    gemini_key = os.environ.get("GEMINI_API_KEY")
    gfw_key = os.environ.get("GFW_API_KEY")
    if not gemini_key or not gfw_key:
        print("GEMINI_API_KEY and GFW_API_KEY must both be set.", file=sys.stderr)
        sys.exit(1)

    claim_text = " ".join(sys.argv[1:]).strip()
    if not claim_text:
        claim_text = input("Claim: ").strip()

    verdict = asyncio.run(run_investigation(claim_text, gemini_key, gfw_key))
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
