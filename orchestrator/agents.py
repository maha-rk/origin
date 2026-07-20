"""ADK agent wrappers for each ORIGIN pipeline step.

These are deterministic ADK agents (google.adk.agents.BaseAgent), not LLM
tool-calling loops — they wrap the already-tested functions from agents/ and
data_clients/, so orchestration is genuine ADK multi-agent composition
without reinventing working, verified logic inside a new framework. Every
handoff between steps goes through orchestrator/a2a_messages.py, not a bare
session-state value.

Land Analysis, Ecology, Water Risk, and now Location Grounding's geocoding
step all call their data sources through the real MCP server in
mcp_servers/origin_tools.py (see orchestrator/mcp_client.py) rather than
importing data_clients/ directly — genuine MCP protocol traffic, not a
decorative server nothing talks to. Location Grounding's Gemini extraction
and the relational-prefix/coordinate-shortcut normalization stay direct
(shared with agents/location_grounding.ground_claim via
extract_and_normalize_query/try_coordinate_shortcut, so this logic exists in
exactly one tested place) — only the actual geocode+confidence decision
routes through MCP's geocode_location tool.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from agents.gemini_config import make_client
from agents.claim_decomposition import decompose_claim
from agents.cross_reference import (
    CrossReferenceFinding,
    CrossReferenceResult,
    Gap,
    build_evidence_bundle,
    cross_reference_claim,
)
from agents.location_grounding import extract_and_normalize_query, try_coordinate_shortcut
from agents.verdict_synthesis import synthesize_verdict
from agents.visual_inspection import VisualInspectionResult, inspect_site
from data_clients.gdacs_client import DisasterEvent, WaterRiskQuery
from data_clients.gfw_client import ProtectedArea, TreeCoverLossYear
from orchestrator import mcp_client
from orchestrator.a2a_messages import make_agent_message, read_agent_message

LAND_RADIUS_KM = 5.0
ECOLOGY_RADIUS_KM = 10.0
WATER_RADIUS_KM = 50.0
WATER_LOOKBACK_DAYS = 30
VISUAL_RADIUS_KM = 5.0
VEGETATION_RADIUS_KM = 5.0
VEGETATION_BASELINE_YEARS = 5
CARBON_RADIUS_KM = 25.0
CLIMATE_WINDOW_YEARS = 3
CLIMATE_BASELINE_GAP_YEARS = 8


def _pipeline_failed(ctx: InvocationContext) -> bool:
    return bool(ctx.session.state.get("pipeline_failed"))


async def _ground_claim_via_mcp(claim_text: str, gemini_api_key: str, gfw_api_key: str) -> dict:
    """Same contract as agents.location_grounding.GroundingResult.__dict__,
    but the geocode+confidence decision is made by MCP's geocode_location
    tool instead of an in-process call."""
    client = make_client(gemini_api_key)
    query_text = await asyncio.to_thread(extract_and_normalize_query, client, claim_text)

    if query_text is None:
        return {
            "resolved": False,
            "reason": (
                "No location signal found in claim text. Please provide a "
                "specific location (coordinates, address, or place name)."
            ),
            "claim_text": claim_text,
            "location_query": None,
            "lat": None,
            "lon": None,
            "display_name": None,
            "candidates_considered": 0,
        }

    coords = try_coordinate_shortcut(query_text)
    if coords is not None:
        lat, lon = coords
        return {
            "resolved": True,
            "reason": "Claim gave explicit coordinates; geocoding skipped.",
            "claim_text": claim_text,
            "location_query": query_text,
            "lat": lat,
            "lon": lon,
            "display_name": query_text,
            "candidates_considered": 0,
        }

    geocode_result = await mcp_client.call_tool(
        "geocode_location", {"query": query_text}, gfw_api_key
    )
    considered = geocode_result.get("candidates_considered", 0)

    if not geocode_result.get("resolved"):
        reason = (
            f"{query_text!r} resolved to {considered} ambiguous or low-confidence "
            "candidates. Please provide a more specific location."
            if considered
            else f"Could not geocode {query_text!r} — no matches found. Please "
            "provide a more specific location."
        )
        return {
            "resolved": False,
            "reason": reason,
            "claim_text": claim_text,
            "location_query": query_text,
            "lat": None,
            "lon": None,
            "display_name": None,
            "candidates_considered": considered,
        }

    return {
        "resolved": True,
        "reason": "Resolved with reasonable confidence.",
        "claim_text": claim_text,
        "location_query": query_text,
        "lat": geocode_result["lat"],
        "lon": geocode_result["lon"],
        "display_name": geocode_result["display_name"],
        "candidates_considered": considered,
    }


class LocationGroundingStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        result = await _ground_claim_via_mcp(
            state["claim_text"], state["gemini_api_key"], state["gfw_api_key"]
        )

        if not result["resolved"]:
            msg = make_agent_message(
                self.name,
                f"Could not resolve a location: {result['reason']}",
                result,
                state["context_id"],
            )
            yield Event(
                author=self.name,
                actions=EventActions(
                    state_delta={
                        "location_message": msg,
                        "pipeline_failed": True,
                        "failure_reason": result["reason"],
                    }
                ),
            )
            return

        msg = make_agent_message(
            self.name,
            f"Resolved to {result['display_name']} ({result['lat']}, {result['lon']}).",
            result,
            state["context_id"],
        )
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"location_message": msg}),
        )


class ClaimDecompositionStep(BaseAgent):
    """Splits a compound claim into atomic sub-claims. Runs in parallel with
    LocationGroundingStep — it only needs the raw claim text, not a resolved
    location, so there's no reason to wait."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        result = await asyncio.to_thread(
            decompose_claim, make_client(state["gemini_api_key"]), state["claim_text"]
        )

        payload = {"sub_claims": result.sub_claims}
        summary = (
            "Single claim, no decomposition needed."
            if len(result.sub_claims) == 1
            else f"Split into {len(result.sub_claims)} sub-claims."
        )
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"decomposition_message": msg}),
        )


