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


@pytest.mark.parametrize("path", ["tests/data/layout01.json", "tests/data/layout02.json"])
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
    assert doc.data["tracks"] == [{"id": track_id, "feeder_segment_id": 1}]
    assert "diagram" not in doc.data
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


def test_moving_a_node_moves_every_attached_segment_end():
    doc = build_y_layout()
    junction = doc.node_at((200, 100))
    doc.move_node(junction, (203, 118))

    assert doc.node_positions()[junction] == (200, 120)
    assert doc.data["nodes"][junction] == {"id": junction, "x": 200, "y": 120}
    assert doc.segments_at(junction) == [1, 2, 3]
    assert doc.problems() == []

    with pytest.raises(LayoutError):
        doc.move_node(junction, (300, 100))


def test_deleting_a_segment_drops_nodes_nothing_uses():
    doc = build_y_layout()
    doc.delete_segment(4)
    assert sorted(doc.node_positions()) == [0, 1, 2, 3]
    assert doc.problems() == []


def test_reversing_a_curve_keeps_its_shape():
    doc = LayoutDocument()
    segment_id = doc.add_segment((100, 100), (200, 200), "curve")
    positions = doc.node_positions()
    before = diagram_helper.segment_line_points(doc.data["segments"][0], positions)

    doc.reverse_segment(segment_id)

    assert doc.segment_nodes()[segment_id] == (1, 0)
    after = diagram_helper.segment_line_points(doc.data["segments"][0], positions)
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
    positions = doc.node_positions()
    before = diagram_helper.segment_line_points(doc.data["segments"][0], positions)

    doc.flip_curve(segment_id)
    flipped = diagram_helper.segment_line_points(doc.data["segments"][0], positions)

    assert flipped[:2] == pytest.approx(before[:2]) and flipped[-2:] == pytest.approx(before[-2:])
    mid = len(before) // 4 * 2
    assert before[mid:mid + 2] == pytest.approx([170.71, 129.29], abs=0.01)  # bulges to the upper right
    assert flipped[mid:mid + 2] == pytest.approx([129.29, 170.71], abs=0.01)  # bulges to the lower left
    assert doc.data["segments"][0]["extent"] == 90

    doc.flip_curve(segment_id)
    assert doc.data["segments"][0]["extent"] == -90


def test_a_curve_can_be_drawn_flipped_and_with_another_extent():
    doc = LayoutDocument()
    doc.add_segment((100, 100), (200, 200), "curve", flipped=True)
    assert doc.data["segments"][0]["extent"] == 90
    with pytest.raises(LayoutError):
        doc.flip_curve(99)
    with pytest.raises(LayoutError):
        doc.add_segment((300, 100), (400, 200), "curve", extent=60)
    assert len(doc.data["segments"]) == 1 and len(doc.data["nodes"]) == 2  # the rejected edit left nothing behind

    doc.add_segment((300, 100), (400, 200), "curve", extent=15)
    assert doc.data["segments"][1]["extent"] == -15


def test_curve_extent_is_limited_to_the_supported_arcs():
    doc = LayoutDocument()
    curve = doc.add_segment((100, 100), (200, 200), "curve")
    straight = doc.add_segment((200, 200), (300, 200))
    for extent in (15, -30, 45, -90, 180):
        doc.set_curve(curve, extent)
        assert doc.problems() == []
    with pytest.raises(LayoutError):
        doc.set_curve(curve, 60)
    with pytest.raises(LayoutError):
        doc.set_curve(straight, 90)
    assert doc.data["segments"][1] == {"id": straight, "from": 1, "to": 2, "shape": "straight"}


def test_splitting_a_straight_segment_puts_a_node_in_its_centre():
    doc = build_y_layout()
    junction = doc.node_at((200, 100))
    doc.add_joint(junction, 1, 2)
    track_id = doc.add_track()
    doc.set_feeder(track_id, 2)

    node = doc.split_segment(2)

    assert doc.node_positions()[node] == (250, 100)
    assert doc.segment_nodes()[2] == (junction, node)
    assert doc.segment_nodes()[5] == (node, doc.node_at((300, 100)))
    assert doc.data["tracks"][0]["feeder_segment_id"] == 2
    assert doc.problems() == []


def test_splitting_moves_joints_and_points_at_the_old_end_to_the_new_segment():
    doc = build_y_layout()
    end = doc.node_at((300, 100))
    doc.add_segment((300, 100), (400, 150))
    doc.set_point(end, 2, 4)
    doc.add_joint(end, 2, 5)

    doc.split_segment(2)

    assert doc.data["points"][0]["direction_segments"] == [6, 4]
    assert doc.joints_at(end) == [{"node": end, "segments": [6, 5]}]
    assert doc.problems() == []


def test_splitting_a_curve_puts_the_node_on_the_arc_and_halves_the_extent():
    doc = LayoutDocument()
    segment_id = doc.add_segment((100, 100), (200, 200), "curve")
    before = diagram_helper.segment_line_points(doc.data["segments"][0], doc.node_positions())
    mid = len(before) // 4 * 2

    node = doc.split_segment(segment_id)

    assert doc.node_positions()[node] == pytest.approx(before[mid:mid + 2], abs=0.1)
    assert [s["extent"] for s in doc.data["segments"]] == [-45, -45]
    assert doc.problems() == []

    small = LayoutDocument()
    small.add_segment((100, 100), (200, 200), "curve", extent=15)
    with pytest.raises(LayoutError):
        small.split_segment(1)
    with pytest.raises(LayoutError):
        small.split_segment(99)
