import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from app.scenario_runner import ScenarioRunner
from app.track import Track
from app.util import encode_message
from tests.fake_serial import FakeSerial


def factory(port):
    fs = FakeSerial()
    factory.last = fs
    return fs


def test_scenario_runner_executes_steps():
    track = Track(serial_factory=factory)
    track.connect("/dev/fake")

    scenario = {
        "name": "demo",
        "times": 1,
        "steps": [
            {"step": "direction_set", "direction": 1},
            {"step": "voltage_target_set", "voltage": 45},
            {"step": "time_wait", "time": 5},
        ],
    }

    runner = ScenarioRunner(scenario, track=track)
    runner.run()

    assert runner.name == "demo"
    assert track.direction == 1
    assert track.target_voltage == 45
    assert runner.current_step is None


def test_scenario_runner_waits_for_actual_voltage():
    track = Track(serial_factory=factory)
    track.connect("/dev/fake")

    scenario = {
        "name": "wait-demo",
        "times": 1,
        "steps": [
            {"step": "voltage_actual_wait", "voltage": 11},
        ],
    }

    runner = ScenarioRunner(scenario, track=track)

    def later():
        time.sleep(0.05)
        # Send a proper 3-byte encoded message with actual voltage = 11
        # request_type=1, device_type=0 (actual voltage), device_id=1, value=11
        message = encode_message(request_type=1, device_type=0, device_id=1, value=11)
        factory.last.inject_bytes(message)

    import threading
    threading.Thread(target=later, daemon=True).start()
    runner.run()

    assert track.actual_voltage == 11
