"""NASA POWER climate-trend client — real satellite/reanalysis-derived
temperature and precipitation trends at a point. Free, no API key, and
globally covered by design (it's model/satellite-derived, not dependent
on a ground station existing nearby) — unlike GDACS or OpenAQ, it works
at any coordinate ORIGIN might investigate, including remote forest
sites.

Compares multi-year windows rather than single years: a single year's
rainfall is dominated by ENSO (El Niño/La Niña) noise, which would make a
one-year-vs-one-year comparison meaningless. Averaging 3-year windows a
decade apart is closer to how climate trends are actually assessed, and
gives a real independent physical signal for deforestation claims —
reduced local rainfall is a documented effect of large-scale forest loss
(the Amazon "flying rivers" mechanism), not just another way of counting
the same tree-cover pixels GFW already measures.
"""

from __future__ import annotations

from data_clients.http_retry import request_with_retry

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
FILL_VALUE = -999.0


def _window_stats(
    daily_temp: dict, daily_precip: dict, start_year: int, end_year: int
) -> tuple[float | None, float | None]:
    temps = [
        v
        for k, v in daily_temp.items()
        if v != FILL_VALUE and start_year <= int(k[:4]) <= end_year
    ]
    mean_temp = sum(temps) / len(temps) if temps else None

    yearly_totals: dict[int, float] = {}
    for date_str, v in daily_precip.items():
        year = int(date_str[:4])
        if v == FILL_VALUE or not (start_year <= year <= end_year):
            continue
        yearly_totals[year] = yearly_totals.get(year, 0.0) + v
    mean_annual_precip = (
        sum(yearly_totals.values()) / len(yearly_totals) if yearly_totals else None
    )
    return mean_temp, mean_annual_precip


def get_climate_trend(
    lat: float,
    lon: float,
    recent_start_year: int,
    recent_end_year: int,
    baseline_start_year: int,
    baseline_end_year: int,
) -> dict | None:
    try:
        resp = request_with_retry(
            "get",
            POWER_URL,
            params={
                "parameters": "T2M,PRECTOTCORR",
                "community": "AG",
                "longitude": lon,
                "latitude": lat,
                "start": f"{baseline_start_year}0101",
                "end": f"{recent_end_year}1231",
                "format": "JSON",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return None
        params = resp.json()["properties"]["parameter"]
        temp, precip = params["T2M"], params["PRECTOTCORR"]

        recent_temp, recent_precip = _window_stats(
            temp, precip, recent_start_year, recent_end_year
        )
        baseline_temp, baseline_precip = _window_stats(
            temp, precip, baseline_start_year, baseline_end_year
        )
        if None in (recent_temp, recent_precip, baseline_temp, baseline_precip):
            return None

        return {
            "available": True,
            "recent_years": f"{recent_start_year}-{recent_end_year}",
            "baseline_years": f"{baseline_start_year}-{baseline_end_year}",
            "recent_mean_temp_c": round(recent_temp, 2),
            "baseline_mean_temp_c": round(baseline_temp, 2),
            "temp_change_c": round(recent_temp - baseline_temp, 2),
            "recent_mean_annual_precip_mm": round(recent_precip, 1),
            "baseline_mean_annual_precip_mm": round(baseline_precip, 1),
            "precip_change_mm": round(recent_precip - baseline_precip, 1),
            "precip_change_pct": round(
                (recent_precip - baseline_precip) / baseline_precip * 100, 1
            ),
        }
    except Exception:
        return None
