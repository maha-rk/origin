"""GDACS (Global Disaster Alert and Coordination System) client.

Backs the Water Risk Agent. No API key required. GDACS is a near-real-time
alert system, not a long historical archive — the `eventsbyarea` endpoint
caps lookback at 30 days, confirmed against the live API. This matches the
agent's brief: opportunistic, lightweight recent-signal context, not a
baseline hydrology model.
"""

from __future__ import annotations

from dataclasses import dataclass

from data_clients.geo_utils import buffer_polygon_wkt
from data_clients.http_retry import request_with_retry

BASE_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/eventsbyarea"
MAX_DAYS = 30


@dataclass
class DisasterEvent:
    event_type: str
    name: str
    country: str
    alert_level: str
    from_date: str
    to_date: str
    source: str
    report_url: str


@dataclass
class WaterRiskQuery:
    """Result of a GDACS lookup, distinguishing two very different kinds of
    "nothing found": genuinely no events in the window (informative — GDACS
    does cover this area, and it's quiet) versus no coverage at all (GDACS
    has no signal here, full stop). Conflating these would misrepresent
    confidence, which is the one thing this agent's brief says never to do.
    """

    has_coverage: bool
    events: list[DisasterEvent]


def get_events(
    lat: float, lon: float, radius_km: float = 50.0, days: int = MAX_DAYS
) -> WaterRiskQuery:
    """Disaster events within radius_km of a point in the last `days` days.

    GDACS's eventsbyarea endpoint 404s for a large, confirmed swath of South
    Asia (Bengaluru, Chennai, Hyderabad, Kochi, Colombo all reproduce this;
    Mumbai/Delhi/Bangladesh do not) — a real gap in their spatial index, not
    a malformed request. Treated as "no coverage here" rather than an error,
    which matches this agent's brief: be honest when the data is thin.
    """
    days = min(days, MAX_DAYS)
    wkt = buffer_polygon_wkt(lat, lon, radius_km)
    resp = request_with_retry(
        "get", BASE_URL, params={"geometryArea": wkt, "days": days}, timeout=30
    )
    if resp.status_code == 404:
        return WaterRiskQuery(has_coverage=False, events=[])
    resp.raise_for_status()
    body = resp.json()

    events = []
    for feature in body.get("features", []):
        props = feature.get("properties", {})
        events.append(
            DisasterEvent(
                event_type=props.get("eventtype", ""),
                name=props.get("name", ""),
                country=props.get("country", ""),
                alert_level=props.get("alertlevel", ""),
                from_date=props.get("fromdate", ""),
                to_date=props.get("todate", ""),
                source=props.get("source", ""),
                report_url=props.get("url", {}).get("report", ""),
            )
        )
    return WaterRiskQuery(has_coverage=True, events=events)


def get_flood_events(
    lat: float, lon: float, radius_km: float = 50.0, days: int = MAX_DAYS
) -> WaterRiskQuery:
    result = get_events(lat, lon, radius_km, days)
    return WaterRiskQuery(
        has_coverage=result.has_coverage,
        events=[e for e in result.events if e.event_type == "FL"],
    )


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("--radius-km", type=float, default=50.0)
    parser.add_argument("--days", type=int, default=MAX_DAYS)
    args = parser.parse_args()

    result = get_events(args.lat, args.lon, args.radius_km, args.days)
    print(json.dumps(
        {"has_coverage": result.has_coverage, "events": [vars(e) for e in result.events]},
        indent=2,
    ))


if __name__ == "__main__":
    main()
