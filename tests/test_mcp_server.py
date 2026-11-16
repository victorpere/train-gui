import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from fake_serial import FakeSerial
from util import load_data_from_file
from railway import Layout, DeviceType
from communication import Communicator
from scenario import ScenarioRunner
from mcp_server import LayoutService, CONTROL_TOOLS, READ_ONLY_TOOLS, build_server

LAYOUT_PATH = "tests/data/test_layout01.json"


class StubHost:
    """Stands in for TrainController: real layout and scenario runner, no UI."""

    def __init__(self):
        self.communicator = Communicator(serial_factory=lambda port: FakeSerial(), time_to_initialize=0)
        self.layout = Layout(self.communicator)
        self.layout_path = LAYOUT_PATH
        self.layout_data = load_data_from_file(LAYOUT_PATH)
        assert self.layout.load(self.layout_data)[0]
        self.scenario_runner = ScenarioRunner(layout=self.layout)

    def run_on_ui(self, fn, *args):
        return fn(*args)

    def connect_serial(self, port=None):
        return self.communicator.connect(port or "/dev/fake")

    def disconnect_serial(self):
        self.communicator.disconnect()
        return True, ""

    def set_test_mode(self, enabled):
        self.layout.test_mode = enabled
        return True, ""

    def load_layout_file(self, path):
        data = load_data_from_file(path)
        ok, msg = self.layout.load(data)
        if ok:
            self.layout_data, self.layout_path = data, path
        return ok, msg

    def load_scenario_file(self, path):
        return self.scenario_runner.load_scenario(load_data_from_file(path))

    def run_scenario(self, times=None):
        if times is not None:
            self.scenario_runner.scenario.times = times
        self.scenario_runner.start()
        return True, ""

    def stop_scenario(self):
        self.scenario_runner.stop()
        return True, ""


@pytest.fixture
def host():
    return StubHost()


@pytest.fixture
def service(host, tmp_path):
    layouts, scenarios = tmp_path / "layouts", tmp_path / "scenarios"
    layouts.mkdir()
    scenarios.mkdir()
    (layouts / "other.json").write_text(json.dumps(load_data_from_file("tests/data/layout01.json")))
    (layouts / "notes.txt").write_text("not a layout")
    (scenarios / "quick.json").write_text(json.dumps({
        "name": "quick", "description": "short wait", "times": 1,
        "steps": [{"action": "TIME_WAIT", "value": 10}]}))
    return LayoutService(host, layout_dir=str(layouts), scenario_dir=str(scenarios))


def test_get_layout_describes_definition_and_derived_blocks(service):
    layout = service.get_layout()
    assert layout["name"] == load_data_from_file(LAYOUT_PATH)["name"]
    assert [segment["id"] for segment in layout["segments"]] == [1, 2, 3, 4]
    assert layout["points"][0]["direction_segments"] == [2, 4]
    assert {block["id"] for block in layout["blocks"]} == {1, 3}
    assert next(block for block in layout["blocks"] if block["id"] == 1)["sensor_ids"] == [1]


def test_layout_state_reports_every_device_type(service):
    state = service.get_layout_state()
    assert state["connection"]["connected"] is False
    assert state["tracks"][0]["electrified_segments"] == [1, 2, 3]
    assert state["points"][0]["direction_name"] == "PRIMARY"
    assert {block["id"]: block["occupied"] for block in state["blocks"]} == {1: False, 3: True}
    assert state["sensors"][0]["on"] is False
    assert state["speed_traps"][0]["last_speed"] == 0
    assert state["scenario"]["loaded"] is False


def test_get_device_and_list_devices(service):
    assert service.get_device("point", 1)["node"] == 1
    assert service.get_device("point", 99)["ok"] is False
    assert service.get_device("train", 1)["ok"] is False
    assert list(service.list_devices("sensor")) == ["sensor"]
    assert service.list_devices("bogus")["ok"] is False


