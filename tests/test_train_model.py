import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from train_model import TrainModel
from fake_serial import FakeSerial


@pytest.fixture
def fake_factory():
    def factory(port):
        fs = FakeSerial()
        factory.last = fs
        return fs

    return factory


def test_train_model_write_and_read(fake_factory):
    events = []

    def listener(name, value):
        events.append((name, value))

    model = TrainModel(serial_factory=fake_factory)
    model.add_listener(listener)

    ok, msg = model.connect("/dev/fake")
    assert ok, f"Connect failed: {msg}"

    ok, msg = model.set_voltage(42)
    assert ok, f"Set voltage failed: {msg}"

    # allow background thread to process
    time.sleep(0.05)

    written = getattr(fake_factory, "last").written
    assert written, "No write occurred"
    assert written[-1] == b"42\n"

    # inject an incoming byte and allow model to notify
    fake_factory.last.inject_bytes(bytes([13]))
    time.sleep(0.1)

    assert any(e for e in events if e[0] == "actual_voltage" and e[1] == 13)
