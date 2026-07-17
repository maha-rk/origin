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


async def run_investigation(claim_text: str, gemini_api_key: str, gfw_api_key: str) -> dict:
    """Run one claim through the full ORIGIN pipeline, returns the verdict dict.

    Only the API key (a plain string) goes into session state, not a
    genai.Client — ADK's InMemorySessionService deep-copies initial state for
    isolation, and a Client holds a thread lock that can't be pickled. Each
    agent constructs its own lightweight client on demand instead.
    """
    pipeline = build_pipeline()
    runner = InMemoryRunner(agent=pipeline, app_name="origin")

    user_id = "origin-cli"
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

    async for _event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=genai_types.Content(
            role="user", parts=[genai_types.Part(text=claim_text)]
        ),
    ):
        pass  # results accumulate in session state via state_delta; read below

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
    log_investigation(claim_text, location, verdict)

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
