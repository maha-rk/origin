"""Location Grounding Agent.

First agent in the ORIGIN pipeline. Extracts a location signal from raw claim
text and geocodes it via Nominatim. Deliberately does NOT attempt entity
resolution (e.g. mapping a company name to one of its facilities) — see
docs/brief.md for the scope boundary this enforces. If the geocode does not
resolve with reasonable confidence, it stops and asks the user for a specific
location rather than guessing harder.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

from google import genai
from pydantic import BaseModel

from agents.gemini_config import MODEL, generate_structured, make_client
from data_clients.geo_utils import haversine_km
from data_clients.http_retry import request_with_retry

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim usage policy requires a descriptive User-Agent and max 1 req/sec.
USER_AGENT = "origin-claim-investigator/0.1 (contact: mahashrirk@gmail.com)"
# OSM place ranks: country ~4, state ~8, city ~16, suburb/neighbourhood ~20,
# street ~26, building ~30. Below this rank we treat a match as too coarse
# to be a "site" even if it's the only candidate. `importance` is NOT used
# as an accept condition: it measures a place's general prominence, not its
# granularity, so a well-known country/city scores high on it regardless of
# how localized the match is (e.g. a bare "India" query gets importance
# ~0.89) — using it as an OR-alternative to granularity let coarse matches
# through, confirmed by testing against the live API.
MIN_SITE_PLACE_RANK = 20
COORDINATE_RE = re.compile(r"^\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*$")
# Nominatim's search is exact-match-oriented and returns zero results for
# queries like "near Cubbon Park, Bengaluru" that would resolve fine as
# "Cubbon Park, Bengaluru" — confirmed against the live API. Gemini's
# extraction is inconsistent about including this prefix (varies run to
# run for similar claims), so it's normalized here rather than relying on
# prompt-only instruction to strip it reliably.
RELATIONAL_PREFIX_RE = re.compile(
    r"^(near|close to|adjacent to|next to|around|by)\s+", re.IGNORECASE
)
# Candidates within this radius of each other are treated as duplicate OSM
# records for the same physical place (e.g. a park's polygon and a point
# inside it), not as genuinely different places to disambiguate between.
DUPLICATE_CLUSTER_RADIUS_KM = 1.0

_last_nominatim_call = 0.0


@dataclass
class LocationSignal:
    found: bool
    query_text: str | None = None
    raw_claim: str = ""


class _LocationSignalSchema(BaseModel):
    has_location: bool
    location_text: str | None = None


@dataclass
class GeocodeCandidate:
    display_name: str
    lat: float
    lon: float
    importance: float
    place_rank: int | None
    bounding_box: list[float] = field(default_factory=list)


@dataclass
class GroundingResult:
    resolved: bool
    reason: str
    claim_text: str
    location_query: str | None = None
    lat: float | None = None
    lon: float | None = None
    display_name: str | None = None
    candidates_considered: int = 0


def extract_location_signal(client: genai.Client, claim_text: str) -> LocationSignal:
    prompt = f"""Extract the location signal from this claim, if any is present.

The claim may contain: coordinates, a street address, a place name, or a
descriptive phrase that names or narrows down a place (e.g. "near Mandya",
"the proposed site on the Bengaluru-Mysuru highway"). Do NOT infer a location
from a company or organization name alone — only extract text that names an
actual place.

