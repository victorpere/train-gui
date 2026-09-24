import time
from pydantic import BaseModel
from threading import Thread
from typing import Callable, List, Optional, Tuple
from enum import Enum
from railway import Layout, DeviceType, MessageType, Message


class ScenarioAction(Enum):
    DEVICE_WAIT = 0
    DEVICE_SET = 1
    TIME_WAIT = 2


class ScenarioStep(BaseModel):
    action: str
    device_type: Optional[str] = None
    device_id: Optional[int] = None
    value: int

    @property
    def name(self) -> str:
        return f"{self.action}:{self.device_type or ""}:{self.device_id or ""}:{self.value}"


class Scenario(BaseModel):
    name: str
    description: str
    times: int
    steps: List[ScenarioStep]


class ScenarioStatus(Enum):
    READY = "Ready"
    RUNNING = "Running"


class ScenarioState(BaseModel):
    status: ScenarioStatus
    step: Optional[ScenarioStep] = None
    iteration: Optional[int] = None
    message: Optional[str] = None


class ScenarioRunner:
    """Execute a JSON-defined scenario against a Track."""

    def __init__(self, layout: Layout):
        self.layout = layout
        self.scenario = None
        self._stop_requested = False
        self._thread = None
        self._listeners: List[Callable[[str, object], None]] = []

    def load_scenario(self, scenario_data: dict) -> Tuple[bool, str]:
        try:
            self.scenario = Scenario(**scenario_data)
            self.state = ScenarioState(status=ScenarioStatus.READY)
            return True, ""
        except Exception as exc:
            self.state = None
            return False, str(exc)

    @property
    def state(self) -> ScenarioState:
        return self._state

    @state.setter
    def state(self, value: ScenarioState):
        self._state = value
        self._notify("scenario_state", self._state)

    def add_listener(self, cb: Callable[[str, object], None]):
        self._listeners.append(cb)

    def _notify(self, name: str, value: object):
        for cb in list(self._listeners):
            try:
                cb(name, value)
            except Exception:
                pass

    def _stop(self):
        self.layout.stop_all()

    def _run_step(self, step: ScenarioStep):
        if step.action == ScenarioAction.DEVICE_SET.name:
            message = Message(
                message_type = MessageType.SET,
                device_type = DeviceType[step.device_type],
                device_id = step.device_id,
                value = step.value
            )
            ok, msg = self.layout.command(message)
            if not ok:
                print(f"scenario._run_step error: {msg}")
                raise RuntimeError(msg)
            return

        if step.action == ScenarioAction.DEVICE_WAIT.name:
            message = Message(
                message_type = MessageType.QUERY,
                device_type = DeviceType[step.device_type],
                device_id = step.device_id,
                value = 0
            )
            target_value = step.value
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

        if step.action == ScenarioAction.TIME_WAIT.name:
            wait_ms = step.value
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
            for i in range(self.scenario.times):
                self.state = ScenarioState(status=ScenarioStatus.RUNNING, iteration=i+1)
                for step in self.scenario.steps:
                    if self._stop_requested:
                        self._stop()
                        self.state = ScenarioState(status=ScenarioStatus.READY, message="Stopped")
                        return False
                    self.state = ScenarioState(status=ScenarioStatus.RUNNING, iteration=i+1, step=step)
                    self._run_step(step)
            self._stop()
            self.state = ScenarioState(status=ScenarioStatus.READY, message="Completed")
            return True
        except InterruptedError:
            self._stop()
            self.state = ScenarioState(status=ScenarioStatus.READY, message="Interrupted")
            return False
        except Exception as exc:
            print(f"scenario.run exception: {str(exc)}")
            self._stop()
            self.state = ScenarioState(status=ScenarioStatus.READY, message=str(exc))
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
