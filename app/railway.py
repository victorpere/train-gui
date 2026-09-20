from typing import List, Tuple, Protocol, TypedDict, overload
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
    POINT = 4
    SIGNAL = 5


class Message(TypedDict):
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
        self.components: dict = {}
        self.name = ""
        self.description = ""
        self._listeners: List[Callback] = []

    def load(self, layout_data: dict) -> Tuple[bool, str]:
        """Creates layout and components from a dictionary definition"""
        try:
            self.name = layout_data.get("name", "n/a")
            self.description = layout_data.get("description", "n/a")
            self.length: float = layout_data.get("length", 0)
            self.scale: float = layout_data.get("scale", 0)
            tracks = layout_data.get("tracks", [])
            blocks = layout_data.get("blocks", [])
            sensors = layout_data.get("sensors", [])

            for device_type_name, _ in DeviceType.__members__.items():
                """Add all device types to components"""
                self.components[device_type_name] = dict()

            for track_data in tracks:
                track = Track(track_data.get("id"), self._on_component_event)
                self.components[DeviceType.TARGET_VOLTAGE.name][track.id] = track
                self.components[DeviceType.ACTUAL_VOLTAGE.name][track.id] = track

            for block_data in blocks:
                block = Block(block_data.get("id"), block_data.get("occupied", False), self._on_component_event)
                self.components[DeviceType.BLOCK.name][block.id] = block

            for sensor_data in sensors:
                track = self.components[DeviceType.TARGET_VOLTAGE.name][sensor_data.get("track_id")]
                block_f = self.components[DeviceType.BLOCK.name][sensor_data.get("block_f_id")]
                block_r = self.components[DeviceType.BLOCK.name][sensor_data.get("block_r_id")]
                sensor = Sensor(sensor_data.get("id"), track, block_f, block_r, self._on_component_event)
                self.components[DeviceType.SENSOR.name][sensor.id] = sensor

            return True, ""

        except Exception as exc:
            print(f"Failed to load layout {str(exc)}")
            return False, str(exc)

    def add_listener(self, cb: Callback):
        """Add a listener to layout component events"""
        self._listeners.append(cb)

    def command(self, message: Message) -> Tuple[bool, str]:
        """Processes command to component"""
        target_type_components: dict = self.components.get(message["device_type"].name)
        target_component: LayoutComponent = target_type_components.get(message["device_id"])

        if target_component == None:
            print(f"device not foud: {message['device_type'].name}:{message['device_id']}")
            return False, "Device not found"
        return target_component.process_message(message)

    def stop_all(self):
        """Sets target voltage to 0 on all tracks"""
        target_voltage_devices: dict = self.components.get(DeviceType.TARGET_VOLTAGE.name)
        for target_voltage_device in target_voltage_devices.values():
            track: Track = target_voltage_device
            ok, msg = track.set_voltage(0)

    def _send_message(self, \
                     message_type: MessageType, \
                     device_type: DeviceType, \
                     device_id: int, \
                     value: int):
        """Sends message via communicator"""
        message = {
            "message_type": message_type.value,
            "device_type": device_type.value,
            "device_id": device_id,
            "value": value
        }

        ok, msg = self.communicator.send(message)
        return ok, msg

    # TODO: return type
    def _on_communication_event(self, name: str, value):
        """Triggers on receiving an event from communicator and forwards to target component.
           Status messages are forwarded to listeners.
        """
        # print(f"_on_communication_event name: {name} value: {value}")
        if name == "status":
            for cb in list(self._listeners):
                cb(name, str(value))
        elif name == "message":
            try:
                message_type = value.get("message_type")
                device_type = value.get("device_type")
                device_id = value.get("device_id")
                device_value = value.get("value")

                message: Message = {
                    "message_type": MessageType(message_type),
                    "device_type": DeviceType(device_type),
                    "device_id": device_id,
                    "value": device_value
                }

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
        cb_message: Tuple[str, object] = None

        if message["device_type"] == DeviceType.TARGET_VOLTAGE and message["message_type"] == MessageType.SET:
            print(f"sending message to communicator: {message['value']}")
            ok, msg = self._send_message(MessageType.SET, DeviceType.TARGET_VOLTAGE, message["device_id"], message["value"])
            print(f"response from communicator: {ok}:{msg}")
            if ok:
                cb_message = "target_voltage", message["value"]
            else:
                return False, msg
        elif message["device_type"] == DeviceType.ACTUAL_VOLTAGE:
            cb_message = "actual_voltage", message["value"]
        elif message["device_type"] == DeviceType.BLOCK:
            cb_message = "block", message["value"]
        elif message["device_type"] == DeviceType.SENSOR:
            cb_message = "sensor", message["value"]
        else:
            return False, "Unknown device"

        for cb in list(self._listeners):
            try:
                cb(cb_message[0], cb_message[1])
            except Exception as exc:
                # TODO: handle exception
                print("Layout._on_component_event exception:")
                print(str(exc))

        return True, ""


