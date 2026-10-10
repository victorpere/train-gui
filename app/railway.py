from time import monotonic, sleep
from pydantic import BaseModel
from typing import List, Tuple, Protocol, overload
from enum import Enum
from communication import Communicator


class MessageType(Enum):
    QUERY = 0
    SET = 1


class DeviceType(Enum):
    ACTUAL_VOLTAGE = 0
    TARGET_VOLTAGE = 1
    BLOCK = 2
    SENSOR = 3
    POINT_DIRECTION = 4
    SIGNAL = 5
    SPEED = 10


class PointDirection(Enum):
    PRIMARY = 0
    SECONDARY = 1


class Message(BaseModel):
    message_type: MessageType
    device_type: DeviceType
    device_id: int
    value: int


class LayoutComponent(Protocol):
    def process_message(self, message: Message) -> Tuple[bool, str]: ...


class Callback(Protocol):
    @overload
    def __call__(self, message: Message) -> Tuple[bool, str]: ...
    @overload
    def __call__(self, name: str, value: object): ...


class Layout:
    """Manages layout components such as track and blocks, and handles communication
    """

    def __init__(self, communicator: Communicator):
        self.communicator = communicator
        self.communicator.add_listener(self._on_communication_event)
        self.components: dict[str, dict[int, LayoutComponent]] = {}
        self.name = ""
        self.description = ""
        self._listeners: List[Callback] = []
        self.diagram_data = None

    def load(self, layout_data: dict) -> Tuple[bool, str]:
        """Creates layout and components from a dictionary definition"""
        try:
            self.name = layout_data.get("name", "n/a")
            self.description = layout_data.get("description", "n/a")
            self.scale: float = layout_data.get("scale", 0)
            self.diagram_data: dict = layout_data.get("diagram")
            tracks = layout_data.get("tracks", [])
            blocks = layout_data.get("blocks", [])
            sensors = layout_data.get("sensors", [])
            speed_traps = layout_data.get("speed_traps", [])
            points = layout_data.get("points", [])

            for device_type_name, _ in DeviceType.__members__.items():
                """Add all device types to components"""
                self.components[device_type_name] = dict()

            for track_data in tracks:
                track = Track(track_data.get("id"), self._on_component_event, self.command, feeder_segment_id=track_data.get(
                    "feeder_segment_id"), segments_data=track_data.get("segments"))
                self.components[DeviceType.TARGET_VOLTAGE.name][track.id] = track
                self.components[DeviceType.ACTUAL_VOLTAGE.name][track.id] = track

            for block_data in blocks:
                block = Block(block_data.get("id"), block_data.get("occupied", False), self._on_component_event)
                self.components[DeviceType.BLOCK.name][block.id] = block

            for sensor_data in sensors:
                track = self.components[DeviceType.TARGET_VOLTAGE.name][sensor_data.get("track_id")]
                block_f = self.components[DeviceType.BLOCK.name][sensor_data.get("block_f_id")]
                block_r = self.components[DeviceType.BLOCK.name][sensor_data.get("block_r_id")]
                sensor = Sensor(sensor_data.get("id"), track, block_f, block_r, self._on_component_event, sensor_data.get("diagram"))
                self.components[DeviceType.SENSOR.name][sensor.id] = sensor

            for speed_trap_data in speed_traps:
                speed_trap = SpeedTrap(id=speed_trap_data.get("id"),
                                       track_id=speed_trap_data.get("track_id"),
                                       sensor_1_id=speed_trap_data.get("sensor_1_id"),
                                       sensor_2_id=speed_trap_data.get("sensor_2_id"),
                                       distance=speed_trap_data.get("distance"),
                                       cb=self._on_component_event)
                self.add_listener(speed_trap.receive_component_event)
                self.components[DeviceType.SPEED.name][speed_trap.id] = speed_trap

            for point_data in points:
                point = Point(point_data, layout=self, cb=self._on_component_event)
                self.components[DeviceType.POINT_DIRECTION.name][point.id] = point

            return True, ""

        except Exception as exc:
            print(f"Failed to load layout {str(exc)}")
            return False, str(exc)

    def add_listener(self, cb: Callback):
        """Add a listener to layout component events"""
        self._listeners.append(cb)

    def command(self, message: Message) -> Tuple[bool, str]:
        """Processes command to component"""
        target_type_components = self.components.get(message.device_type.name, {})
        target_component = target_type_components.get(message.device_id)

        if target_component == None:
            print(f"device not foud: {message.device_type.name}:{message.device_id}")
            return False, "Device not found"
        return target_component.process_message(message)

    def stop_all(self):
        """Sets target voltage to 0 on all tracks"""
        target_voltage_devices = self.components.get(DeviceType.TARGET_VOLTAGE.name)
        for target_voltage_device in target_voltage_devices.values():
            track: Track = target_voltage_device
            ok, msg = track.set_voltage(0)

    def electrified_segments(self) -> dict[int, list[int]]:
        segments: dict[int, list[int]] = {}
        track_components = self.components.get(DeviceType.TARGET_VOLTAGE.name)
        for track_component in track_components.values():
            track: Track = track_component
            segments[track.id] = track.electrified_segments()
        # print(f"Layout.electrified_segments: {segments}")
        return segments

    def _initialize(self, delay: float):
        points = self.components.get(DeviceType.POINT_DIRECTION.name)
        sleep(delay)
        for point in points.values():
            message = Message(
                message_type=MessageType.SET,
                device_type=DeviceType.POINT_DIRECTION,
                device_id=point.id,
                value=point.direction
            )
            ok, msg = self.command(message)
            if not ok:
                print(f"error initializing point {point.id}: {msg}")

    def _send_message(self, message: Message):
        """Sends message via communicator"""
        message = {
            "message_type": message.message_type.value,
            "device_type": message.device_type.value,
            "device_id": message.device_id,
            "value": message.value
        }

        ok, msg = self.communicator.send(message)
        return ok, msg

    # TODO: return type
    def _on_communication_event(self, name: str, value, delay: float):
        """Triggers on receiving an event from communicator and forwards to target component.
           Status messages are forwarded to listeners.
        """
        # print(f"_on_communication_event name: {name} value: {value}")
        if name == "status":
            for cb in list(self._listeners):
                cb(name, str(value))
            if value == "connected":
                self._initialize(delay)
        elif name == "message":
            try:
                message_type = value.get("message_type")
                device_type = value.get("device_type")
                device_id = value.get("device_id")
                device_value = value.get("value")

                message = Message(
                    message_type=MessageType(message_type),
                    device_type=DeviceType(device_type),
                    device_id=device_id,
                    value=device_value
                )

                ok, msg = self.command(message)

            except Exception as exc:
                # TODO: handle exception
                print("Layout._on_communication_event exception:")
                print(str(exc))

    def _on_component_event(self, message: Message) -> Tuple[bool, str]:
        """Handles component events, such as value changes.
           Notifies listeners.
        """
        # print(f"_on_component_event message received: {message}")
        if message.device_type == DeviceType.TARGET_VOLTAGE and message.message_type == MessageType.SET or \
           message.device_type == DeviceType.POINT_DIRECTION and message.message_type == MessageType.SET:
            ok, msg = self._send_message(message)
            if not ok:
                return False, msg

        for cb in list(self._listeners):
            try:
                cb("component", message)
            except Exception as exc:
                # TODO: handle exception
                print("Layout._on_component_event exception:")
                print(str(exc))

        return True, ""


