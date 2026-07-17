"""Shared geo helpers for data clients that need to buffer a point into an
area for spatial queries (GFW wants GeoJSON, GDACS wants WKT)."""

from __future__ import annotations

from math import asin, atan2, cos, degrees, radians, sin


def destination_point(
    lat: float, lon: float, distance_km: float, bearing_deg: float
) -> tuple[float, float]:
    r = 6371.0
    lat1, lon1, brng = radians(lat), radians(lon), radians(bearing_deg)
    d = distance_km / r
    lat2 = asin(sin(lat1) * cos(d) + cos(lat1) * sin(d) * cos(brng))
    lon2 = lon1 + atan2(
        sin(brng) * sin(d) * cos(lat1), cos(d) - sin(lat1) * sin(lat2)
    )
    return degrees(lat2), degrees(lon2)


def buffer_polygon_coords(
    lat: float, lon: float, radius_km: float, num_vertices: int = 32
) -> list[list[float]]:
    """Closed ring of [lon, lat] pairs approximating a circle around a point."""
    coords = []
    for i in range(num_vertices):
        bearing = 360.0 * i / num_vertices
        plat, plon = destination_point(lat, lon, radius_km, bearing)
        coords.append([plon, plat])
    coords.append(coords[0])
    return coords


def buffer_polygon_geojson(
    lat: float, lon: float, radius_km: float, num_vertices: int = 32
) -> dict:
    coords = buffer_polygon_coords(lat, lon, radius_km, num_vertices)
    return {"type": "Polygon", "coordinates": [coords]}


def buffer_polygon_wkt(
    lat: float, lon: float, radius_km: float, num_vertices: int = 32
) -> str:
    coords = buffer_polygon_coords(lat, lon, radius_km, num_vertices)
    pairs = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return f"POLYGON(({pairs}))"
