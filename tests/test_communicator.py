import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

import pytest

from communication import Communicator
from util import encode_message
from fake_serial import FakeSerial


@pytest.fixture
def fake_factory():
    def factory(port):
        fs = FakeSerial()
        factory.last = fs
        return fs

    return factory


def test_connect_success(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
    communicator.add_listener(listener)

    ok, msg = communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"
    assert ("status", "connected") in events


def test_connect_failure():
    def failing_factory(port):
        raise RuntimeError("cannot open port")

    communicator = Communicator(serial_factory=failing_factory)

    ok, msg = communicator.connect("/dev/fake")
    assert not ok
    assert msg == "cannot open port"


def test_disconnect(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
    communicator.add_listener(listener)

    ok, msg = communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    communicator.disconnect()

    assert ("status", "disconnected") in events
    assert not fake_factory.last.is_open


def test_send_without_connection():
    communicator = Communicator(serial_factory=lambda port: FakeSerial())

    ok, msg = communicator.send({
        "message_type": 1,
        "device_type": 1,
        "device_id": 1,
        "value": 42
    })

    assert not ok
    assert msg == "Serial connection not established"


def test_send_encodes_and_writes(fake_factory):
    communicator = Communicator(serial_factory=fake_factory)

    ok, msg = communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    message = {
        "message_type": 1,
        "device_type": 1,
        "device_id": 1,
        "value": 42
    }
    ok, msg = communicator.send(message)
    assert ok, f"Send failed: {msg}"

    written = fake_factory.last.written
    assert written, "No write occurred"
    assert written[-1] == encode_message(message)


def test_receive_message_notifies_listener(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
    communicator.add_listener(listener)

    ok, msg = communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    message = {
        "message_type": 1,
        "device_type": 0,
        "device_id": 1,
        "value": 13
    }
    fake_factory.last.inject_bytes(encode_message(message))
    time.sleep(0.1)

    assert any(e for e in events if e[0] == "message" and e[1] == message)


def test_receive_resyncs_after_corrupt_bytes(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    communicator = Communicator(serial_factory=fake_factory)
    communicator.add_listener(listener)

    ok, msg = communicator.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    message = {
        "message_type": 1,
        "device_type": 0,
        "device_id": 1,
        "value": 13
    }
    encoded = encode_message(message)
    corrupted = bytes([encoded[0] ^ 0x01, encoded[1], encoded[2]])
    # send a corrupted message followed by a valid one; the reader should
    # discard the corrupt bytes and resync on the valid message
    fake_factory.last.inject_bytes(corrupted + encoded)
    time.sleep(0.1)

    assert not any(e for e in events if e[0] == "message" and e[1] != message)
    assert any(e for e in events if e[0] == "message" and e[1] == message)
