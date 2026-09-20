import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from communication import Communicator
from scenario import ScenarioRunner
from railway import Layout, DeviceType
from util import encode_message
from fake_serial import FakeSerial


def factory(port):
    fs = FakeSerial()
    factory.last = fs
    return fs


def test_scenario_runner_executes_steps():
    layout_data = {
        "name": "test layout",
        "description": "simple test loop",
        "tracks": [
            {
                "id": 1
            }
        ]
    }
    
    communicator = Communicator(serial_factory=factory)
    layout = Layout(communicator)
    layout.load(layout_data)
    track = layout.components[DeviceType.TARGET_VOLTAGE.name][1]
    communicator.connect("/dev/fake")

    scenario = {
        "name": "demo",
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

    runner = ScenarioRunner(scenario, layout)
    runner.run()

    assert runner.scenario["name"] == "demo"
    assert track.target_voltage == 45
    assert runner.current_step is None


def test_scenario_runner_waits_for_actual_voltage():
    layout_data = {
                "name": "test layout",
                "description": "simple test loop",
                "tracks": [
                    {
                        "id": 1
                    }
                ]
            }
    
    communicator = Communicator(serial_factory=factory)
    layout = Layout(communicator)
    layout.load(layout_data)
    track = layout.components[DeviceType.TARGET_VOLTAGE.name][1]
    communicator.connect("/dev/fake")

    scenario = {
        "name": "wait-demo",
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

    runner = ScenarioRunner(scenario, layout)

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
