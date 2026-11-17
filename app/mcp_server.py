"""MCP server exposing the layout and its devices to MCP clients.

It runs inside the GUI process (see train_gui.py) so it shares the live Layout and the serial connection.
LayoutService holds the logic and has no dependency on the mcp package; build_server wires it to FastMCP.
"""
import os
import threading
from typing import Any, Callable, Optional, Protocol, Tuple

from railway import Layout, Message, MessageType, DeviceType
from scenario import ScenarioRunner
from util import EMERGENCY_STOP, MAX_VOLTAGE

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAYOUT_DIR = os.path.join(BASE_DIR, "data", "layouts")
SCENARIO_DIR = os.path.join(BASE_DIR, "data", "scenarios")
DATA_EXTENSIONS = (".json", ".yaml", ".yml")

# Tool-facing device type names and the component group each one lives in
DEVICE_GROUPS = {
    "track": DeviceType.TARGET_VOLTAGE,
    "block": DeviceType.BLOCK,
    "sensor": DeviceType.SENSOR,
    "point": DeviceType.POINT_DIRECTION,
    "speed_trap": DeviceType.SPEED,
}


class Host(Protocol):
    """What the service needs from the application (implemented by TrainController).
    Methods that touch the UI are only called through run_on_ui."""
    layout: Layout
    scenario_runner: ScenarioRunner
    layout_data: dict
    layout_path: Optional[str]

    def run_on_ui(self, fn: Callable, *args) -> Any: ...
    def connect_serial(self, port: Optional[str] = None) -> Tuple[bool, str]: ...
    def disconnect_serial(self) -> Tuple[bool, str]: ...
    def set_test_mode(self, enabled: bool) -> Tuple[bool, str]: ...
    def load_layout_file(self, path: str) -> Tuple[bool, str]: ...
    def load_scenario_file(self, path: str) -> Tuple[bool, str]: ...
    def run_scenario(self, times: Optional[int] = None) -> Tuple[bool, str]: ...
    def stop_scenario(self) -> Tuple[bool, str]: ...


def _result(ok: bool, message: str = "", **extra) -> dict:
    return {"ok": ok, "message": message, **extra}


