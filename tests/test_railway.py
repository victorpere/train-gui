from fake_serial import FakeSerial
from util import encode_message, load_data_from_file
from railway import Layout, DeviceType, Message, MessageType, Sensor, Block, Track, SpeedTrap, Point, validate_layout
from communication import Communicator
import copy
import pytest
import os
import sys
import time

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../app")))


@pytest.fixture
def fake_factory():
    def factory(port):
        fs = FakeSerial()
        factory.last = fs
        return fs

    return factory


layout_data = load_data_from_file("tests/data/test_layout01.json")


def test_layout_invalid_command(fake_factory):
    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    invalid_message = Message(
        message_type=MessageType.SET,
        device_type=DeviceType.TARGET_VOLTAGE,
        device_id=999,  # non-existent device
        value=42
    )

    ok, msg = layout.command(invalid_message)
    assert not ok
    assert msg == "Device not found"


def test_track_write_and_read(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    set_target_voltage_message = Message(
        message_type=MessageType.SET,
        device_type=DeviceType.TARGET_VOLTAGE,
        device_id=1,
        value=42
    )

    ok, msg = layout.command(set_target_voltage_message)
    assert ok, f"Set voltage failed: {msg}"

    # allow background thread to process
    time.sleep(0.05)

    written = getattr(fake_factory, "last").written
    assert written, "No write occurred"

    # Verify the written data is a 3-byte encoded message
    # message_type=1, device_type=1 (target voltage), device_id=1, value=42
    message = {
        "message_type": 1,
        "device_type": 1,
        "device_id": 1,
        "value": 42
    }
    expected_message = encode_message(message)
    assert written[-1] == expected_message, f"Expected {expected_message.hex()}, got {written[-1].hex()}"

    # inject an incoming 3-byte message with actual voltage = 13
    # message_type=1, device_type=0 (actual voltage), device_id=1, value=13
    message = {
        "message_type": 1,
        "device_type": 0,
        "device_id": 1,
        "value": 13
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    assert any(e for e in events if e[0] == "component"
               and e[1].device_type == DeviceType.ACTUAL_VOLTAGE
               and e[1].value == 13)


def test_sensor_read(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    sensor: Sensor = layout.components[DeviceType.SENSOR.name][1]
    assert not sensor.on

    # inject an incoming 3-byte message to set sensor to "ON"
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 1          # ON
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    assert sensor.on

    # inject an incoming 3-byte message to set sensor to "OFF"
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 0          # ON
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    assert not sensor.on


def test_duplicate_sensor_events(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    sensor: Sensor = layout.components[DeviceType.SENSOR.name][1]

    # inject an incoming 3-byte message to turn sensor "ON"
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 1          # ON
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    assert sensor.on

    # inject the same message again
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    # sensor should still be ON and no duplicate events should be triggered
    assert sensor.on
    assert len(list(filter(
        lambda e: e[0] == "component" and e[1].device_type == DeviceType.SENSOR, events))) == 1


def test_speed_trap(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    speed_trap: SpeedTrap = layout.components[DeviceType.SPEED.name][1]

    assert speed_trap.last_speed == 0

    # inject an incoming 3-byte message to turn sensor "ON" then "OFF"
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 1          # ON
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.01)
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 0          # ON
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    assert speed_trap.last_speed == 0

    # inject an incoming 3-byte message to turn sensor "ON" then "OFF"
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 1          # ON
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.01)
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 0          # ON
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    assert speed_trap.last_speed > 0


def test_point(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    point: Point = layout.components[DeviceType.POINT_DIRECTION.name][1]

    # initial point direction
    assert point.direction == 0

    switch_point_message = Message(
        message_type=MessageType.SET,
        device_type=DeviceType.POINT_DIRECTION,
        device_id=1,
        value=1
    )

    ok, msg = layout.command(switch_point_message)
    assert ok, f"Point switching failed: {msg}"
    # point direction should be switched
    assert point.direction == 1

    # inject an incoming 3-byte message with actual voltage = 10
    message = {
        "message_type": 1,
        "device_type": 0,
        "device_id": 1,
        "value": 10
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    # try to switch point
    switch_point_message = Message(
        message_type=MessageType.SET,
        device_type=DeviceType.POINT_DIRECTION,
        device_id=1,
        value=0
    )

    # point direction should not have been switched
    ok, msg = layout.command(switch_point_message)
    assert not ok
    assert point.direction == 1

    # try to switch with skip check
    switch_point_skip_check_message = Message(
        message_type=MessageType.SET,
        device_type=DeviceType.POINT_DIRECTION_SKIP_CHECK,
        device_id=1,
        value=0
    )

    # point should have switched
    ok, msg = layout.command(switch_point_skip_check_message)
    assert ok
    assert point.direction == 0


def test_validate_layout_accepts_bundled_layouts():
    for path in ("tests/data/test_layout01.json", "data/layouts/layout01.json", "data/layouts/layout02.json"):
        assert validate_layout(load_data_from_file(path)) == [], path


def test_validate_layout_reports_problems(fake_factory):
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

    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    ok, msg = layout.load(bad)
    assert not ok
    assert "duplicate id 1" in msg


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


def test_electrified_segments_follow_points(fake_factory):
    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    ok, msg = layout.load(layout_data)
    assert ok, msg
    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, msg

    assert sorted(layout.electrified_segments()[1]) == [1, 2, 3]

    skip_check = Message(
        message_type=MessageType.SET,
        device_type=DeviceType.POINT_DIRECTION_SKIP_CHECK,
        device_id=1,
        value=1
    )
    ok, msg = layout.command(skip_check)
    assert ok, msg
    assert sorted(layout.electrified_segments()[1]) == [1, 4]


def test_insulated_joint_isolates_segments(fake_factory):
    jointed = copy.deepcopy(layout_data)
    jointed["insulated_joints"] = [{"node": 2, "segments": [2, 3]}]

    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    ok, msg = layout.load(jointed)
    assert ok, msg
    assert sorted(layout.electrified_segments()[1]) == [1, 2]

    bad = copy.deepcopy(layout_data)
    bad["insulated_joints"] = [{"node": 4, "segments": [2, 3]}]
    assert any("must both touch the node" in e for e in validate_layout(bad))


def test_point_switch_in_test_mode_without_connection(fake_factory):
    communicator = Communicator(serial_factory=fake_factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    point: Point = layout.components[DeviceType.POINT_DIRECTION.name][1]
    switch = Message(
        message_type=MessageType.SET,
        device_type=DeviceType.POINT_DIRECTION,
        device_id=1,
        value=1
    )

    ok, _ = layout.command(switch)
    assert not ok

    layout.test_mode = True
    ok, msg = layout.command(switch)
    assert ok, msg
    assert point.direction == 1


def test_blocks_are_derived_from_sensor_nodes(fake_factory):
    layout = Layout(Communicator(serial_factory=fake_factory, time_to_initialize=0))
    ok, msg = layout.load(load_data_from_file("data/layouts/layout01.json"))
    assert ok, msg

    blocks = layout.components[DeviceType.BLOCK.name]
    assert {b_id: b.segment_ids for b_id, b in blocks.items()} == {
        1: [1, 3, 4, 5, 6, 8, 9, 10, 11, 17],
        2: [2],
        12: [12],
        18: [18],
    }
    assert blocks[2].sensor_ids == [0, 3]
    assert blocks[12].sensor_ids == [1]
    assert blocks[12].occupied and not blocks[1].occupied
    assert layout.node_location(layout.components[DeviceType.SENSOR.name][1].node) == (340, 96)


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


def test_sensor_events_move_occupancy_between_blocks(fake_factory):
    layout = Layout(Communicator(serial_factory=fake_factory, time_to_initialize=0))
    layout.load(layout_data)
    blocks = layout.components[DeviceType.BLOCK.name]
    events = []
    layout.add_listener(lambda name, value: events.append(value) if name == "component" else None)

    def set_sensor(value):
        ok, msg = layout.command(Message(
            message_type=MessageType.SET, device_type=DeviceType.SENSOR, device_id=1, value=value))
        assert ok, msg

    # block 3 starts occupied, block 1 free
    set_sensor(1)
    assert blocks[1].occupied and blocks[3].occupied
    set_sensor(0)
    assert blocks[1].occupied and not blocks[3].occupied
    assert [(e.device_type, e.device_id, e.value) for e in events if e.device_type == DeviceType.BLOCK] == [
        (DeviceType.BLOCK, 1, 1), (DeviceType.BLOCK, 3, 0)]

    # both blocks occupied before the event: direction unknown, nothing is freed
    blocks[3].occupied = True
    set_sensor(1)
    set_sensor(0)
    assert blocks[1].occupied and blocks[3].occupied


def _block_setup(fake_factory):
    layout = Layout(Communicator(serial_factory=fake_factory, time_to_initialize=0))
    layout.load(layout_data)

    def set_actual_voltage(value):
        ok, msg = layout.command(Message(
            message_type=MessageType.SET, device_type=DeviceType.ACTUAL_VOLTAGE, device_id=1, value=value))
        assert ok, msg

    def set_sensor(value):
        ok, msg = layout.command(Message(
            message_type=MessageType.SET, device_type=DeviceType.SENSOR, device_id=1, value=value))
        assert ok, msg

    return layout.components[DeviceType.BLOCK.name], set_actual_voltage, set_sensor


def test_track_direction_resolves_which_block_is_left(fake_factory):
    blocks, set_actual_voltage, set_sensor = _block_setup(fake_factory)
    # sensor at node 2 joins segment 2 (block 1) and segment 3 (block 3)
    blocks[1].occupied = True
    blocks[3].occupied = True

    set_actual_voltage(10)  # along segments: from block 1 into block 3
    set_sensor(1)
    set_sensor(0)
    assert not blocks[1].occupied and blocks[3].occupied

    blocks[1].occupied = True
    set_actual_voltage(0)  # coasting to a stop keeps the direction
    set_sensor(1)
    set_sensor(0)
    assert not blocks[1].occupied and blocks[3].occupied

    blocks[1].occupied = True
    set_actual_voltage(-10)  # against segments: from block 3 into block 1
    set_sensor(1)
    set_sensor(0)
    assert blocks[1].occupied and not blocks[3].occupied