def test_voltage_control_needs_connection_and_follows_rules(service, host):
    assert service.set_track_voltage(1, 50) == {"ok": False, "message": "Serial connection not established"}
    assert service.connect()["ok"]
    assert service.get_connection_status()["connected"] is True

    assert service.set_track_voltage(1, 50)["ok"]
    assert service.get_device("track", 1)["target_voltage"] == 50
    assert service.set_track_voltage(1, 500)["ok"] is False
    assert service.set_track_voltage(99, 10)["message"] == "Device not found"

    # actual voltage still positive: reversing is refused until stopped
    host.layout.components[DeviceType.ACTUAL_VOLTAGE.name][1]._actual_voltage = 50
    assert service.set_track_voltage(1, -10)["message"] == "Must be stopped before changing directions"

    assert service.emergency_stop()["ok"]
    assert service.get_device("track", 1)["target_voltage"] == 0
    assert service.emergency_stop(1)["ok"]


def test_point_direction_follows_rules(service):
    assert service.set_point_direction(1, 2)["ok"] is False
    service.set_test_mode(True)
    assert service.set_point_direction(1, 1)["ok"]
    assert service.get_device("point", 1)["direction"] == 1
    assert service.set_point_direction(99, 1)["message"] == "Device not found"


def test_point_refuses_switching_under_occupied_block(service, host):
    service.set_test_mode(True)
    host.layout.components[DeviceType.ACTUAL_VOLTAGE.name][1]._actual_voltage = 50
    # block 3 is occupied and its segments lose power when the point moves to its secondary route
    result = service.set_point_direction(1, 1)
    assert result == {"ok": False, "message": "Occupied block would change voltage"}
    assert service.get_device("point", 1)["direction"] == 0


def test_set_sensor_updates_sensor_and_blocks(service):
    assert service.set_sensor(1, True)["ok"]
    assert service.get_device("sensor", 1)["on"] is True
    assert service.set_sensor(1, True)["ok"] is False
    assert service.set_sensor(1, False)["ok"]


def test_connect_and_disconnect(service):
    assert service.connect("/dev/fake-port")["ok"]
    assert service.get_connection_status()["port"] == "/dev/fake-port"
    service.disconnect()
    assert service.get_connection_status() == {
        "connected": False, "port": None, "test_mode": False, "scenario_running": False}


def test_layout_files_are_listed_and_restricted(service):
    assert service.list_layout_files() == {"files": ["other.json"]}
    assert service.load_layout("other.json")["ok"]
    assert service.get_layout()["name"] == load_data_from_file("tests/data/layout01.json")["name"]
    for name in ("../tests/data/layout01.json", "notes.txt", "missing.json", os.path.abspath(LAYOUT_PATH)):
        assert service.load_layout(name)["ok"] is False


def test_scenario_load_and_run(service, host):
    assert service.list_scenario_files() == {"files": ["quick.json"]}
    assert service.load_scenario("../scenarios/quick.json")["ok"] is False
    assert service.load_scenario("quick.json")["ok"]

    status = service.get_scenario_status()
    assert status["loaded"] and status["name"] == "quick" and status["status"] == "Ready"
    assert service.start_scenario(times=0)["ok"] is False

    assert service.start_scenario(times=2)["ok"]
    host.scenario_runner._thread.join(timeout=5)
    status = service.get_scenario_status()
    assert status["running"] is False and status["times"] == 2 and status["message"] == "Completed"


def test_scenario_cannot_be_replaced_while_running(service, host):
    service.load_scenario("quick.json")
    host.scenario_runner.scenario.steps[0].value = 5000
    assert service.start_scenario()["ok"]
    assert service.load_layout("other.json")["ok"] is False
    assert service.load_scenario("quick.json")["ok"] is False
    assert service.stop_scenario()["ok"]
    host.scenario_runner._thread.join(timeout=5)
    assert service.get_scenario_status()["running"] is False


def test_server_registers_every_tool_with_read_only_hints(service):
    server = build_server(service)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert set(tools) == set(READ_ONLY_TOOLS) | set(CONTROL_TOOLS)
    assert all(tools[name].annotations.readOnlyHint for name in READ_ONLY_TOOLS)
    assert not any(tools[name].annotations.readOnlyHint for name in CONTROL_TOOLS)
    assert set(tools["set_point_direction"].inputSchema["required"]) == {"point_id", "direction"}
