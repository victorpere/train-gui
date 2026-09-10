import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scenario_runner import ScenarioRunner
from track_model import TrackModel
from fake_serial import FakeSerial


def factory(port):
    fs = FakeSerial()
    factory.last = fs
    return fs


def test_scenario_runner_executes_steps():
    model = TrackModel(serial_factory=factory)
    model.connect("/dev/fake")

    scenario = {
        "name": "demo",
        "times": 1,
        "steps": [
            {"step": "direction_set", "direction": 1},
            {"step": "voltage_target_set", "voltage": 45},
            {"step": "time_wait", "time": 5},
        ],
    }

    runner = ScenarioRunner(scenario, model=model)
    runner.run()

    assert runner.name == "demo"
    assert model.direction == 1
    assert model.target_voltage == 45
    assert runner.current_step is None


def test_scenario_runner_waits_for_actual_voltage():
    model = TrackModel(serial_factory=factory)
    model.connect("/dev/fake")

    scenario = {
        "name": "wait-demo",
        "times": 1,
        "steps": [
            {"step": "voltage_actual_wait", "voltage": 11},
        ],
    }

    runner = ScenarioRunner(scenario, model=model)

    def later():
        time.sleep(0.05)
        factory.last.inject_bytes(bytes([11]))

    import threading
    threading.Thread(target=later, daemon=True).start()
    runner.run()

    assert model.actual_voltage == 11
