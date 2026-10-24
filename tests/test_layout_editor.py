import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

import diagram_helper
from layout_editor import LayoutDocument, LayoutError
from util import load_data_from_file


def build_y_layout() -> LayoutDocument:
    """Segments 1 (100,100)-(200,100), 2 (200,100)-(300,100), 3 (200,100)-(300,150), 4 (300,100)-(400,100)"""
    doc = LayoutDocument()
    doc.add_segment((100, 100), (200, 100))
    doc.add_segment((200, 100), (300, 100))
    doc.add_segment((200, 100), (300, 150))
    doc.add_segment((300, 100), (400, 100))
    return doc


@pytest.mark.parametrize("path", ["data/layouts/layout01.json", "data/layouts/layout02.json"])
def test_bundled_layouts_open_without_problems(path):
    doc = LayoutDocument(load_data_from_file(path))
    assert doc.problems() == []


def test_drawing_a_loop_reuses_nodes_and_validates():
    doc = LayoutDocument()
    doc.add_segment((100, 100), (300, 100))
    doc.add_segment((300, 100), (300, 200))
    doc.add_segment((300, 200), (100, 200))
    doc.add_segment((103, 198), (100, 100))  # ends snap to the existing nodes

    assert sorted(doc.node_positions()) == [0, 1, 2, 3]
    assert [(s["from"], s["to"]) for s in doc.data["segments"]] == [(0, 1), (1, 2), (2, 3), (3, 0)]

    track_id = doc.add_track()
    doc.set_feeder(track_id, 1)
    assert doc.drawings[0]["feeder"] is True
    assert doc.problems() == []


def test_zero_length_segment_is_rejected():
    doc = LayoutDocument()
    with pytest.raises(LayoutError):
        doc.add_segment((100, 100), (102, 101))


def test_sensors_split_blocks_and_occupancy_follows_them():
    doc = build_y_layout()
    node = doc.node_at((300, 100))
    assert doc.add_sensor(node) == 0
    assert doc.blocks() == {1: [1, 2, 3], 4: [4]}

    doc.set_block_occupied(4, True)
    summaries = {b["id"]: b for b in doc.block_summaries()}
    assert summaries[4]["occupied"] and summaries[4]["sensors"] == [0]
    assert doc.problems() == []

    doc.remove_sensor(node)
    assert doc.data["blocks"] == []  # block 4 no longer exists
    assert doc.problems() == []


def test_sensor_id_can_be_assigned_manually():
    doc = build_y_layout()
    first, second = doc.node_at((300, 100)), doc.node_at((200, 100))
    doc.add_sensor(first)
    doc.add_sensor(second)
    track_id = doc.add_track()
    doc.set_speed_trap(None, track_id, 0, 1, 50)

    doc.set_sensor_id(first, 7)
    assert doc.sensor_at(first) == 7
    assert doc.data["speed_traps"][0]["sensor_1_id"] == 7

    with pytest.raises(LayoutError):
        doc.set_sensor_id(first, 1)  # used by the other sensor
    with pytest.raises(LayoutError):
        doc.set_sensor_id(first, 16)
    with pytest.raises(LayoutError):
        doc.set_sensor_id(doc.node_at((400, 100)), 3)  # no sensor there


def test_point_needs_three_segments_and_is_dropped_when_it_breaks():
    doc = build_y_layout()
    junction = doc.node_at((200, 100))
    doc.set_point(junction, 2, 3, initial_direction=1)
    assert doc.data["points"] == [
        {"id": 0, "node": junction, "initial_direction": 1, "direction_segments": [2, 3]}]
    assert doc.problems() == []

    with pytest.raises(LayoutError):
        doc.set_point(doc.node_at((100, 100)), 1, 2)

    doc.delete_segment(3)
    assert doc.data["points"] == []
    assert doc.problems() == []


def test_insulated_joint_and_feeder_cleanup_on_delete():
    doc = build_y_layout()
    junction = doc.node_at((200, 100))
    doc.add_joint(junction, 1, 2)
    track_id = doc.add_track()
    doc.set_feeder(track_id, 4)
    assert doc.joints_at(junction) == [{"node": junction, "segments": [1, 2]}]

    doc.delete_segment(1)
    assert doc.joints_at(junction) == []

    doc.delete_segment(4)
    assert "feeder_segment_id" not in doc.data["tracks"][0]
    assert doc.problems() == []


def test_moving_a_node_moves_every_attached_end_point():
    doc = build_y_layout()
    junction = doc.node_at((200, 100))
    doc.move_node(junction, (203, 118))

    assert doc.node_positions()[junction] == (200, 120)
    assert doc.drawings[0]["end_point"] == [200, 120]
    assert doc.drawings[1]["start_point"] == [200, 120]
    assert doc.drawings[2]["start_point"] == [200, 120]
    assert doc.problems() == []

    with pytest.raises(LayoutError):
        doc.move_node(junction, (300, 100))


def test_reversing_a_curve_keeps_its_shape():
    doc = LayoutDocument()
    segment_id = doc.add_segment((100, 100), (200, 200), "curve")
    before = diagram_helper.curve_to_line_points(doc.drawings[0])

    doc.reverse_segment(segment_id)

    assert doc.segment_nodes()[segment_id] == (1, 0)
    after = diagram_helper.curve_to_line_points(doc.drawings[0])
    expected = [value for x, y in zip(before[0::2][::-1], before[1::2][::-1]) for value in (x, y)]
    assert after == pytest.approx(expected)


def test_device_ids_are_limited_to_the_protocol_range():
    doc = LayoutDocument()
    for _ in range(16):
        doc.add_track()
    with pytest.raises(LayoutError):
        doc.add_track()


def test_flipping_a_curve_bends_it_the_other_way_between_the_same_end_points():
    doc = LayoutDocument()
    segment_id = doc.add_segment((100, 100), (200, 200), "curve")
    before = diagram_helper.curve_to_line_points(doc.drawings[0])

    doc.flip_curve(segment_id)
    flipped = diagram_helper.curve_to_line_points(doc.drawings[0])

    assert flipped[:2] == pytest.approx(before[:2]) and flipped[-2:] == pytest.approx(before[-2:])
    mid = len(before) // 4 * 2
    assert before[mid:mid + 2] == pytest.approx([170.71, 129.29], abs=0.01)  # bulges to the upper right
    assert flipped[mid:mid + 2] == pytest.approx([129.29, 170.71], abs=0.01)  # bulges to the lower left
    assert doc.drawings[0]["start_angle"] == 180 and doc.drawings[0]["extent"] == 90

    doc.flip_curve(segment_id)
    assert (doc.drawings[0]["start_angle"], doc.drawings[0]["extent"]) == (90, -90)


def test_a_curve_can_be_drawn_flipped():
    doc = LayoutDocument()
    doc.add_segment((100, 100), (200, 200), "curve", flipped=True)
    assert (doc.drawings[0]["start_angle"], doc.drawings[0]["extent"]) == (180, 90)
    with pytest.raises(LayoutError):
        doc.flip_curve(99)
