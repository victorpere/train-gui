import operator
import time
from pydantic import BaseModel, model_validator
from threading import Thread
from typing import Callable, List, Optional, Tuple
from enum import Enum
from railway import Layout, DeviceType, MessageType, Message


class ScenarioAction(Enum):
    DEVICE_WAIT = 0
    DEVICE_SET = 1
    TIME_WAIT = 2
    DEVICE_ADJUST = 3
    DEVICE_CONDITION = 4
    LOOP = 5


CONDITION_OPERATORS = {
    "EQ": operator.eq,
    "GT": operator.gt,
    "GE": operator.ge,
    "LT": operator.lt,
    "LE": operator.le,
    "NE": operator.ne,
}


class _LoopTimeout(Exception):
    """Raised inside a blocking step when the deadline of an enclosing LOOP is reached."""

    def __init__(self, deadline: float):
        super().__init__("Loop duration reached")
        self.deadline = deadline


class ScenarioStep(BaseModel):
    action: str
    device_type: Optional[str] = None
    device_id: Optional[int] = None
    value: int = 0
    operator: Optional[str] = None
    times: Optional[int] = None
    duration: Optional[float] = None
    steps: Optional[List["ScenarioStep"]] = None

    @model_validator(mode="after")
    def _validate_condition(self):
        if self.action == ScenarioAction.DEVICE_CONDITION.name:
            if self.operator not in CONDITION_OPERATORS:
                raise ValueError(
                    f"DEVICE_CONDITION operator must be one of {', '.join(CONDITION_OPERATORS)}")
            if not self.steps:
                raise ValueError("DEVICE_CONDITION requires a non-empty list of steps")
        if self.action == ScenarioAction.LOOP.name:
            if self.times is None and self.duration is None:
                raise ValueError("LOOP requires at least one of times or duration")
            if self.times is not None and self.times < 1:
                raise ValueError("LOOP times must be at least 1")
            if self.duration is not None and self.duration <= 0:
                raise ValueError("LOOP duration must be greater than 0")
            if not self.steps:
                raise ValueError("LOOP requires a non-empty list of steps")
        return self

    @model_validator(mode="before")
    @classmethod
    def _parse_compact_form(cls, data):
        """Allow steps given as "ACTION:DEVICE_TYPE:DEVICE_ID:VALUE" strings (used by YAML scenarios)."""
        if isinstance(data, str):
            action, device_type, device_id, value = data.split(":")
            return {
                "action": action,
                "device_type": device_type or None,
                "device_id": int(device_id) if device_id else None,
                "value": int(value),
            }
        return data

    @property
    def name(self) -> str:
        return f"{self.action}:{self.device_type or ""}:{"" if self.device_id is None else self.device_id}:{self.value}"


class Scenario(BaseModel):
    name: str
    description: str
    times: int
    steps: List[ScenarioStep]


class ScenarioStatus(Enum):
    READY = "Ready"
    RUNNING = "Running"
    ERROR = "Error"


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
        self._deadlines: List[float] = []
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

    def _check_deadlines(self):
        """Abort the current blocking step if an enclosing LOOP has run out of time."""
        now = time.monotonic()
        for deadline in self._deadlines:
            if now >= deadline:
                raise _LoopTimeout(deadline)

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
                self._check_deadlines()
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
                self._check_deadlines()
                time.sleep(0.05)
            if self._stop_requested:
                raise InterruptedError("Scenario stopped")
            return

        if step.action == ScenarioAction.DEVICE_ADJUST.name:
            device_type = DeviceType[step.device_type]
            ok, msg = self.layout.command(Message(
                message_type = MessageType.QUERY,
                device_type = device_type,
                device_id = step.device_id,
                value = 0
            ))
            if not ok:
                raise RuntimeError(msg)
            ok, msg = self.layout.command(Message(
                message_type = MessageType.SET,
                device_type = device_type,
                device_id = step.device_id,
                value = int(msg) + step.value
            ))
            if not ok:
                raise RuntimeError(msg)
            return

        if step.action == ScenarioAction.DEVICE_CONDITION.name:
            ok, msg = self.layout.command(Message(
                message_type = MessageType.QUERY,
                device_type = DeviceType[step.device_type],
                device_id = step.device_id,
                value = 0
            ))
            if not ok:
                raise RuntimeError(msg)
            if CONDITION_OPERATORS[step.operator](int(msg), step.value):
                print(f"{int(msg)} {step.operator} {step.value}")
                for nested_step in step.steps:
                    if self._stop_requested:
                        raise InterruptedError("Scenario stopped")
                    self._run_step(nested_step)
            return

        if step.action == ScenarioAction.LOOP.name:
            deadline = None if step.duration is None else time.monotonic() + step.duration
            if deadline is not None:
                self._deadlines.append(deadline)
            try:
                iteration = 0
                while step.times is None or iteration < step.times:
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    iteration += 1
                    for nested_step in step.steps:
                        if self._stop_requested:
                            raise InterruptedError("Scenario stopped")
                        self._check_deadlines()
                        self._run_step(nested_step)
            except _LoopTimeout as timeout:
                if timeout.deadline != deadline:
                    raise
            finally:
                if deadline is not None:
                    self._deadlines.pop()
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
            self.state = ScenarioState(status=ScenarioStatus.ERROR, message=str(exc))
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
