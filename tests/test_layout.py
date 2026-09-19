import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

import pytest

from communication import Communicator
from railway import Layout, DeviceType, Message, MessageType
from util import encode_message, decode_message
from fake_serial import FakeSerial


@pytest.fixture
def fake_factory():
    def factory(port):
        fs = FakeSerial()
        factory.last = fs
        return fs

    return factory


def test_track_write_and_read(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    layout_data = {
        "name": "test layout",
        "description": "simple test loop",
        "tracks": [
            {
                "id": 1
            }
        ]
    }

    communicator = Communicator(serial_factory=fake_factory)
    layout = Layout(communicator)
    layout.load(layout_data)
    layout.add_listener(listener)

    track = layout.components[DeviceType.TARGET_VOLTAGE.name][1]

    ok, msg = layout.communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    message: Message = {
        "message_type": MessageType.SET,
        "device_type": DeviceType.TARGET_VOLTAGE,
        "device_id": 1,
        "value": 42
    }

    ok, msg = layout.command(message)
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
    time.sleep(0.2)

    assert any(e for e in events if e[0] == "actual_voltage" and e[1] == 13)


def test_encode_decode_message():
    """Test that encode/decode roundtrip works correctly."""
    # Test positive value
    message = {
        "message_type": 1,
        "device_type": 1,
        "device_id": 1,
        "value": 42
    }
    msg = encode_message(message)
    decoded = decode_message(msg)
    assert decoded["message_type"] == 1
    assert decoded["device_type"] == 1
    assert decoded["device_id"] == 1
    assert decoded["value"] == 42
    
    # Test negative value
    message = {
            "message_type": 1,
            "device_type": 0,
            "device_id": 1,
            "value": -30
        }
    msg = encode_message(message)
    decoded = decode_message(msg)
    assert decoded["value"] == -30
    
    # Test CRC failure (corrupt one byte)
    message = {
            "message_type": 1,
            "device_type": 1,
            "device_id": 1,
            "value": 42
        }
    msg = encode_message(message)
    corrupted = bytes([msg[0] ^ 0x01, msg[1], msg[2]])  # flip a bit in byte 0
    decoded = decode_message(corrupted)
    assert decoded is None  # CRC should fail

