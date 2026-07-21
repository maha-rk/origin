"""These aggregation helpers feed the Evidence Overview cards directly —
wrong numbers here means a wrong hectare/distance count on screen, not
just an internal bug."""

from orchestrator.pipeline import (
    _land_stats,
    _nearest_and_count,
    _unwrap_task_group_error,
)


def test_land_stats_empty_input():
    stats = _land_stats([])
    assert stats == {
        "years_with_data": 0,
        "total_loss_ha_last_5_years": 0.0,
        "most_recent_year": None,
    }


def test_land_stats_only_sums_last_five_years():
    # 6 years of data (2018-2023); only 2019-2023 (last 5) should be summed.
    loss_by_year = [
        {"year": 2018, "loss_area_ha": 100.0},
        {"year": 2019, "loss_area_ha": 10.0},
        {"year": 2020, "loss_area_ha": 20.0},
        {"year": 2021, "loss_area_ha": 30.0},
        {"year": 2022, "loss_area_ha": 40.0},
        {"year": 2023, "loss_area_ha": 50.0},
    ]
    stats = _land_stats(loss_by_year)
    assert stats["years_with_data"] == 6
    assert stats["most_recent_year"] == 2023
    assert stats["total_loss_ha_last_5_years"] == 150.0  # 10+20+30+40+50, not +100


def test_land_stats_handles_protobuf_float_years():
    # read_agent_message round-trips numbers through a protobuf Struct, so
    # "year" arrives as e.g. 2023.0, not the int 2023 GFW originally returned.
    loss_by_year = [{"year": 2023.0, "loss_area_ha": 5.5}]
    stats = _land_stats(loss_by_year)
    assert stats["most_recent_year"] == 2023
    assert isinstance(stats["most_recent_year"], int)


def test_nearest_and_count_empty():
    assert _nearest_and_count([]) == {"count": 0, "nearest_km": None}


def test_nearest_and_count_picks_minimum_distance():
    items = [{"distance_km": 12.5}, {"distance_km": 3.2}, {"distance_km": 8.0}]
    result = _nearest_and_count(items)
    assert result["count"] == 3
    assert result["nearest_km"] == 3.2


def test_nearest_and_count_ignores_missing_distance_but_still_counts():
    items = [{"distance_km": None}, {"distance_km": 4.0}, {}]
    result = _nearest_and_count(items)
    assert result["count"] == 3
    assert result["nearest_km"] == 4.0


def test_unwrap_plain_exception_returns_itself():
    err = ValueError("boom")
    assert _unwrap_task_group_error(err) is err


def test_unwrap_exception_group_surfaces_first_real_exception():
    inner = ValueError("the actual problem")
    group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])
    assert _unwrap_task_group_error(group) is inner


def test_unwrap_nested_exception_groups():
    root_cause = KeyError("missing key")
    inner_group = ExceptionGroup("inner", [root_cause])
    outer_group = ExceptionGroup("outer", [inner_group])
    assert _unwrap_task_group_error(outer_group) is root_cause
