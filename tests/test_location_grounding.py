"""The "stop and ask instead of guessing" rule (docs/brief.md's hard scope
boundary) lives entirely in resolve_with_confidence()'s granularity/
ambiguity checks — if this regresses, ORIGIN silently starts guessing
locations instead of refusing to, which is the one thing it's explicitly
not supposed to do."""

from agents.location_grounding import (
    RELATIONAL_PREFIX_RE,
    GeocodeCandidate,
    resolve_with_confidence,
    try_coordinate_shortcut,
)


def _candidate(place_rank, lat=12.97, lon=77.59, importance=0.5):
    return GeocodeCandidate(
        display_name="test place",
        lat=lat,
        lon=lon,
        importance=importance,
        place_rank=place_rank,
    )


def test_no_candidates_is_unresolved():
    assert resolve_with_confidence([]) is None


def test_single_site_level_candidate_resolves():
    # place_rank 26 (street-level) is finer than MIN_SITE_PLACE_RANK (20).
    result = resolve_with_confidence([_candidate(place_rank=26)])
    assert result is not None
    assert result.place_rank == 26


def test_single_city_level_candidate_is_rejected_as_too_coarse():
    # place_rank 16 (city-level) — a bare city match isn't a "site".
    assert resolve_with_confidence([_candidate(place_rank=16)]) is None


def test_single_candidate_with_no_place_rank_is_rejected():
    assert resolve_with_confidence([_candidate(place_rank=None)]) is None


def test_two_genuinely_different_places_is_ambiguous():
    # ~124km apart (Bengaluru vs Mysuru) — real, different places, not a
    # duplicate-record situation, so this must refuse rather than pick one.
    far = [
        _candidate(place_rank=26, lat=12.9716, lon=77.5946),
        _candidate(place_rank=26, lat=12.2958, lon=76.6394),
    ]
    assert resolve_with_confidence(far) is None


def test_duplicate_records_of_the_same_place_collapse_to_the_most_specific():
    # Two OSM records within the 1km duplicate-cluster radius (e.g. a
    # park's polygon centroid and a point inside it) should collapse to
    # whichever is more specific, not be treated as ambiguous.
    close = [
        _candidate(place_rank=16, lat=12.9716, lon=77.5946),
        _candidate(place_rank=26, lat=12.9718, lon=77.5948),
    ]
    result = resolve_with_confidence(close)
    assert result is not None
    assert result.place_rank == 26


def test_duplicate_records_that_are_all_too_coarse_still_rejected():
    close = [
        _candidate(place_rank=8, lat=12.9716, lon=77.5946),
        _candidate(place_rank=16, lat=12.9718, lon=77.5948),
    ]
    assert resolve_with_confidence(close) is None


def test_coordinate_shortcut_parses_plain_pair():
    assert try_coordinate_shortcut("12.9716,77.5946") == (12.9716, 77.5946)


def test_coordinate_shortcut_parses_negative_and_spaced():
    assert try_coordinate_shortcut(" -9.98 , -63.0 ") == (-9.98, -63.0)


def test_coordinate_shortcut_rejects_place_names():
    assert try_coordinate_shortcut("Bengaluru, India") is None
    assert try_coordinate_shortcut("Cubbon Park") is None


def test_relational_prefix_stripped():
    assert RELATIONAL_PREFIX_RE.sub("", "near Mandya") == "Mandya"
    assert RELATIONAL_PREFIX_RE.sub("", "close to Cubbon Park") == "Cubbon Park"


def test_relational_prefix_leaves_unprefixed_text_alone():
    assert RELATIONAL_PREFIX_RE.sub("", "Mandya") == "Mandya"