If the claim contains BOTH explicit coordinates AND a place name (e.g. "at
26.9,70.9 near Jaisalmer"), extract ONLY the coordinates. Coordinates are
exact; a place name next to them is just orienting context and geocoding it
instead would throw away precision the claim already gave you.

location_text should be the location phrase as it appears (or a minimal
cleaned version of it), or null if has_location is false.

Claim: {claim_text!r}"""

    data = generate_structured(client, MODEL, prompt, _LocationSignalSchema)

    # Treat a self-contradictory response (has_location=True but no usable
    # location_text) the same as has_location=False rather than crashing —
    # an LLM occasionally returning null/empty text alongside true is a real
    # observed failure mode, and the safe fallback is exactly what
    # has_location=False already does: ask the user for a location instead
    # of guessing or raising.
    location_text = data.get("location_text")
    if not data.get("has_location") or not isinstance(location_text, str) or not location_text.strip():
        return LocationSignal(found=False, raw_claim=claim_text)
    return LocationSignal(found=True, query_text=location_text, raw_claim=claim_text)


def geocode(query_text: str) -> list[GeocodeCandidate]:
    global _last_nominatim_call
    elapsed = time.monotonic() - _last_nominatim_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    resp = request_with_retry(
        "get",
        NOMINATIM_URL,
        params={
            "q": query_text,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 0,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    _last_nominatim_call = time.monotonic()
    resp.raise_for_status()
    results = resp.json()

    candidates = []
    for r in results:
        candidates.append(
            GeocodeCandidate(
                display_name=r["display_name"],
                lat=float(r["lat"]),
                lon=float(r["lon"]),
                importance=float(r.get("importance", 0.0)),
                place_rank=r.get("place_rank"),
                bounding_box=[float(x) for x in r.get("boundingbox", [])],
            )
        )
    return candidates


def _all_within_radius(candidates: list[GeocodeCandidate], radius_km: float) -> bool:
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            if haversine_km(a.lat, a.lon, b.lat, b.lon) > radius_km:
                return False
    return True


def resolve_with_confidence(
    candidates: list[GeocodeCandidate],
) -> GeocodeCandidate | None:
    """Apply the hard confidence rule from docs/brief.md.

    A single candidate, or several candidates that all cluster within
    DUPLICATE_CLUSTER_RADIUS_KM of each other (duplicate OSM records for the
    same physical place, e.g. a park's polygon and a point inside it), are
    collapsed to the most specific (highest place_rank) one and checked
    against the granularity gate. Candidates spread across genuinely
    different places are rejected as ambiguous. Zero results, or a single
    low-granularity match (city/state/country level), are also rejected.
    """
    if not candidates:
        return None

    if len(candidates) == 1:
        candidate = candidates[0]
    elif _all_within_radius(candidates, DUPLICATE_CLUSTER_RADIUS_KM):
        candidate = max(
            candidates, key=lambda c: c.place_rank if c.place_rank is not None else -1
        )
    else:
        return None

    granularity_ok = (
        candidate.place_rank is not None
        and candidate.place_rank >= MIN_SITE_PLACE_RANK
    )
    return candidate if granularity_ok else None


def extract_and_normalize_query(client: genai.Client, claim_text: str) -> str | None:
    """Gemini extraction + relational-prefix stripping, shared by both the
    direct (sync, Nominatim-in-process) and MCP-routed geocoding paths so
    this logic exists in exactly one place. Returns None if no location
    signal was found in the claim."""
    signal = extract_location_signal(client, claim_text)
    if not signal.found:
        return None
    return RELATIONAL_PREFIX_RE.sub("", signal.query_text).strip()


def try_coordinate_shortcut(query_text: str) -> tuple[float, float] | None:
    """If query_text is already a bare 'lat,lon' pair, skip geocoding
    entirely. Shared by both geocoding paths for the same reason as
    extract_and_normalize_query above."""
    coord_match = COORDINATE_RE.match(query_text)
    if not coord_match:
        return None
    return float(coord_match.group(1)), float(coord_match.group(2))


def ground_claim(client: genai.Client, claim_text: str) -> GroundingResult:
    query_text = extract_and_normalize_query(client, claim_text)
    if query_text is None:
        return GroundingResult(
            resolved=False,
            reason=(
                "No location signal found in claim text. Please provide a "
                "specific location (coordinates, address, or place name)."
            ),
            claim_text=claim_text,
        )

    coords = try_coordinate_shortcut(query_text)
    if coords is not None:
        lat, lon = coords
        return GroundingResult(
            resolved=True,
            reason="Claim gave explicit coordinates; geocoding skipped.",
            claim_text=claim_text,
            location_query=query_text,
            lat=lat,
            lon=lon,
            display_name=query_text,
            candidates_considered=0,
        )

    candidates = geocode(query_text)
    match = resolve_with_confidence(candidates)

    if match is None:
        if not candidates:
            reason = (
                f"Could not geocode {query_text!r} — no matches found. "
                "Please provide a more specific location."
            )
        else:
            reason = (
                f"{query_text!r} resolved to {len(candidates)} ambiguous "
                "or low-confidence candidates. Please provide a more specific "
                "location."
            )
        return GroundingResult(
            resolved=False,
            reason=reason,
            claim_text=claim_text,
            location_query=query_text,
            candidates_considered=len(candidates),
        )

    return GroundingResult(
        resolved=True,
        reason="Resolved with reasonable confidence.",
        claim_text=claim_text,
        location_query=query_text,
        lat=match.lat,
        lon=match.lon,
        display_name=match.display_name,
        candidates_considered=len(candidates),
    )


def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    claim_text = " ".join(sys.argv[1:]).strip()
    if not claim_text:
        claim_text = input("Claim: ").strip()

    client = make_client(api_key)
    result = ground_claim(client, claim_text)

    print(json.dumps(result.__dict__, indent=2))


if __name__ == "__main__":
    main()
