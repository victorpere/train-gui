from __future__ import annotations

import time
from threading import Thread
from typing import Callable, List, TypedDict, NotRequired, cast
from enum import Enum
from railway import Layout, DeviceType, MessageType, Message


class ScenarioAction(Enum):
    DEVICE_WAIT = 0
    DEVICE_SET = 1
    TIME_WAIT = 2


class ScenarioStep(TypedDict):
    action: str
    device_type: NotRequired[str]
    device_id: NotRequired[int]
    value: int


class Scenario(TypedDict):
    name: str
    description: str
    times: int
    steps: List[ScenarioStep]


class ScenarioRunner:
    """Execute a JSON-defined scenario against a Track."""

    def __init__(self, scenario: dict, layout: Layout):
        self.scenario: Scenario = cast(Scenario, scenario)
        # TODO: scenario validation

        self.layout = layout
        self.current_step: ScenarioStep = None
        self._stop_requested = False
        self._thread = None
        self._listeners: List[Callable[[str, object], None]] = []

    def add_listener(self, cb: Callable[[str, object], None]):
        self._listeners.append(cb)

    def _notify(self, name: str, value: object):
        for cb in list(self._listeners):
            try:
                cb(name, value)
            except Exception:
                pass

    def _stop(self):
        self.current_step = None
        self.layout.stop_all()
        self._notify("scenario_status", "Stopped")
        self._notify("scenario_step", None)

    def _set_current_step(self, step: ScenarioStep):
        self.current_step = step
        step_name = f"{step.get('action')}:{step.get('device_type', '')}:{step.get('device_id', '')}:{step.get('value')}"
        self._notify("scenario_step", step_name)
        self._notify("scenario_status", f"Running {step_name}")

    def _run_step(self, step: ScenarioStep):
        if step["action"] == ScenarioAction.DEVICE_SET.name:
            message: Message = {
                "message_type": MessageType.SET,
                "device_type": DeviceType[step["device_type"]],
                "device_id": step["device_id"],
                "value": step["value"]
            }
            ok, msg = self.layout.command(message)
            if not ok:
                print(f"scenario._run_step error: {msg}")
                raise RuntimeError(msg)
            return

        if step["action"] == ScenarioAction.DEVICE_WAIT.name:
            message: Message = {
                "message_type": MessageType.QUERY,
                "device_type": DeviceType[step["device_type"]],
                "device_id": step["device_id"],
                "value": 0
            }
            target_value = step["value"]
            target_reached = False
            while not self._stop_requested and not target_reached:
                ok, msg = self.layout.command(message)
                if not ok:
                    raise Exception(msg)
                actual_value = int(msg)
                if actual_value == target_value:
                    target_reached = True
                else:
                    time.sleep(0.05)
            if self._stop_requested:
                raise InterruptedError("Scenario stopped")
            return

        if step["action"] == ScenarioAction.TIME_WAIT.name:
            wait_ms = step["value"]
            end = time.monotonic() + (wait_ms / 1000.0)
            while not self._stop_requested and time.monotonic() < end:
                time.sleep(0.05)
            if self._stop_requested:
                raise InterruptedError("Scenario stopped")
            return

        print("Unsupported step")
        raise ValueError(f"Unsupported step")

    def run(self) -> bool:
        """Execute the scenario synchronously."""
        self._stop_requested = False
        try:
            for _ in range(self.scenario.get("times")):
                for step in self.scenario.get("steps"):
                    print("scenario.run step start")
                    if self._stop_requested:
                        self.stop()
                        return False
                    self._set_current_step(step)
                    self._run_step(step)
                    print(f"scenario.run step finish")
            self.current_step = None
            self._notify("scenario_step", None)
            self._notify("scenario_status", f"Completed {self.scenario['name']}")
            return True
        except InterruptedError:
            self.stop()
            return False
        except Exception as exc:
            print(f"scenario.run exception: {str(exc)}")
            self.stop()
            self._notify("scenario_error", str(exc))
            return False

    def start(self):
        if self._thread and self._thread.is_alive():
            return self._thread
        self._thread = Thread(target=self.run, daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self._stop_requested = True

    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive())