class Track:
    """Encapsulates track voltage control.
    """

    def __init__(self, id: int, cb: Callback, command: Callback, feeder_segment_id: int, segments_data: list = None):
        self.id = id
        self._target_voltage = 0
        self._actual_voltage = 0
        self._cb = cb
        self._command = command
        self._segments_data = segments_data
        self._feeder_segment_id = feeder_segment_id

    def electrified_segments(self) -> list[int]:
        segments: list[int] = []
        try:
            segments.append(self._feeder_segment_id)
            for direction_segments in self._segments_data:
                segments = segments + self._path(direction_segments)
            return segments
        except Exception as exc:
            print(f"track.electrified_segments exc: {str(exc)}")

    def _path(self, segments: list) -> list[int]:
        path_segments: list[int] = []
        try:
            for segment in segments:
                if isinstance(segment, int):
                    path_segments.append(segment)
                else:
                    point_id = segment.get("point_id")
                    message = Message(
                        message_type=MessageType.QUERY,
                        device_type=DeviceType.POINT_DIRECTION,
                        device_id=point_id,
                        value=0
                    )
                    ok, value = self._command(message)
                    if not ok:
                        print(f"Track._path error: {value}")
                        return []
                    direction = int(value)
                    path_segments = path_segments + self._path(segment["direction_segments"][direction])
            return path_segments
        except Exception as exc:
            print(f"Track._path exception: {str(exc)}")

    @property
    def actual_direction(self):
        if self._actual_voltage == 0:
            return 0
        if self._actual_voltage > 0:
            return 1
        return -1

    @property
    def target_voltage(self):
        return self._target_voltage

    @property
    def actual_voltage(self):
        return self._actual_voltage

    def set_voltage(self, voltage: int) -> Tuple[bool, str]:
        if (voltage > 0 and (self._target_voltage < 0 or self._actual_voltage < 0)) or \
                (voltage < 0 and (self._target_voltage > 0 or self._actual_voltage > 0)):
            return False, "Must be stopped before changing directions"

        try:
            self._target_voltage = voltage
            message = Message(
                message_type=MessageType.SET,
                device_type=DeviceType.TARGET_VOLTAGE,
                device_id=self.id,
                value=self._target_voltage
            )
            ok, msg = self._cb(message)
            return ok, msg
        except Exception as e:
            return False, str(e)

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message.message_type == MessageType.SET and message.device_type == DeviceType.ACTUAL_VOLTAGE:
            self._actual_voltage = message.value
            return self._cb(message)

        if message.message_type == MessageType.SET and message.device_type == DeviceType.TARGET_VOLTAGE:
            return self.set_voltage(message.value)

        if message.message_type == MessageType.QUERY and message.device_type == DeviceType.ACTUAL_VOLTAGE:
            return True, str(self._actual_voltage)

        return False, "Unknown message"


