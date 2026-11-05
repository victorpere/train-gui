import copy
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from layout import validate_layout
from util import load_data_from_file

layout_data = load_data_from_file("tests/data/test_layout01.json")


def test_validate_layout_accepts_bundled_layouts():
    for path in ("tests/data/test_layout01.json", "tests/data/layout01.json", "tests/data/layout02.json"):
        assert validate_layout(load_data_from_file(path)) == [], path


def test_validate_layout_reports_problems():
    bad = copy.deepcopy(layout_data)
    bad["sensors"].append({"id": 1})
    bad["speed_traps"][0]["sensor_2_id"] = 99
    bad["speed_traps"][0]["track_id"] = 42
    bad["points"][0]["direction_segments"] = [2, 77]
    bad["tracks"][0]["feeder_segment_id"] = 55

    errors = validate_layout(bad)
    assert "sensors: duplicate id 1" in errors
    assert any("unknown sensor 99" in e for e in errors)
    assert any("unknown track 42" in e for e in errors)
    assert any("unknown segment 77" in e for e in errors)
    assert any("unknown feeder segment 55" in e for e in errors)


def test_validate_layout_rejects_inconsistent_graph():
    bad = copy.deepcopy(layout_data)
    bad["points"][0]["node"] = 3
    bad["tracks"][0]["segments"] = [[1]]

    errors = validate_layout(bad)
    assert any("must both touch node 3" in e for e in errors)
    assert any("nested segments are no longer supported" in e for e in errors)

    undrawn = copy.deepcopy(layout_data)
    undrawn["segments"].append({"id": 9, "from": 3, "to": 99})
    assert any("segment 9: unknown node 99" in e for e in validate_layout(undrawn))


def test_validate_layout_checks_nodes_and_segment_shapes():
    bad = copy.deepcopy(layout_data)
    bad["nodes"].append({"id": 5, "x": 30})
    bad["nodes"].append({"id": 1, "x": 0, "y": 0})
    bad["segments"][0]["extent"] = 90
    bad["segments"][1]["to"] = bad["segments"][1]["from"]
    bad["segments"][2]["shape"] = "spiral"
    bad["segments"][3]["extent"] = 60
    bad["diagram"] = {"segments": []}

    errors = validate_layout(bad)
    assert "nodes: duplicate id 1" in errors
    assert "node 5: x and y must be numbers" in errors
    assert any("node 1: same position as node 0" in e for e in errors)
    assert any("segment 1: extent only applies to curves" in e for e in errors)
    assert any("segment 2: from and to must be different nodes" in e for e in errors)
    assert any("segment 3: shape must be straight or curve" in e for e in errors)
    assert any("segment 4: curve extent must be one of" in e for e in errors)
    assert any(e.startswith("diagram: no longer supported") for e in errors)

    for extent in (15, -30, 45, -90, 180):
        good = copy.deepcopy(layout_data)
        good["segments"][3]["extent"] = extent
        assert validate_layout(good) == []


def test_validate_layout_rejects_misplaced_insulated_joint():
    bad = copy.deepcopy(layout_data)
    bad["insulated_joints"] = [{"node": 4, "segments": [2, 3]}]
    assert any("must both touch the node" in e for e in validate_layout(bad))


def test_validate_layout_sensor_and_block_problems():
    bad = copy.deepcopy(layout_data)
    bad["sensors"].append({"id": 2, "node": 99})
    bad["sensors"].append({"id": 3, "node": 2})
    bad["sensors"].append({"id": 4, "diagram": {"location": [0, 0]}})
    bad["blocks"].append({"id": 2})
    bad["nodes"][2].update({"x": 10, "y": 0})

    errors = validate_layout(bad)
    assert any("sensor 2: unknown node 99" in e for e in errors)
    assert any("sensor 3: node 2 already has a sensor" in e for e in errors)
    assert any("sensor 4: diagram location is no longer supported" in e for e in errors)
    assert any("block 2: no such block" in e for e in errors)
    assert any("node 2: same position as node 1" in e for e in errors)
