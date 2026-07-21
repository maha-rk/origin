from data_clients.geo_utils import haversine_km


def test_same_point_is_zero_distance():
    assert haversine_km(12.9716, 77.5946, 12.9716, 77.5946) == 0.0


def test_known_distance_bengaluru_to_mysuru():
    # Real-world reference distance is ~124km as the crow flies.
    km = haversine_km(12.9716, 77.5946, 12.2958, 76.6394)
    assert 120 < km < 130


def test_known_distance_is_symmetric():
    a_to_b = haversine_km(12.9716, 77.5946, 12.2958, 76.6394)
    b_to_a = haversine_km(12.2958, 76.6394, 12.9716, 77.5946)
    assert a_to_b == b_to_a
