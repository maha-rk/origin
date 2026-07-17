"""Global Forest Watch Data API client.

Covers both the Land Analysis Agent (tree cover loss) and the
Ecology/Protected-Area Agent (WDPA protected areas) — both datasets are
queryable through the same GFW Data API with the same API key, so there's
no need for a separate Protected Planet/WDPA integration.

Auth: free signup at https://www.globalforestwatch.org/help/developers/guides/create-and-use-an-api-key/
(name + email, no billing). Requests are authenticated with an `x-api-key`
header.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from data_clients.geo_utils import buffer_polygon_geojson

BASE_URL = "https://data-api.globalforestwatch.org"

# Dataset identifiers, pinned to a specific version rather than "latest":
# GFW query endpoints 404/redirect unpredictably on the "latest" alias, and
# pinning means results don't silently shift if GFW ships a new version.
TREE_COVER_LOSS_DATASET = "umd_tree_cover_loss"
TREE_COVER_LOSS_VERSION = "v1.13"
WDPA_DATASET = "wdpa_protected_areas"
WDPA_VERSION = "v202512"


point_to_buffer_polygon = buffer_polygon_geojson


def query_dataset(
    api_key: str, dataset: str, version: str, sql: str, geometry: dict | None = None
) -> list[dict]:
    url = f"{BASE_URL}/dataset/{dataset}/{version}/query"
    body: dict = {"sql": sql}
    if geometry is not None:
        body["geometry"] = geometry
    resp = requests.post(
        url, json=body, headers={"x-api-key": api_key}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()["data"]


@dataclass
class TreeCoverLossYear:
    year: int
    loss_area_ha: float


def get_tree_cover_loss(
    api_key: str,
    lat: float,
    lon: float,
    radius_km: float = 1.0,
    min_density_pct: int = 30,
) -> list[TreeCoverLossYear]:
    """Annual tree cover loss (hectares) within radius_km of a point.

    min_density_pct filters to pixels that had at least this much canopy
    density in 2000 — the standard GFW convention for "was this forest to
    begin with" (30% is GFW's own default threshold).
    """
    geometry = point_to_buffer_polygon(lat, lon, radius_km)
    # Note: an "IS NOT NULL" clause here 422s with "Unsupported filter
    # operator: exists" on GFW's SQL backend, confirmed against the live API.
    sql = (
        "SELECT umd_tree_cover_loss__year AS year, SUM(area__ha) AS loss_area_ha "
        "FROM data "
        f"WHERE umd_tree_cover_density_2000__threshold >= {min_density_pct} "
        "GROUP BY umd_tree_cover_loss__year "
        "ORDER BY umd_tree_cover_loss__year"
    )
    rows = query_dataset(
        api_key, TREE_COVER_LOSS_DATASET, TREE_COVER_LOSS_VERSION, sql, geometry
    )
    return [
        TreeCoverLossYear(year=int(r["year"]), loss_area_ha=float(r["loss_area_ha"]))
        for r in rows
        if r.get("year") is not None
    ]


@dataclass
class ProtectedArea:
    name: str
    designation: str
    iucn_category: str
    status: str
    area_ha: float


def get_nearby_protected_areas(
    api_key: str, lat: float, lon: float, radius_km: float = 10.0
) -> list[ProtectedArea]:
    geometry = point_to_buffer_polygon(lat, lon, radius_km)
    sql = "SELECT name, name_eng, desig, iucn_cat, status, gis_area FROM data"
    rows = query_dataset(api_key, WDPA_DATASET, WDPA_VERSION, sql, geometry)
    return [
        ProtectedArea(
            name=r.get("name") or r.get("name_eng") or "Unnamed",
            designation=r.get("desig") or "",
            iucn_category=r.get("iucn_cat") or "",
            status=r.get("status") or "",
            area_ha=float(r.get("gis_area") or 0),
        )
        for r in rows
    ]


def main() -> None:
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("lat", type=float)
    parser.add_argument("lon", type=float)
    parser.add_argument("--radius-km", type=float, default=5.0)
    args = parser.parse_args()

    api_key = os.environ.get("GFW_API_KEY")
    if not api_key:
        raise SystemExit("GFW_API_KEY environment variable is not set.")

    loss = get_tree_cover_loss(api_key, args.lat, args.lon, radius_km=args.radius_km)
    areas = get_nearby_protected_areas(
        api_key, args.lat, args.lon, radius_km=args.radius_km
    )

    print(json.dumps(
        {
            "tree_cover_loss_by_year": [vars(y) for y in loss],
            "nearby_protected_areas": [vars(a) for a in areas],
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
