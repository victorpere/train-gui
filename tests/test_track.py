import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

import pytest

from app.track import Track
from app.util import encode_message, decode_message
from tests.fake_serial import FakeSerial


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

    track = Track(serial_factory=fake_factory)
    track.add_listener(listener)

    ok, msg = track.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    ok, msg = track.set_voltage(42)
    assert ok, f"Set voltage failed: {msg}"

    # allow background thread to process
    time.sleep(0.05)

    written = getattr(fake_factory, "last").written
    assert written, "No write occurred"
    
    # Verify the written data is a 3-byte encoded message
    # request_type=1, device_type=1 (target voltage), device_id=1, value=42
    expected_message = encode_message(request_type=1, device_type=1, device_id=1, value=42)
    assert written[-1] == expected_message, f"Expected {expected_message.hex()}, got {written[-1].hex()}"

    # inject an incoming 3-byte message with actual voltage = 13
    # request_type=1, device_type=0 (actual voltage), device_id=1, value=13
    incoming_message = encode_message(request_type=1, device_type=0, device_id=1, value=13)
    fake_factory.last.inject_bytes(incoming_message)
    time.sleep(0.2)

    assert any(e for e in events if e[0] == "actual_voltage" and e[1] == 13)


def test_encode_decode_message():
    """Test that encode/decode roundtrip works correctly."""
    # Test positive value
    msg = encode_message(request_type=1, device_type=1, device_id=1, value=42)
    decoded = decode_message(msg)
    assert decoded["request_type"] == 1
    assert decoded["device_type"] == 1
    assert decoded["device_id"] == 1
    assert decoded["value"] == 42
    
    # Test negative value
    msg = encode_message(request_type=1, device_type=0, device_id=1, value=-30)
    decoded = decode_message(msg)
    assert decoded["value"] == -30
    
    # Test CRC failure (corrupt one byte)
    msg = encode_message(request_type=1, device_type=1, device_id=1, value=42)
    corrupted = bytes([msg[0] ^ 0x01, msg[1], msg[2]])  # flip a bit in byte 0
    decoded = decode_message(corrupted)
    assert decoded is None  # CRC should fail

