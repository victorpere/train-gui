import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from communication import Communicator
from scenario import ScenarioRunner
from railway import Layout, DeviceType, MessageType, Message
from util import encode_message
from fake_serial import FakeSerial


def factory(port):
    fs = FakeSerial()
    factory.last = fs
    return fs

layout_data = {
    "name": "test layout",
    "description": "simple test loop",
    "tracks": [
        {
            "id": 1
        }
    ]
}

def test_scenario_runner_executes_steps():    
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    track = layout.components[DeviceType.TARGET_VOLTAGE.name][1]
    communicator.connect("/dev/fake")

    scenario = {
        "name": "demo",
        "description": "A simple demo scenario",
        "times": 1,
        "steps": [
            {
                "device_type": "TARGET_VOLTAGE",
                "device_id": 1,
                "action": "DEVICE_SET",
                "value": 45
            }
        ]
    }

    runner = ScenarioRunner(layout)
    ok, msg = runner.load_scenario(scenario)
    assert ok, f"Load scenario failed: {msg}"
    runner.run()

    assert runner.scenario.name == "demo"
    # scenario should reset the target voltage after completion
    assert track.target_voltage == 0
    assert runner.state.step is None


def test_scenario_runner_waits_for_actual_voltage():
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    track = layout.components[DeviceType.TARGET_VOLTAGE.name][1]
    communicator.connect("/dev/fake")

    scenario = {
        "name": "wait-demo",
        "description": "A scenario that waits for actual voltage",
        "times": 1,
        "steps": [
            {
                "device_type": "ACTUAL_VOLTAGE",
                "device_id": 1,
                "action": "DEVICE_WAIT",
                "value": 11
            }
        ],
    }

    runner = ScenarioRunner(layout)
    ok, msg = runner.load_scenario(scenario)
    assert ok, f"Load scenario failed: {msg}"

    def later():
        time.sleep(0.05)
        # Send a proper 3-byte encoded message with actual voltage = 11
        # message_type=1, device_type=0 (actual voltage), device_id=1, value=11
        message = {
                "message_type": 1,
                "device_type": 0,
                "device_id": 1,
                "value": 11
            }
        encoded_message = encode_message(message)
        factory.last.inject_bytes(encoded_message)

    import threading
    threading.Thread(target=later, daemon=True).start()
    runner.run()

    assert track.actual_voltage == 11


def test_invalid_scenario():
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    communicator.connect("/dev/fake")

    scenario = {
        "name": "invalid-demo",
        "description": "An invalid scenario missing action",
        "times": 1,
        "steps": [
            {
                "device_type": "TARGET_VOLTAGE",
                "value": 45
            }
        ]
    }

    runner = ScenarioRunner(layout)
    ok, _ = runner.load_scenario(scenario)

    assert not ok


def test_step_name():
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    communicator.connect("/dev/fake")

    scenario = {
            "name": "step-name",
            "description": "scenario to check step name",
            "times": 1,
            "steps": [
                {
                    "action": "DEVICE_SET",
                    "device_type": "TARGET_VOLTAGE",
                    "device_id": 0,
                    "value": 45
                }
            ]
        }

    runner = ScenarioRunner(layout)
    ok, _ = runner.load_scenario(scenario)

    assert ok

    step1 = runner.scenario.steps[0]
    assert step1.name == "DEVICE_SET:TARGET_VOLTAGE:0:45"


def test_device_adjust_adds_to_current_value():
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    communicator.connect("/dev/fake")

    runner = ScenarioRunner(layout)
    ok, msg = runner.load_scenario({
        "name": "adjust",
        "description": "adjust target voltage",
        "times": 1,
        "steps": [
            "DEVICE_SET:TARGET_VOLTAGE:1:100",
            "DEVICE_ADJUST:TARGET_VOLTAGE:1:-5",
        ],
    })
    assert ok, msg

    sets = []
    original_command = layout.command

    def recording_command(message):
        if message.message_type == MessageType.SET:
            sets.append(message.value)
        return original_command(message)

    layout.command = recording_command

    assert runner.run()
    assert sets == [100, 95]


def _run_condition(operator, value, voltage=100):
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    communicator.connect("/dev/fake")

    runner = ScenarioRunner(layout)
    ok, msg = runner.load_scenario({
        "name": "condition",
        "description": "conditional adjust",
        "times": 1,
        "steps": [
            f"DEVICE_SET:TARGET_VOLTAGE:1:{voltage}",
            {
                "action": "DEVICE_CONDITION",
                "device_type": "TARGET_VOLTAGE",
                "device_id": 1,
                "value": value,
                "operator": operator,
                "steps": ["DEVICE_ADJUST:TARGET_VOLTAGE:1:-5"],
            },
        ],
    })
    assert ok, msg

    sets = []
    original_command = layout.command

    def recording_command(message):
        if message.message_type == MessageType.SET:
            sets.append(message.value)
        return original_command(message)

    layout.command = recording_command
    assert runner.run()
    return sets