class LayoutService:
    """Layout information and device control for MCP tools. Every method returns a JSON-friendly value;
    failures are reported as {"ok": False, "message": ...} rather than raised."""

    def __init__(self, host: Host, layout_dir: str = LAYOUT_DIR, scenario_dir: str = SCENARIO_DIR):
        self._host = host
        self._layout_dir = layout_dir
        self._scenario_dir = scenario_dir

    @property
    def _layout(self) -> Layout:
        return self._host.layout

    def _devices(self, device_type: DeviceType) -> dict:
        return dict(self._layout.components.get(device_type.name, {}))

    def _command(self, device_type: DeviceType, device_id: int, value: int) -> dict:
        ok, msg = self._layout.command(Message(message_type=MessageType.SET, device_type=device_type,
                                               device_id=device_id, value=value))
        return _result(ok, "" if ok else str(msg))

    # --- serialization of device state ---

    def _describe(self, kind: str, device) -> dict:
        if kind == "track":
            return {
                "id": device.id,
                "target_voltage": device.target_voltage,
                "actual_voltage": device.actual_voltage,
                "travel_direction": device.travel_direction,
                "feeder_segment_id": device.feeder_segment_id,
                "electrified_segments": self._layout.electrified_segments().get(device.id, []),
            }
        if kind == "block":
            return {"id": device.id, "occupied": device.occupied,
                    "segment_ids": device.segment_ids, "sensor_ids": device.sensor_ids}
        if kind == "sensor":
            return {"id": device.id, "node": device.node, "on": device.on}
        if kind == "point":
            return {"id": device.id, "node": device.node, "direction": device.direction,
                    "direction_name": "PRIMARY" if device.direction == 0 else "SECONDARY",
                    "direction_segments": list(device.direction_segments)}
        if kind == "speed_trap":
            return {"id": device.id, "track_id": device.track_id,
                    "sensor_1_id": device.sensor_1_id, "sensor_2_id": device.sensor_2_id,
                    "distance": device.distance, "last_speed_kmh": device.last_speed}
        raise ValueError(kind)

    def _kind(self, device_type: str) -> str:
        kind = str(device_type).strip().lower()
        if kind not in DEVICE_GROUPS:
            raise ValueError(f"Unknown device type '{device_type}', expected one of {sorted(DEVICE_GROUPS)}")
        return kind

    # --- layout information ---

    def get_layout(self) -> dict:
        """Static definition of the loaded layout: name, description, scale, nodes (diagram coordinates),
        segments (track pieces between nodes), insulated joints, tracks (power feeders), blocks (groups of
        segments, derived from sensor positions), sensors, points (switches) and speed traps."""
        data = self._host.layout_data or {}
        layout = self._layout
        return {
            "file": self._host.layout_path,
            "name": layout.name,
            "description": layout.description,
            "scale": getattr(layout, "scale", 0),
            "nodes": data.get("nodes", []),
            "segments": data.get("segments", []),
            "insulated_joints": data.get("insulated_joints", []),
            "tracks": data.get("tracks", []),
            "blocks": [{"id": b.id, "segment_ids": b.segment_ids, "sensor_ids": b.sensor_ids}
                       for b in self._devices(DeviceType.BLOCK).values()],
            "sensors": data.get("sensors", []),
            "points": data.get("points", []),
            "speed_traps": data.get("speed_traps", []),
        }

    def get_layout_state(self) -> dict:
        """Live state of everything: connection, tracks (voltages, direction, electrified segments), blocks
        (occupied), sensors (on/off), points (direction), speed traps (last speed) and the scenario."""
        state: dict = {"connection": self.get_connection_status(), "scenario": self.get_scenario_status()}
        for kind, device_type in DEVICE_GROUPS.items():
            state[f"{kind}s"] = [self._describe(kind, d) for d in self._devices(device_type).values()]
        return state

    def list_devices(self, device_type: Optional[str] = None) -> dict:
        """Live state of the devices of one type (track, block, sensor, point, speed_trap), or of all
        types if device_type is omitted."""
        try:
            kinds = [self._kind(device_type)] if device_type else list(DEVICE_GROUPS)
        except ValueError as exc:
            return _result(False, str(exc))
        return {kind: [self._describe(kind, d) for d in self._devices(DEVICE_GROUPS[kind]).values()]
                for kind in kinds}

    def get_device(self, device_type: str, device_id: int) -> dict:
        """Live state of one device. device_type is track, block, sensor, point or speed_trap."""
        try:
            kind = self._kind(device_type)
        except ValueError as exc:
            return _result(False, str(exc))
        device = self._devices(DEVICE_GROUPS[kind]).get(device_id)
        if device is None:
            return _result(False, f"{kind} {device_id} not found")
        return self._describe(kind, device)

    def get_connection_status(self) -> dict:
        """Serial connection status, test mode (points switch without a connection) and whether a scenario runs."""
        communicator = self._layout.communicator
        return {"connected": communicator.is_connected,
                "port": communicator.port if communicator.is_connected else None,
                "test_mode": self._layout.test_mode,
                "scenario_running": self._host.scenario_runner.is_running}

    # --- device control ---

    def set_track_voltage(self, track_id: int, voltage: int) -> dict:
        """Set the target voltage of a track, -127..127 (sign is the direction; 0 stops).
        A moving track must be stopped before its direction changes."""
        if not -MAX_VOLTAGE <= voltage <= MAX_VOLTAGE:
            return _result(False, f"voltage must be between {-MAX_VOLTAGE} and {MAX_VOLTAGE}")
        return self._command(DeviceType.TARGET_VOLTAGE, track_id, voltage)

    def emergency_stop(self, track_id: Optional[int] = None) -> dict:
        """Cut the voltage immediately on one track, or on all tracks if track_id is omitted."""
        tracks = self._devices(DeviceType.TARGET_VOLTAGE)
        if track_id is not None:
            return self._command(DeviceType.TARGET_VOLTAGE, track_id, EMERGENCY_STOP)
        results = {track: self._command(DeviceType.TARGET_VOLTAGE, track, EMERGENCY_STOP) for track in tracks}
        failed = {track: r["message"] for track, r in results.items() if not r["ok"]}
        return _result(not failed, "; ".join(f"track {t}: {m}" for t, m in failed.items()), tracks=results)

    def set_point_direction(self, point_id: int, direction: int) -> dict:
        """Switch a point: 0 = primary, 1 = secondary. Refused if it would change the voltage on an occupied block."""
        if direction not in (0, 1):
            return _result(False, "direction must be 0 (primary) or 1 (secondary)")
        return self._command(DeviceType.POINT_DIRECTION, point_id, direction)

    def set_sensor(self, sensor_id: int, on: bool) -> dict:
        """Simulate a sensor turning on or off (like clicking it in the GUI); nothing is sent over serial."""
        return self._command(DeviceType.SENSOR, sensor_id, int(on))

    # --- connection ---

    def list_serial_ports(self) -> dict:
        """Serial ports available on this computer."""
        try:
            from serial.tools import list_ports
            return {"ports": [{"device": p.device, "description": p.description} for p in list_ports.comports()]}
        except Exception as exc:
            return _result(False, f"Cannot list serial ports: {exc}")

    def connect(self, port: Optional[str] = None) -> dict:
        """Connect to the layout controller on a serial port (the GUI's port if omitted)."""
        return _result(*self._host.run_on_ui(self._host.connect_serial, port))

    def disconnect(self) -> dict:
        """Disconnect from the layout controller."""
        return _result(*self._host.run_on_ui(self._host.disconnect_serial))

    def set_test_mode(self, enabled: bool) -> dict:
        """Turn test mode on or off. In test mode points switch without a serial connection."""
        return _result(*self._host.run_on_ui(self._host.set_test_mode, enabled))

    # --- layouts and scenarios ---

    @staticmethod
    def _list_files(directory: str) -> list[str]:
        try:
            return sorted(f for f in os.listdir(directory) if f.lower().endswith(DATA_EXTENSIONS))
        except OSError:
            return []

    def _resolve(self, directory: str, name: str) -> Optional[str]:
        """Path of a file in the directory; only plain names from the directory listing are accepted."""
        return os.path.join(directory, name) if name in self._list_files(directory) else None

    def list_layout_files(self) -> dict:
        """Layout files that can be loaded."""
        return {"files": self._list_files(self._layout_dir)}

    def load_layout(self, file_name: str) -> dict:
        """Load a layout file listed by list_layout_files. Not allowed while a scenario is running."""
        path = self._resolve(self._layout_dir, file_name)
        if path is None:
            return _result(False, f"Layout file '{file_name}' not found; see list_layout_files")
        if self._host.scenario_runner.is_running:
            return _result(False, "Stop the running scenario before loading a layout")
        return _result(*self._host.run_on_ui(self._host.load_layout_file, path))

    def list_scenario_files(self) -> dict:
        """Scenario files that can be loaded."""
        return {"files": self._list_files(self._scenario_dir)}

    def load_scenario(self, file_name: str) -> dict:
        """Load a scenario file listed by list_scenario_files."""
        path = self._resolve(self._scenario_dir, file_name)
        if path is None:
            return _result(False, f"Scenario file '{file_name}' not found; see list_scenario_files")
        if self._host.scenario_runner.is_running:
            return _result(False, "Stop the running scenario before loading another")
        return _result(*self._host.run_on_ui(self._host.load_scenario_file, path))

    def start_scenario(self, times: Optional[int] = None) -> dict:
        """Start the loaded scenario, optionally overriding how many times it repeats."""
        if times is not None and times < 1:
            return _result(False, "times must be at least 1")
        return _result(*self._host.run_on_ui(self._host.run_scenario, times))

    def stop_scenario(self) -> dict:
        """Stop the running scenario; all tracks are stopped."""
        return _result(*self._host.run_on_ui(self._host.stop_scenario))

    def get_scenario_status(self) -> dict:
        """The loaded scenario and its run status (Ready, Running or Error), iteration and current step."""
        runner = self._host.scenario_runner
        scenario = runner.scenario
        status: dict = {"loaded": scenario is not None, "running": runner.is_running}
        if scenario is not None:
            status.update(name=scenario.name, description=scenario.description, times=scenario.times,
                          steps=[step.name for step in scenario.steps])
        try:
            state = runner.state
        except AttributeError:
            state = None
        if state is not None:
            status.update(status=state.status.value, iteration=state.iteration, message=state.message,
                          current_step=state.step.name if state.step else None)
        return status