class LandAnalysisStep(BaseAgent):
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        loss = await mcp_client.call_tool(
            "get_tree_cover_loss",
            {"lat": location["lat"], "lon": location["lon"], "radius_km": LAND_RADIUS_KM},
            state["gfw_api_key"],
        )
        payload = {"loss_by_year": loss, "radius_km": LAND_RADIUS_KM}
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
        areas = await mcp_client.call_tool(
            "get_protected_areas",
            {"lat": location["lat"], "lon": location["lon"], "radius_km": ECOLOGY_RADIUS_KM},
            state["gfw_api_key"],
        )
        payload = {
            "protected_areas": areas,
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
        result = await mcp_client.call_tool(
            "get_disaster_events",
            {
                "lat": location["lat"],
                "lon": location["lon"],
                "radius_km": WATER_RADIUS_KM,
                "days": WATER_LOOKBACK_DAYS,
            },
            state["gfw_api_key"],
        )
        payload = {
            "has_coverage": result["has_coverage"],
            "events": result["events"],
            "radius_km": WATER_RADIUS_KM,
            "days": WATER_LOOKBACK_DAYS,
        }
        if not result["has_coverage"]:
            summary = "GDACS has no coverage for this location — no signal, not silence."
        elif result["events"]:
            summary = (
                f"Found {len(result['events'])} disaster event(s) in the last "
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


class VisualInspectionStep(BaseAgent):
    """Runs alongside Land/Ecology/Water Risk once location resolves — a
    genuinely independent evidence source, since it's Gemini's own reading
    of a real satellite image rather than another structured-data lookup."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        result = await asyncio.to_thread(
            inspect_site,
            make_client(state["gemini_api_key"]),
            location["lat"],
            location["lon"],
            VISUAL_RADIUS_KM,
        )
        payload = {
            "available": result.available,
            "observations": result.observations,
            "radius_km": result.radius_km,
        }
        summary = (
            result.observations
            if result.available
            else "Satellite imagery unavailable for this location — skipped."
        )
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name, actions=EventActions(state_delta={"visual_message": msg})
        )


class VegetationTrendStep(BaseAgent):
    """Runs alongside the other evidence-gathering agents — real,
    independently-computed NDVI vegetation-index data from Google Earth
    Engine, comparing a recent year against a baseline several years
    earlier. Optional: degrades to unavailable rather than failing the
    pipeline if Earth Engine isn't configured or unreachable, same
    reasoning as GDACS's has_coverage handling in WaterRiskStep."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        recent_year = datetime.now(timezone.utc).year - 1
        baseline_year = recent_year - VEGETATION_BASELINE_YEARS
        result = await mcp_client.call_tool(
            "get_vegetation_trend",
            {
                "lat": location["lat"],
                "lon": location["lon"],
                "radius_km": VEGETATION_RADIUS_KM,
                "recent_year": recent_year,
                "baseline_year": baseline_year,
            },
            state["gfw_api_key"],
        )
        payload = {**result, "radius_km": VEGETATION_RADIUS_KM}
        if result.get("available"):
            change = result["ndvi_change"]
            direction = "decreased" if change < 0 else "increased"
            summary = (
                f"NDVI vegetation index {direction} from {result['baseline_ndvi']} "
                f"({baseline_year}) to {result['recent_ndvi']} ({recent_year})."
            )
        else:
            summary = "Earth Engine vegetation data unavailable for this location."
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"vegetation_message": msg}),
        )


