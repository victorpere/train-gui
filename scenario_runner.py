from __future__ import annotations

import time
from threading import Thread
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from track import Track


class ScenarioRunner:
    """Execute a JSON-defined scenario against a Track."""

    def __init__(self, scenario: Optional[dict] = None, track: Optional["Track"] = None):
        self.scenario = scenario or {}
        self.track = track or self._create_default_track()
        self.name = str(self.scenario.get("name", "unnamed"))
        self.times = int(self.scenario.get("times", 1))
        self.steps = list(self.scenario.get("steps", []))
        self.current_step = None
        self._stop_requested = False
        self._thread = None
        self._listeners: List[Callable[[str, object], None]] = []

    def _create_default_track(self):
        from track import Track
        return Track()

    def add_listener(self, cb: Callable[[str, object], None]):
        self._listeners.append(cb)

    def _notify(self, name: str, value: object):
        for cb in list(self._listeners):
            try:
                cb(name, value)
            except Exception:
                pass

    def _set_current_step(self, step: dict):
        self.current_step = step
        step_name = step.get("step", "") if isinstance(step, dict) else str(step)
        self._notify("scenario_step", step_name)
        self._notify("scenario_status", f"Running {step_name}")

    def _run_step(self, step: dict):
        if not isinstance(step, dict):
            raise ValueError(f"Invalid step definition: {step!r}")

        step_name = step.get("step")

        if step_name == "direction_set":
            direction = int(step.get("direction", self.track.direction))
            ok, msg = self.track.set_direction(direction)
            if not ok:
                raise RuntimeError(msg)
            return

        if step_name == "voltage_target_set":
            voltage = int(step.get("voltage", 0))
            ok, msg = self.track.set_voltage(voltage)
            if not ok:
                raise RuntimeError(msg)
            return

        if step_name == "voltage_actual_wait":
            target = int(step.get("voltage", 0))
            while not self._stop_requested and self.track.actual_voltage != target:
                time.sleep(0.05)
            if self._stop_requested:
                raise InterruptedError("Scenario stopped")
            return

        if step_name == "time_wait":
            wait_ms = int(step.get("time", 0))
            end = time.monotonic() + (wait_ms / 1000.0)
            while not self._stop_requested and time.monotonic() < end:
                time.sleep(0.05)
            if self._stop_requested:
                raise InterruptedError("Scenario stopped")
            return

        raise ValueError(f"Unsupported step: {step_name!r}")

    def run(self) -> bool:
        """Execute the scenario synchronously."""
        self._stop_requested = False
        try:
            for _ in range(self.times):
                for step in self.steps:
                    if self._stop_requested:
                        self._notify("scenario_status", "Stopped")
                        self.current_step = None
                        self.track.set_voltage(0)
                        self._notify("scenario_step", None)
                        return False
                    self._set_current_step(step)
                    self._run_step(step)
            self.current_step = None
            self._notify("scenario_step", None)
            self._notify("scenario_status", f"Completed {self.name}")
            return True
        except InterruptedError:
            self.current_step = None
            self.track.set_voltage(0)
            self._notify("scenario_step", None)
            self._notify("scenario_status", "Stopped")
            return False
        except Exception as exc:
            self.current_step = None
            self.track.set_voltage(0)
            self._notify("scenario_step", None)
            self._notify("scenario_status", f"Error: {exc}")
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