class Track:
    """Encapsulates track voltage control.
    """

    def __init__(self, id: int, cb: Callback):
        self.id = id
        self._target_voltage = 0
        self._actual_voltage = 0
        self._cb = cb

    @property
    def actual_direction(self):
        if self._actual_voltage == 0: return 0
        if self._actual_voltage > 0: return 1
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
            message: Message = {
                "message_type": MessageType.SET,
                "device_type": DeviceType.TARGET_VOLTAGE,
                "device_id": self.id,
                "value": self._target_voltage
            }
            ok, msg = self._cb(message)
            return ok, msg
        except Exception as e:
            return False, str(e)

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message["message_type"] == MessageType.SET and message["device_type"] == DeviceType.ACTUAL_VOLTAGE:
            self._actual_voltage = message["value"]
            return self._cb(message)

        if message["message_type"] == MessageType.SET and message["device_type"] == DeviceType.TARGET_VOLTAGE:
            return self.set_voltage(message["value"])

        if message["message_type"] == MessageType.QUERY and message["device_type"] == DeviceType.ACTUAL_VOLTAGE:
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
            message: Message = {
                "message_type": MessageType.SET,
                "device_type": DeviceType.BLOCK,
                "device_id": self.id,
                "value": int(self._occupied)
            }
            self._cb(message)

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message["message_type"] == MessageType.QUERY and message["device_type"] == DeviceType.BLOCK:
            return True, int(self.occupied)
        return False, "Unknown message"


class Sensor:
    """Sensor that detects train presence
    """

    def __init__(self, id: int, track: Track, block_f: Block, block_r: Block, \
                 cb: Callback):
        self.id = id
        self._track = track
        self._block_f: Block = block_f
        self._block_r: Block = block_r
        self._cb = cb
        self._on: bool = False
        self.ON_THRESHOLD = 1

    @property
    def on(self):
        return self._on

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message["message_type"] == MessageType.SET and message["device_type"] == DeviceType.SENSOR:
            if message["value"] >= self.ON_THRESHOLD:
                if self._detect_on():
                    return self._cb(message)
                else:
                    return False, "Already on"
            else:
                if self._detect_off():
                    return self._cb(message)
                else:
                    return False, "Already off"
        elif message["message_type"] == MessageType.QUERY and message["device_type"] == DeviceType.SENSOR:
            return True, int(self.on)
        return False, "Unknown message"
        
    def _detect_on(self) -> bool:
        if self._on: 
            return False
        self._on = True
        self._block_f.occupied = True
        self._block_r.occupied = True
        return True

    def _detect_off(self) -> bool:
        if not self._on:
            return False
        self._on = False
        if self._track.actual_direction == 1:
            self._block_r.occupied = False
            self._block_f.occupied = True
        elif self._track.actual_direction == -1:
            self._block_f.occupied = False
            self._block_r.occupied = True
        return True