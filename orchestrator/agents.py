"""ADK agent wrappers for each ORIGIN pipeline step.

These are deterministic ADK agents (google.adk.agents.BaseAgent), not LLM
tool-calling loops — they wrap the already-tested functions from agents/ and
data_clients/, so orchestration is genuine ADK multi-agent composition
without reinventing working, verified logic inside a new framework. Every
handoff between steps goes through orchestrator/a2a_messages.py, not a bare
session-state value.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

import data_clients.gdacs_client as gdacs
import data_clients.gfw_client as gfw
from agents.gemini_config import make_client
from agents.cross_reference import (
    CrossReferenceFinding,
    CrossReferenceResult,
    build_evidence_bundle,
    cross_reference_claim,
)
from agents.location_grounding import ground_claim
from agents.verdict_synthesis import synthesize_verdict
from data_clients.gdacs_client import DisasterEvent, WaterRiskQuery
from data_clients.gfw_client import ProtectedArea, TreeCoverLossYear
from orchestrator.a2a_messages import make_agent_message, read_agent_message

LAND_RADIUS_KM = 5.0
ECOLOGY_RADIUS_KM = 10.0
WATER_RADIUS_KM = 50.0
WATER_LOOKBACK_DAYS = 30


def _pipeline_failed(ctx: InvocationContext) -> bool:
    return bool(ctx.session.state.get("pipeline_failed"))


class LocationGroundingStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        result = await asyncio.to_thread(
            ground_claim, make_client(state["gemini_api_key"]), state["claim_text"]
        )

        if not result.resolved:
            msg = make_agent_message(
                self.name,
                f"Could not resolve a location: {result.reason}",
                result.__dict__,
                state["context_id"],
            )
            yield Event(
                author=self.name,
                actions=EventActions(
                    state_delta={
                        "location_message": msg,
                        "pipeline_failed": True,
                        "failure_reason": result.reason,
                    }
                ),
            )
            return

        msg = make_agent_message(
            self.name,
            f"Resolved to {result.display_name} ({result.lat}, {result.lon}).",
            result.__dict__,
            state["context_id"],
        )
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"location_message": msg}),
        )


class LandAnalysisStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        loss = await asyncio.to_thread(
            gfw.get_tree_cover_loss,
            state["gfw_api_key"],
            location["lat"],
            location["lon"],
            LAND_RADIUS_KM,
        )
        payload = {"loss_by_year": [vars(y) for y in loss], "radius_km": LAND_RADIUS_KM}
        summary = (
            f"Found {len(loss)} year(s) of tree cover loss data within "
            f"{LAND_RADIUS_KM}km."
            if loss
            else f"No tree cover loss detected within {LAND_RADIUS_KM}km."
        )
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name, actions=EventActions(state_delta={"land_message": msg})
        )


class EcologyStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        areas = await asyncio.to_thread(
            gfw.get_nearby_protected_areas,
            state["gfw_api_key"],
            location["lat"],
            location["lon"],
            ECOLOGY_RADIUS_KM,
        )
        payload = {
            "protected_areas": [vars(a) for a in areas],
            "radius_km": ECOLOGY_RADIUS_KM,
        }
        summary = (
            f"Found {len(areas)} protected area(s) within {ECOLOGY_RADIUS_KM}km."
            if areas
            else f"No protected areas found within {ECOLOGY_RADIUS_KM}km."
        )
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"ecology_message": msg}),
        )


class WaterRiskStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        result = await asyncio.to_thread(
            gdacs.get_events,
            location["lat"],
            location["lon"],
            WATER_RADIUS_KM,
            WATER_LOOKBACK_DAYS,
        )
        payload = {
            "has_coverage": result.has_coverage,
            "events": [vars(e) for e in result.events],
            "radius_km": WATER_RADIUS_KM,
            "days": WATER_LOOKBACK_DAYS,
        }
        if not result.has_coverage:
            summary = "GDACS has no coverage for this location — no signal, not silence."
        elif result.events:
            summary = (
                f"Found {len(result.events)} disaster event(s) in the last "
                f"{WATER_LOOKBACK_DAYS} days."
            )
        else:
            summary = (
                "GDACS covers this location; confirmed no events in the last "
                f"{WATER_LOOKBACK_DAYS} days."
            )
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name, actions=EventActions(state_delta={"water_message": msg})
        )


class CrossReferenceStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        _, land_data = read_agent_message(state["land_message"])
        _, ecology_data = read_agent_message(state["ecology_message"])
        _, water_data = read_agent_message(state["water_message"])

        loss_years = [TreeCoverLossYear(**y) for y in land_data.get("loss_by_year", [])]
        areas = [ProtectedArea(**a) for a in ecology_data.get("protected_areas", [])]
        water_query = WaterRiskQuery(
            has_coverage=water_data.get("has_coverage", False),
            events=[DisasterEvent(**e) for e in water_data.get("events", [])],
        )

        bundle = build_evidence_bundle(
            state["claim_text"],
            location["display_name"],
            loss_years,
            areas,
            land_data.get("radius_km", LAND_RADIUS_KM),
            water_query,
            water_data.get("radius_km", WATER_RADIUS_KM),
            water_data.get("days", WATER_LOOKBACK_DAYS),
        )
        cross_ref = await asyncio.to_thread(
            cross_reference_claim, make_client(state["gemini_api_key"]), bundle
        )

        payload = {
            "findings": [vars(f) for f in cross_ref.findings],
            "gaps": cross_ref.gaps,
        }
        summary = (
            f"{len(cross_ref.findings)} finding(s), "
            f"{len(cross_ref.gaps)} gap(s) identified."
        )
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"cross_reference_message": msg}),
        )


class VerdictSynthesisStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            yield Event(
                author=self.name,
                actions=EventActions(
                    state_delta={
                        "verdict": {
                            "resolved": False,
                            "reason": state.get("failure_reason"),
                        }
                    }
                ),
            )
            return

        _, location = read_agent_message(state["location_message"])
        _, cross_ref_data = read_agent_message(state["cross_reference_message"])

        findings = [
            CrossReferenceFinding(**f) for f in cross_ref_data.get("findings", [])
        ]
        cross_ref = CrossReferenceResult(
            findings=findings, gaps=cross_ref_data.get("gaps", [])
        )

        verdict = await asyncio.to_thread(
            synthesize_verdict,
            make_client(state["gemini_api_key"]),
            state["claim_text"],
            location["display_name"],
            cross_ref,
        )

        verdict_dict = {
            "resolved": True,
            "claim": verdict.claim,
            "location": verdict.location,
            "confidence": vars(verdict.confidence),
            "supporting_evidence": verdict.supporting_evidence,
            "contradicting_evidence": verdict.contradicting_evidence,
            "gaps": verdict.gaps,
            "summary": verdict.summary,
            "sources": verdict.sources,
        }
        trace_summary = (
            f"Verdict ready — {len(verdict.supporting_evidence)} supporting, "
            f"{len(verdict.contradicting_evidence)} contradicting, "
            f"{len(verdict.gaps)} gap(s). Full summary below."
        )
        msg = make_agent_message(
            self.name, trace_summary, verdict_dict, state["context_id"]
        )
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={"verdict_message": msg, "verdict": verdict_dict}
            ),
        )