def test_device_condition_runs_steps_when_true():
    assert _run_condition("GT", 50) == [100, 95]
    assert _run_condition("GE", 100) == [100, 95]
    assert _run_condition("EQ", 100) == [100, 95]
    assert _run_condition("NE", 50) == [100, 95]
    assert _run_condition("LT", 150) == [100, 95]
    assert _run_condition("LE", 100) == [100, 95]


def test_device_condition_skips_steps_when_false():
    assert _run_condition("GT", 100) == [100]
    assert _run_condition("LT", 100) == [100]
    assert _run_condition("EQ", 50) == [100]


def test_device_condition_requires_valid_operator_and_steps():
    runner = ScenarioRunner(Layout(Communicator(serial_factory=factory, time_to_initialize=0)))
    step = {"action": "DEVICE_CONDITION", "device_type": "SPEED", "device_id": 1, "value": 1}
    ok, _ = runner.load_scenario({"name": "x", "description": "x", "times": 1,
                                  "steps": [{**step, "operator": "XX", "steps": ["TIME_WAIT:::1"]}]})
    assert not ok
    ok, _ = runner.load_scenario({"name": "x", "description": "x", "times": 1,
                                  "steps": [{**step, "operator": "GT"}]})
    assert not ok


def _loop_runner(loop_step):
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    layout.load(layout_data)
    communicator.connect("/dev/fake")
    runner = ScenarioRunner(layout)
    ok, msg = runner.load_scenario({"name": "loop", "description": "loop", "times": 1,
                                    "steps": ["DEVICE_SET:TARGET_VOLTAGE:1:100", loop_step]})
    return runner, ok, msg, layout


def test_loop_runs_nested_steps_times():
    runner, ok, msg, layout = _loop_runner({
        "action": "LOOP", "times": 3, "steps": ["DEVICE_ADJUST:TARGET_VOLTAGE:1:-5"]})
    assert ok, msg
    sets = []
    original_command = layout.command

    def recording_command(message):
        if message.message_type == MessageType.SET:
            sets.append(message.value)
        return original_command(message)

    layout.command = recording_command
    assert runner.run()
    assert sets == [100, 95, 90, 85]


def test_loop_ends_at_duration_even_during_blocking_step():
    runner, ok, msg, _ = _loop_runner({
        "action": "LOOP", "times": 100, "duration": 0.3, "steps": ["TIME_WAIT:::10000"]})
    assert ok, msg
    start = time.monotonic()
    assert runner.run()
    assert time.monotonic() - start < 2


def test_loop_requires_times_or_duration_and_steps():
    runner = ScenarioRunner(Layout(Communicator(serial_factory=factory, time_to_initialize=0)))
    for step in ({"action": "LOOP", "steps": ["TIME_WAIT:::1"]},
                 {"action": "LOOP", "times": 2},
                 {"action": "LOOP", "times": 0, "steps": ["TIME_WAIT:::1"]}):
        ok, _ = runner.load_scenario({"name": "x", "description": "x", "times": 1, "steps": [step]})
        assert not ok


def test_device_wait_catches_sensor_pulse_between_polls():
    communicator = Communicator(serial_factory=factory, time_to_initialize=0)
    layout = Layout(communicator)
    with open(os.path.join(os.path.dirname(__file__), "data/test_layout01.json")) as f:
        layout.load(json.load(f))
    communicator.connect("/dev/fake")
    sensor = layout.components[DeviceType.SENSOR.name][1]
    runner = ScenarioRunner(layout)
    ok, msg = runner.load_scenario({"name": "pulse", "description": "pulse", "times": 1,
                                    "steps": ["DEVICE_WAIT:SENSOR:1:1"]})
    assert ok, msg

    original_command = layout.command
    queries = []

    def pulsing_command(message):
        result = original_command(message)
        if message.message_type == MessageType.QUERY and message.device_type == DeviceType.SENSOR:
            queries.append(result)
            if len(queries) == 1:
                # the sensor turns on and off again before the next poll
                for value in (1, 0):
                    sensor.process_message(Message(message_type=MessageType.SET,
                                                   device_type=DeviceType.SENSOR, device_id=1, value=value))
        return result

    layout.command = pulsing_command
    start = time.monotonic()
    assert runner.run()
    assert not sensor.on
    assert time.monotonic() - start < 2
    assert sensor._watchers == []
