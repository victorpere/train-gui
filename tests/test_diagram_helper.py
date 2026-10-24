import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

import math

from diagram_helper import curve_geometry, curve_to_line_points, segment_line_points


@pytest.mark.parametrize("start, end, extent", [
    ([450, 50], [450, 250], -180),
    ([150, 250], [150, 50], -180),
    ([200, 50], [250, 60], -15),
    ([350, 10], [410, 70], 45),
    ([0, 0], [100, 40], 30),
])
def test_curve_points_run_from_start_to_end(start, end, extent):
    points = curve_to_line_points(start, end, extent)
    assert len(points) >= 6
    assert points[:2] == pytest.approx(start)
    assert points[-2:] == pytest.approx(end)


@pytest.mark.parametrize("extent", [15, 30, 45, 90, 180, -90])
def test_curve_has_a_constant_radius(extent):
    start, end = [100, 100], [180, 140]
    geometry = curve_geometry(start, end, extent)
    cx, cy = geometry["center"]
    points = curve_to_line_points(start, end, extent, step_degrees=5)
    for x, y in zip(points[0::2], points[1::2]):
        assert math.hypot(x - cx, y - cy) == pytest.approx(geometry["radius"])


def test_curve_direction_follows_the_extent_sign():
    # From (100,100) to (200,200): a clockwise (negative) arc bulges to the upper right, a counter-clockwise one to the lower left
    clockwise = curve_to_line_points([100, 100], [200, 200], -90)
    counter_clockwise = curve_to_line_points([100, 100], [200, 200], 90)
    middle = len(clockwise) // 4 * 2
    assert clockwise[middle:middle + 2] == pytest.approx([170.71, 129.29], abs=0.01)
    assert counter_clockwise[middle:middle + 2] == pytest.approx([129.29, 170.71], abs=0.01)


def test_half_circle_is_centred_on_the_chord():
    geometry = curve_geometry([450, 50], [450, 250], -180)
    assert geometry["center"] == pytest.approx((450, 150))
    assert geometry["radius"] == pytest.approx(100)


def test_curve_needs_distinct_ends_and_an_extent():
    with pytest.raises(ValueError):
        curve_geometry([1, 1], [1, 1], 90)
    with pytest.raises(ValueError):
        curve_geometry([1, 1], [5, 5], 0)


def test_segment_line_points_use_node_positions():
    positions = {1: (0, 0), 2: (10, 0)}
    assert segment_line_points({"from": 1, "to": 2, "shape": "straight"}, positions) == [0, 0, 10, 0]
    assert segment_line_points({"from": 1, "to": 2}, positions) == [0, 0, 10, 0]
    points = segment_line_points({"from": 1, "to": 2, "shape": "curve", "extent": 90}, positions)
    assert points[:2] == pytest.approx([0, 0]) and points[-2:] == pytest.approx([10, 0])
