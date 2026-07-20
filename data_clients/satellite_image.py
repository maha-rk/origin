"""Fetches a static satellite image crop for a coordinate — the same free,
no-key Esri World Imagery service already used for the map's tile layer,
just as a single exported PNG instead of a tile grid, so it can be handed
to Gemini as image bytes."""

from __future__ import annotations

import requests

from data_clients.geo_utils import destination_point
from data_clients.http_retry import request_with_retry

EXPORT_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"


def fetch_satellite_image(
    lat: float, lon: float, radius_km: float, size_px: int = 640
) -> bytes | None:
    """Returns PNG bytes for a square crop centered on (lat, lon), or None
    if the export service is unreachable — an optional evidence source
    failing shouldn't take the whole investigation down, same reasoning as
    GDACS's has_coverage handling in gdacs_client.py."""
    north_lat, _ = destination_point(lat, lon, radius_km, 0)
    south_lat, _ = destination_point(lat, lon, radius_km, 180)
    _, east_lon = destination_point(lat, lon, radius_km, 90)
    _, west_lon = destination_point(lat, lon, radius_km, 270)

    params = {
        "bbox": f"{west_lon},{south_lat},{east_lon},{north_lat}",
        "bboxSR": 4326,
        "size": f"{size_px},{size_px}",
        "imageSR": 4326,
        "format": "png",
        "f": "image",
    }
    try:
        resp = request_with_retry("GET", EXPORT_URL, params=params, timeout=15)
    except requests.exceptions.RequestException:
        return None
    if resp.status_code != 200 or not resp.content:
        return None
    return resp.content
