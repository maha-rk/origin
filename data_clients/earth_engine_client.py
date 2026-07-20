"""Google Earth Engine client — computes real vegetation-trend data (NDVI)
for a coordinate, as an independent quantitative evidence source alongside
GFW's tree-cover-loss data. Lazily initializes the Earth Engine SDK on
first use (a real network handshake, not free), guarded so it only
happens once per process even across repeated calls.

Requires one-time setup outside this codebase: a Cloud project registered
for Earth Engine's free noncommercial Community tier
(console.cloud.google.com/earth-engine) and a local OAuth credential from
`earthengine authenticate`. The project ID is read from the
EARTH_ENGINE_PROJECT env var by the MCP tool that calls this — if
initialization or the query fails for any reason, get_ndvi_trend returns
None rather than raising, so a missing/misconfigured optional evidence
source degrades the same way GDACS's has_coverage does, not by taking the
investigation down.
"""

from __future__ import annotations

import os

import certifi

# python.org's macOS Python build doesn't trust the system CA bundle for
# raw urllib/https calls (the SDK's OAuth token exchange hit this directly:
# SSLCertVerificationError: unable to get local issuer certificate) —
# certifi's bundle is the standard fix, set here so it applies whether this
# runs as the CLI, the FastAPI server, or the MCP subprocess.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

_initialized_project: str | None = None


def _ensure_initialized(project: str) -> bool:
    global _initialized_project
    if _initialized_project == project:
        return True
    try:
        import ee

        ee.Initialize(project=project)
        _initialized_project = project
        return True
    except Exception:
        return False


def get_ndvi_trend(
    project: str,
    lat: float,
    lon: float,
    radius_km: float,
    recent_year: int,
    baseline_year: int,
) -> dict | None:
    """Mean NDVI (Normalized Difference Vegetation Index, from Sentinel-2's
    red/near-infrared bands) over a buffer around (lat, lon), for
    recent_year vs baseline_year — a real, independently-computed
    quantitative signal of vegetation density change, not a pre-rendered
    tile or someone else's summary."""
    if not _ensure_initialized(project):
        return None

    import ee

    try:
        region = ee.Geometry.Point([lon, lat]).buffer(radius_km * 1000)

        def _mean_ndvi(year: int) -> float | None:
            img = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(region)
                .filterDate(f"{year}-01-01", f"{year}-12-31")
                .median()
            )
            ndvi = img.normalizedDifference(["B8", "B4"])
            value = ndvi.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region, scale=30, maxPixels=1e9
            ).get("nd")
            return value.getInfo()

        recent = _mean_ndvi(recent_year)
        baseline = _mean_ndvi(baseline_year)
        if recent is None or baseline is None:
            return None

        return {
            "available": True,
            "recent_year": recent_year,
            "baseline_year": baseline_year,
            "recent_ndvi": round(recent, 4),
            "baseline_ndvi": round(baseline, 4),
            "ndvi_change": round(recent - baseline, 4),
        }
    except Exception:
        return None