READ_ONLY_TOOLS = (
    "get_layout", "get_layout_state", "list_devices", "get_device", "get_connection_status",
    "list_serial_ports", "list_layout_files", "list_scenario_files", "get_scenario_status",
)
CONTROL_TOOLS = (
    "set_track_voltage", "emergency_stop", "set_point_direction", "set_sensor",
    "connect", "disconnect", "set_test_mode",
    "load_layout", "load_scenario", "start_scenario", "stop_scenario",
)


def build_server(service: LayoutService, host: str = "127.0.0.1", port: int = 8765):
    """FastMCP server with all service methods registered as tools."""
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations

    server = FastMCP("train-gui", host=host, port=port, log_level="WARNING", instructions=(
        "Tools to read the model railway layout and control its devices (track voltage, points, sensors). "
        "Start with get_layout and get_layout_state. Commands act on real hardware when connected."))
    for names, read_only in ((READ_ONLY_TOOLS, True), (CONTROL_TOOLS, False)):
        for name in names:
            server.add_tool(getattr(service, name), name=name,
                            annotations=ToolAnnotations(readOnlyHint=read_only))
    return server


class McpServerThread:
    """Runs the MCP server (streamable HTTP at /mcp) in a daemon thread."""

    def __init__(self, service: LayoutService, host: str = "127.0.0.1", port: int = 8765):
        self.host, self.port = host, port
        self._service = service
        self._uvicorn = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/mcp"

    def start(self):
        import uvicorn
        app = build_server(self._service, self.host, self.port).streamable_http_app()
        self._uvicorn = uvicorn.Server(uvicorn.Config(app, host=self.host, port=self.port, log_level="warning"))
        self._thread = threading.Thread(target=self._uvicorn.run, daemon=True, name="mcp-server")
        self._thread.start()

    def stop(self):
        if self._uvicorn:
            self._uvicorn.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