class CarbonProjectStep(BaseAgent):
    """Runs alongside the other evidence-gathering agents — checks whether
    a real, registered carbon offset/credit project (Verra/Gold
    Standard/Puro) exists near the claim site. Opportunistic like Water
    Risk's GDACS check: most claims won't have one nearby, and an empty
    result is the normal, honest outcome, not a failure."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        projects = await mcp_client.call_tool(
            "get_nearby_carbon_projects",
            {
                "lat": location["lat"],
                "lon": location["lon"],
                "radius_km": CARBON_RADIUS_KM,
            },
            state["gfw_api_key"],
        )
        payload = {"projects": projects, "radius_km": CARBON_RADIUS_KM}
        summary = (
            f"Found {len(projects)} registered carbon project(s) within "
            f"{CARBON_RADIUS_KM}km."
            if projects
            else f"No registered carbon projects found within {CARBON_RADIUS_KM}km."
        )
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"carbon_message": msg}),
        )


class ClimateTrendStep(BaseAgent):
    """Runs alongside the other evidence-gathering agents — real
    temperature/precipitation trend data from NASA POWER, comparing a
    recent multi-year window against a baseline a decade earlier. Globally
    covered (satellite/reanalysis-derived, not station-dependent) so it
    works at any coordinate, unlike GDACS or a ground-station-based air
    quality source would."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        if _pipeline_failed(ctx):
            return

        _, location = read_agent_message(state["location_message"])
        recent_end = datetime.now(timezone.utc).year - 1
        recent_start = recent_end - (CLIMATE_WINDOW_YEARS - 1)
        baseline_end = recent_start - CLIMATE_BASELINE_GAP_YEARS
        baseline_start = baseline_end - (CLIMATE_WINDOW_YEARS - 1)
        result = await mcp_client.call_tool(
            "get_climate_trend",
            {
                "lat": location["lat"],
                "lon": location["lon"],
                "recent_start_year": recent_start,
                "recent_end_year": recent_end,
                "baseline_start_year": baseline_start,
                "baseline_end_year": baseline_end,
            },
            state["gfw_api_key"],
        )
        payload = dict(result)
        if result.get("available"):
            summary = (
                f"Precipitation changed {result['precip_change_pct']:+.1f}% and "
                f"temperature changed {result['temp_change_c']:+.2f}°C from "
                f"{result['baseline_years']} to {result['recent_years']}."
            )
        else:
            summary = "NASA POWER climate trend data unavailable for this location."
        msg = make_agent_message(self.name, summary, payload, state["context_id"])
        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"climate_message": msg}),
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
        _, visual_data = read_agent_message(state["visual_message"])
        _, vegetation_data = read_agent_message(state["vegetation_message"])
        _, carbon_data = read_agent_message(state["carbon_message"])
        _, climate_data = read_agent_message(state["climate_message"])
        _, decomposition_data = read_agent_message(state["decomposition_message"])

        # Explicit int() cast: A2A messages round-trip through a protobuf
        # Value, whose JSON mapping has no integer type — every number comes
        # back as a float (confirmed: year=2001 becomes 2001.0), which would
        # otherwise leak into evidence bundles and Gemini-generated
        # citations as "in 2001.0" instead of "in 2001".
        loss_years = [
            TreeCoverLossYear(year=int(y["year"]), loss_area_ha=float(y["loss_area_ha"]))
            for y in land_data.get("loss_by_year", [])
        ]
        areas = [ProtectedArea(**a) for a in ecology_data.get("protected_areas", [])]
        water_query = WaterRiskQuery(
            has_coverage=water_data.get("has_coverage", False),
            events=[DisasterEvent(**e) for e in water_data.get("events", [])],
        )
        visual = VisualInspectionResult(
            available=visual_data.get("available", False),
            observations=visual_data.get("observations", ""),
            radius_km=visual_data.get("radius_km", VISUAL_RADIUS_KM),
        )
        sub_claims = decomposition_data.get("sub_claims") or [state["claim_text"]]

        bundle = build_evidence_bundle(
            state["claim_text"],
            sub_claims,
            location["display_name"],
            loss_years,
            areas,
            land_data.get("radius_km", LAND_RADIUS_KM),
            water_query,
            water_data.get("radius_km", WATER_RADIUS_KM),
            water_data.get("days", WATER_LOOKBACK_DAYS),
            visual,
            vegetation_data,
            carbon_data.get("projects", []),
            carbon_data.get("radius_km", CARBON_RADIUS_KM),
            climate_data,
        )
        cross_ref = await asyncio.to_thread(
            cross_reference_claim, make_client(state["gemini_api_key"]), bundle
        )

        payload = {
            "findings": [vars(f) for f in cross_ref.findings],
            "gaps": [vars(g) for g in cross_ref.gaps],
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
        _, decomposition_data = read_agent_message(state["decomposition_message"])

        findings = [
            CrossReferenceFinding(**f) for f in cross_ref_data.get("findings", [])
        ]
        gaps = [Gap(**g) for g in cross_ref_data.get("gaps", [])]
        cross_ref = CrossReferenceResult(findings=findings, gaps=gaps)
        sub_claims = decomposition_data.get("sub_claims") or [state["claim_text"]]

        verdict = await asyncio.to_thread(
            synthesize_verdict,
            make_client(state["gemini_api_key"]),
            state["claim_text"],
            sub_claims,
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
            "sub_claims": [
                {
                    "claim": sc.claim,
                    "confidence": vars(sc.confidence),
                    "supporting_evidence": sc.supporting_evidence,
                    "contradicting_evidence": sc.contradicting_evidence,
                    "gaps": sc.gaps,
                    "summary": sc.summary,
                }
                for sc in verdict.sub_claims
            ],
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
