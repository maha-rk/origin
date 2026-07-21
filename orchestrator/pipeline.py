"""Top-level ORIGIN pipeline: composes all agent steps via ADK's
SequentialAgent/ParallelAgent and executes them through an ADK Runner.

Two genuine concurrency points, not sequential function calls dressed up as
agents: Claim Decomposition runs alongside Location Grounding (neither
depends on the other's output), and once a location resolves, Land
Analysis/Ecology/Water Risk fan out together.
"""

from __future__ import annotations

import uuid

from google.adk.agents import ParallelAgent, SequentialAgent
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from orchestrator.a2a_messages import read_agent_message
from orchestrator.agents import (
    CarbonProjectStep,
    ClaimDecompositionStep,
    ClimateTrendStep,
    CrossReferenceStep,
    EcologyStep,
    LandAnalysisStep,
    LocationGroundingStep,
    VegetationTrendStep,
    VerdictSynthesisStep,
    VisualInspectionStep,
    WaterRiskStep,
)
from orchestrator.claims_log import log_investigation


def build_pipeline() -> SequentialAgent:
    return SequentialAgent(
        name="OriginPipeline",
        sub_agents=[
            ParallelAgent(
                name="ClaimIntake",
                sub_agents=[
                    LocationGroundingStep(name="LocationGrounding"),
                    ClaimDecompositionStep(name="ClaimDecomposition"),
                ],
            ),
            ParallelAgent(
                name="EvidenceGathering",
                sub_agents=[
                    LandAnalysisStep(name="LandAnalysis"),
                    EcologyStep(name="Ecology"),
                    WaterRiskStep(name="WaterRisk"),
                    VisualInspectionStep(name="VisualInspection"),
                    VegetationTrendStep(name="VegetationTrend"),
                    CarbonProjectStep(name="CarbonProject"),
                    ClimateTrendStep(name="ClimateTrend"),
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
    ("decomposition_message", "Claim Decomposition"),
    ("land_message", "Land Analysis"),
    ("ecology_message", "Ecology"),
    ("water_message", "Water Risk"),
    ("visual_message", "Visual Inspection"),
    ("vegetation_message", "Vegetation Trend"),
    ("carbon_message", "Carbon Registry"),
    ("climate_message", "Climate Trend"),
    ("cross_reference_message", "Cross-Reference"),
    ("verdict_message", "Verdict Synthesis"),
]


def _int_or_none(value) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def _land_stats(loss_by_year: list[dict]) -> dict:
    """Same aggregation as cross_reference.py's `_summarize_land_evidence`,
    duplicated here rather than imported — that one builds prose for
    Gemini, this one builds a number for a UI card, and they'd only
    coincidentally match signatures today. loss_by_year's numbers arrive as
    floats (protobuf Struct round-trip in read_agent_message), hence the
    int() casts on year."""
    if not loss_by_year:
        return {"years_with_data": 0, "total_loss_ha_last_5_years": 0.0, "most_recent_year": None}
    years_sorted = sorted(loss_by_year, key=lambda y: y["year"])
    most_recent = int(years_sorted[-1]["year"])
    recent = [y for y in years_sorted if y["year"] >= most_recent - 4]
    return {
        "years_with_data": len(years_sorted),
        "total_loss_ha_last_5_years": round(sum(y["loss_area_ha"] for y in recent), 2),
        "most_recent_year": most_recent,
    }


def _nearest_and_count(items: list[dict]) -> dict:
    """Shared by Ecology (protected_areas) and Carbon Registry (projects) —
    both are lists of dicts with a distance_km field, and both cards need
    the same two numbers: how many were found, and how close the nearest
    one is."""
    distances = [i["distance_km"] for i in items if i.get("distance_km") is not None]
    return {"count": len(items), "nearest_km": min(distances) if distances else None}


def _unwrap_task_group_error(e: Exception) -> Exception:
    """Two pipeline stages now run agents concurrently (Location Grounding +
    Claim Decomposition, then the evidence-gathering trio) — when a shared
    root cause (e.g. a bad API key) fails multiple concurrent agents at
    once, asyncio.TaskGroup wraps them in an ExceptionGroup whose default
    string form is an unhelpful "unhandled errors in a TaskGroup (N
    sub-exception)". Surface the first real underlying exception instead.
    """
    exceptions = getattr(e, "exceptions", None)
    if exceptions:
        return _unwrap_task_group_error(exceptions[0])
    return e


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
                    # the map can show exactly what area was actually checked. Also
                    # carry a small stats dict per evidence agent — the Evidence
                    # Overview cards need real numbers (loss hectares, NDVI change,
                    # etc), not just the prose summary already in `summary`.
                    if key == "location_message" and data.get("resolved"):
                        progress["lat"] = data.get("lat")
                        progress["lon"] = data.get("lon")
                        progress["display_name"] = data.get("display_name")
                    elif key == "land_message":
                        progress["radius_km"] = data.get("radius_km")
                        progress["land_stats"] = _land_stats(data.get("loss_by_year") or [])
                    elif key == "ecology_message":
                        progress["radius_km"] = data.get("radius_km")
                        progress["ecology_stats"] = _nearest_and_count(
                            data.get("protected_areas") or []
                        )
                    elif key == "water_message":
                        progress["radius_km"] = data.get("radius_km")
                        progress["water_stats"] = {
                            "has_coverage": data.get("has_coverage"),
                            "event_count": len(data.get("events") or []),
                        }
                    elif key == "vegetation_message":
                        progress["radius_km"] = data.get("radius_km")
                        progress["vegetation_stats"] = {
                            "available": data.get("available"),
                            "ndvi_change": data.get("ndvi_change"),
                            "recent_year": _int_or_none(data.get("recent_year")),
                            "baseline_year": _int_or_none(data.get("baseline_year")),
                        }
                    elif key == "carbon_message":
                        progress["radius_km"] = data.get("radius_km")
                        progress["carbon_stats"] = _nearest_and_count(
                            data.get("projects") or []
                        )
                    elif key == "visual_message":
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
        pipeline_error = _unwrap_task_group_error(e)

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
        row = log_investigation(claim_text, location, verdict)
        verdict = {**verdict, "investigation_id": row["investigation_id"]}
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
