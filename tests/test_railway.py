import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

import pytest

from communication import Communicator
from railway import Layout, DeviceType, Message, MessageType, Sensor, Block, Track
from util import encode_message
from fake_serial import FakeSerial


@pytest.fixture
def fake_factory():
    def factory(port):
        fs = FakeSerial()
        factory.last = fs
        return fs

    return factory


layout_data = {
    "name": "test layout",
    "description": "layout with one track, two blocks and one sensor",
    "tracks": [
        {
            "id": 1
        }
    ],
    "blocks": [
        {
            "id": 1,
            "occupied": False
        },
        {
            "id": 2,
            "occupied": True
        }
    ],
    "sensors": [
        {
            "id": 1,
            "track_id": 1,
            "block_f_id": 1,
            "block_r_id": 2
        }
    ]
}


def test_layout_invalid_command(fake_factory):
    communicator = Communicator(serial_factory=fake_factory)
    layout = Layout(communicator)
    layout.load(layout_data)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    invalid_message = Message(
        message_type = MessageType.SET,
        device_type = DeviceType.TARGET_VOLTAGE,
        device_id = 999,  # non-existent device
        value = 42
    )

    ok, msg = layout.command(invalid_message)
    assert not ok
    assert msg == "Device not found"


def test_track_write_and_read(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    set_target_voltage_message = Message(
        message_type = MessageType.SET,
        device_type = DeviceType.TARGET_VOLTAGE,
        device_id = 1,
        value = 42
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

    assert any(e for e in events if e[0] == "component" \
               and e[1].device_type == DeviceType.ACTUAL_VOLTAGE \
               and e[1].value == 13)

def test_sensor_read(fake_factory):
    events = []
    
    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
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

def test_block_occupied_update(fake_factory):
    events = []
    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    track: Track = layout.components[DeviceType.TARGET_VOLTAGE.name][1]
    sensor: Sensor = layout.components[DeviceType.SENSOR.name][1]
    block_f: Block = layout.components[DeviceType.BLOCK.name][1]
    blcok_r: Block = layout.components[DeviceType.BLOCK.name][2]

    # verify initial states
    assert track.actual_direction == 0
    assert not sensor.on
    assert not block_f.occupied
    assert blcok_r.occupied

    track_set_target_voltage_message: Message = Message(
        message_type = MessageType.SET,
        device_type = DeviceType.TARGET_VOLTAGE,
        device_id = 1,
        value = 12
    )

    # send the command to set the track's target voltage in the forward direction
    layout.command(track_set_target_voltage_message)
    time.sleep(0.05)

    # inject an incoming 3-byte message with actual voltage = 13
    # message_type=1, device_type=0 (actual voltage), device_id=1, value=13
    message = {
        "message_type": 1,
        "device_type": 0,
        "device_id": 1,
        "value": 12
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)
    
    assert track.actual_direction == 1

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

    # both blocks should now be occupied
    assert sensor.on
    assert block_f.occupied
    assert blcok_r.occupied

    # inject an incoming 3-byte message to turn sensor "OFF"
    message = {
        "message_type": 1,  # SET
        "device_type": 3,   # SENSOR
        "device_id": 1,
        "value": 0          # OFF
    }
    incoming_message = encode_message(message)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.1)

    # block_r should no longer be occupied
    assert not sensor.on
    assert block_f.occupied
    assert not blcok_r.occupied

def test_duplicate_sensor_events(fake_factory):
    events = []
    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
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
    assert len(list(filter(lambda e: e[0] == "component" and e[1].device_type == DeviceType.SENSOR, events))) == 1