class Block:
    """A block that is either occupied or not occupied
    """

    def __init__(self, id: int, occupied: bool, cb: Callback):
        self.id = id
        self._occupied = occupied
        self._cb = cb

    @property
    def occupied(self):
        return self._occupied

    @occupied.setter
    def occupied(self, value: bool):
        if self._occupied != value:
            self._occupied = value
            message: Message = Message(
                message_type=MessageType.SET,
                device_type=DeviceType.BLOCK,
                device_id=self.id,
                value=int(self._occupied)
            )
            self._cb(message)

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message.message_type == MessageType.QUERY and message.device_type == DeviceType.BLOCK:
            return True, str(int(self.occupied))
        return False, "Unknown message"


class Sensor:
    """Sensor that detects train presence
    """

    def __init__(self, id: int, track: Track, block_f: Block, block_r: Block, cb: Callback, diagram_data: dict = None):
        self.id = id
        self._track = track
        self._block_f: Block = block_f
        self._block_r: Block = block_r
        self._cb = cb
        self.diagram_data = diagram_data
        self._on: bool = False
        self.ON_THRESHOLD = 1

    @property
    def on(self):
        return self._on

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message.message_type == MessageType.SET and message.device_type == DeviceType.SENSOR:
            if message.value >= self.ON_THRESHOLD:
                ok, msg = self._detect_on()
                if ok:
                    return self._cb(message)
                else:
                    return False, msg
            else:
                ok, msg = self._detect_off()
                if ok:
                    return self._cb(message)
                else:
                    return False, msg
        elif message.message_type == MessageType.QUERY and message.device_type == DeviceType.SENSOR:
            return True, int(self.on)
        return False, "Unknown message"

    def _detect_on(self) -> Tuple[bool, str]:
        if self._on:
            return False, "Already on"
        self._on = True
        self._block_f.occupied = True
        self._block_r.occupied = True
        return True, ""

    def _detect_off(self) -> Tuple[bool, str]:
        if not self._on:
            return False, "Already off"
        self._on = False
        if self._track.actual_direction == 1:
            self._block_r.occupied = False
            self._block_f.occupied = True
        elif self._track.actual_direction == -1:
            self._block_f.occupied = False
            self._block_r.occupied = True
        return True, ""


