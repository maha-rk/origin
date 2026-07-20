"""ORIGIN's evidence-gathering tools exposed as a real MCP server.

Thin wrappers around the already-tested clients in data_clients/ and
agents/location_grounding.py — this server doesn't reimplement any logic,
it just exposes the existing, verified functions over MCP so any
MCP-compatible client (this project's own orchestrator, Claude Desktop,
another agent framework) can discover and call them.

Run standalone for manual testing:
    GFW_API_KEY=... python3 -m mcp_servers.origin_tools

The orchestrator launches this as a subprocess over stdio — see
orchestrator/mcp_client.py.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from agents.location_grounding import geocode as _geocode
from agents.location_grounding import resolve_with_confidence
from data_clients import (
    carbon_registry_client,
    climate_trend_client,
    earth_engine_client,
    gdacs_client,
    gfw_client,
)

mcp = FastMCP("origin-evidence-tools")


@mcp.tool()
def geocode_location(query: str) -> dict:
    """Geocode a place-name or address query via Nominatim.

    Applies the same hard confidence rule as the rest of ORIGIN: resolves
    only if exactly one candidate (or a tight cluster of duplicate records
    for the same place) clears the site/neighbourhood granularity bar.
    Returns {"resolved": false, "candidates_considered": N} rather than
    guessing when the query is ambiguous or too coarse.
    """
    candidates = _geocode(query)
    match = resolve_with_confidence(candidates)
    if match is None:
        return {"resolved": False, "candidates_considered": len(candidates)}
    return {
        "resolved": True,
        "lat": match.lat,
        "lon": match.lon,
        "display_name": match.display_name,
        "candidates_considered": len(candidates),
    }


@mcp.tool()
def get_tree_cover_loss(lat: float, lon: float, radius_km: float = 5.0) -> list[dict]:
    """Annual tree cover loss (hectares) within radius_km of a point, via
    Global Forest Watch (30% canopy density threshold at year 2000)."""
    api_key = os.environ["GFW_API_KEY"]
    years = gfw_client.get_tree_cover_loss(api_key, lat, lon, radius_km)
    return [vars(y) for y in years]


@mcp.tool()
def get_protected_areas(lat: float, lon: float, radius_km: float = 10.0) -> list[dict]:
    """Protected areas within radius_km of a point, via the World Database
    on Protected Areas (WDPA)."""
    api_key = os.environ["GFW_API_KEY"]
    areas = gfw_client.get_nearby_protected_areas(api_key, lat, lon, radius_km)
    return [vars(a) for a in areas]


@mcp.tool()
def get_disaster_events(
    lat: float, lon: float, radius_km: float = 50.0, days: int = 30
) -> dict:
    """Recent disaster/flood events within radius_km of a point in the last
    `days` days, via GDACS. `has_coverage: false` means GDACS has no signal
    for this region at all — distinct from confirming zero events."""
    result = gdacs_client.get_events(lat, lon, radius_km, days)
    return {
        "has_coverage": result.has_coverage,
        "events": [vars(e) for e in result.events],
    }


@mcp.tool()
def get_vegetation_trend(
    lat: float, lon: float, radius_km: float, recent_year: int, baseline_year: int
) -> dict:
    """Mean NDVI vegetation index for recent_year vs baseline_year within
    radius_km of a point, via Google Earth Engine (Sentinel-2). An optional
    evidence source, not a hard pipeline dependency: returns
    {"available": false} if EARTH_ENGINE_PROJECT isn't set or Earth Engine
    is unreachable, rather than raising."""
    project = os.environ.get("EARTH_ENGINE_PROJECT")
    if not project:
        return {"available": False}
    result = earth_engine_client.get_ndvi_trend(
        project, lat, lon, radius_km, recent_year, baseline_year
    )
    return result or {"available": False}


@mcp.tool()
def get_nearby_carbon_projects(lat: float, lon: float, radius_km: float = 25.0) -> list[dict]:
    """Real, registered carbon offset/credit projects within radius_km of a
    point, via Verra/Gold Standard/Puro registries (aggregated through
    Carbonmark's public API). Opportunistic: an empty list is the normal,
    honest result for most locations, not a failure."""
    return carbon_registry_client.find_nearby_carbon_projects(lat, lon, radius_km)


@mcp.tool()
def get_climate_trend(
    lat: float,
    lon: float,
    recent_start_year: int,
    recent_end_year: int,
    baseline_start_year: int,
    baseline_end_year: int,
) -> dict:
    """Mean temperature and annual precipitation for a recent multi-year
    window vs an earlier baseline window, via NASA POWER (satellite/
    reanalysis-derived, globally covered — no ground station required).
    Returns {"available": false} if unreachable rather than raising."""
    result = climate_trend_client.get_climate_trend(
        lat,
        lon,
        recent_start_year,
        recent_end_year,
        baseline_start_year,
        baseline_end_year,
    )
    return result or {"available": False}


if __name__ == "__main__":
    mcp.run()
