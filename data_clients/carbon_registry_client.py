"""Carbon credit registry cross-reference client — checks whether a claim
site sits near a real, registered carbon offset/credit project, via
Carbonmark's free public API (aggregates Verra/VCS, Gold Standard, Puro,
and other registries — each project carries real point coordinates, not
just a country-level location, so this supports genuine proximity
filtering, not just "is there a project somewhere in this country").

Free, no API key. Carbonmark's search is by country name rather than
lat/lon directly, so this first reverse-geocodes the claim coordinate to a
country via Nominatim (same 1 req/sec usage-policy pacing and User-Agent
as agents/location_grounding.py's forward geocoding), then paginates that
country's projects and filters to ones within radius_km, client-side,
using real haversine distance.
"""

from __future__ import annotations

import time

from agents.location_grounding import USER_AGENT
from data_clients.geo_utils import haversine_km
from data_clients.http_retry import request_with_retry

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
CARBONMARK_URL = "https://api.carbonmark.com/carbonProjects"
# Pagination cap per country — generous headroom over what's actually been
# observed (Brazil, one of the largest project counts, has 38).
MAX_PROJECTS_PER_COUNTRY = 200

_last_nominatim_call = 0.0


def _pace_nominatim() -> None:
    global _last_nominatim_call
    elapsed = time.monotonic() - _last_nominatim_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)


def _country_for(lat: float, lon: float) -> str | None:
    _pace_nominatim()
    global _last_nominatim_call
    try:
        resp = request_with_retry(
            "get",
            NOMINATIM_REVERSE_URL,
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": 3,
                "accept-language": "en",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
    finally:
        _last_nominatim_call = time.monotonic()
    if resp.status_code != 200:
        return None
    return resp.json().get("address", {}).get("country")


def find_nearby_carbon_projects(lat: float, lon: float, radius_km: float) -> list[dict]:
    """Real, registered carbon offset/credit projects within radius_km of
    (lat, lon) — an opportunistic evidence source, same reasoning as Water
    Risk's GDACS check: most claims won't have one nearby, and an empty
    result here is honest absence of a signal, not a failure to report."""
    try:
        country = _country_for(lat, lon)
        if not country:
            return []

        matches = []
        offset = 0
        while offset < MAX_PROJECTS_PER_COUNTRY:
            resp = request_with_retry(
                "get",
                CARBONMARK_URL,
                params={"country": country, "offset": offset},
                timeout=15,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            for project in items:
                coords = project.get("location", {}).get("geometry", {}).get("coordinates")
                if not coords or len(coords) != 2:
                    continue
                project_lon, project_lat = coords
                distance_km = haversine_km(lat, lon, project_lat, project_lon)
                if distance_km <= radius_km:
                    matches.append(
                        {
                            "name": project.get("name"),
                            "registry": project.get("registry"),
                            "methodologies": [
                                m.get("name")
                                for m in project.get("methodologies", [])
                                if m.get("name")
                            ],
                            "country": project.get("country"),
                            "distance_km": round(distance_km, 2),
                            "total_credits_retired": project.get("stats", {}).get(
                                "totalRetired", 0
                            ),
                            "url": project.get("url"),
                        }
                    )
            offset += len(items)
            if offset >= data.get("itemsCount", 0):
                break

        matches.sort(key=lambda m: m["distance_km"])
        return matches
    except Exception:
        return []