class SpeedTrap:
    def __init__(self, id: int, track_id: int, sensor_1_id: int, sensor_2_id: int, distance: float, cb: Callback):
        self.id = id
        self.track_id = track_id
        self._sensor_1_id = sensor_1_id
        self._sensor_2_id = sensor_2_id
        self._distance = distance
        self._cb = cb
        self._last_sensor_1_event_time = -1
        self._last_sensor_2_event_time = -1
        self._last_speed = 0

    def process_message(self, message: Message) -> Tuple[bool, str]:
        return False, ""

    @property
    def last_speed(self):
        return self._last_speed

    def receive_component_event(self, name: str, value: object):
        if name != "component":
            return
        message: Message = value
        if message.device_type == DeviceType.SENSOR and message.message_type == MessageType.SET and message.value == 1:
            event_time = int(monotonic() * 1000)
            if message.device_id == self._sensor_2_id:
                self._last_sensor_2_event_time = event_time
                if self._last_sensor_1_event_time > 0:
                    elapsed_time = self._last_sensor_2_event_time - self._last_sensor_1_event_time
                    self._last_speed = (self._distance / elapsed_time) * 1000 # per second
                    cb_message = Message(
                        message_type=MessageType.SET,
                        device_type=DeviceType.SPEED,
                        device_id=self.id,
                        value=int(self._last_speed)
                    )
                    self._cb(cb_message)
            if message.device_id == self._sensor_1_id:
                self._last_sensor_1_event_time = event_time


class Point:
    def __init__(self, point_data: dict, layout: Layout, cb: Callback):
        self.id = point_data.get("id")
        self._cb = cb
        self._direction: int = point_data.get("initial_direction")
        self._direction_segments: list[int] = []
        self._layout = layout

        directions_data: list = point_data.get("direction_segments")
        for direction in directions_data:
            self._direction_segments.append(direction)

    @property
    def direction(self):
        return self._direction

    @property
    def direction_segments(self):
        return self._direction_segments

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message.device_type == DeviceType.POINT_DIRECTION and message.device_id == self.id:
            if message.message_type == MessageType.SET:
                if self._direction != message.value:
                    electrified_segments = self._layout.electrified_segments()
                    for track_id in electrified_segments:
                        if self._direction_segments[self._direction] in electrified_segments[track_id] or \
                           self._direction_segments[message.value] in electrified_segments[track_id]:
                            voltage_query = Message(
                                message_type=MessageType.QUERY,
                                device_type=DeviceType.ACTUAL_VOLTAGE,
                                device_id=track_id,
                                value=0
                            )
                            ok, msg = self._layout.command(voltage_query)
                            if ok:
                                track_voltage = int(msg)
                                if track_voltage != 0:
                                    return False, "Track voltage is not 0"
                            else:
                                print(f"Failed to get track voltage: {msg}")
                                return False, msg
                self._direction = message.value
                return self._cb(message)
            elif message.message_type == MessageType.QUERY:
                return True, str(self._direction)

        return False, f"Point.process_messageUnknown did not process: {message}"
