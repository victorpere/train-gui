import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from diagram_helper import curve_to_line_points


@pytest.mark.parametrize("arc", [
    {"start_point": [450, 50], "end_point": [450, 250], "start_angle": 90, "extent": -180},
    {"start_point": [150, 250], "end_point": [150, 50], "start_angle": -90, "extent": -180},
    {"start_point": [200, 50], "end_point": [250, 60], "start_angle": 90, "extent": -15},
])
def test_curve_points_run_from_start_to_end(arc):
    points = curve_to_line_points(arc)
    assert len(points) >= 6
    assert points[:2] == pytest.approx(arc["start_point"])
    assert points[-2:] == pytest.approx(arc["end_point"])
