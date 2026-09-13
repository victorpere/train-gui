
from typing import Callable, List, Optional, Tuple, Protocol, TypedDict
from enum import Enum
from communication import Communicator
from util import encode_message, decode_message


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


class LayoutComponent(Protocol):
    def process_message(self, \
                        message_type: MessageType, \
                        device_type: DeviceType, \
                        value: int) -> bool:
        ...


class Layout:
    def __init__(self, communicator: Communicator):
        self.communicator = communicator
        self.communicator.add_listener(self._on_communication_event)
        self.components: dict = {}
        self.name = ""
        self.description = ""
        self._listeners: List[Callable[[DeviceType, int, int], None]] = []

    def load(self, layout_data: dict) -> Tuple[bool, str]:
        """Creates layout and components from a dictionary definition"""
        try:
            self.name = layout_data.get("name", "n/a")
            self.description = layout_data.get("description", "n/a")
            tracks = layout_data.get("tracks", [])
            blocks = layout_data.get("blocks", [])
            sensors = layout_data.get("sensors", [])

            for track_data in tracks:
                track = Track(track_data.get("id"), self._on_component_event)
                self.components[f"{DeviceType.TARGET_VOLTAGE.value}-{track.id}"] = track
                self.components[f"{DeviceType.ACTUAL_VOLTAGE.value}-{track.id}"] = track

            for block_data in blocks:
                block = Block(block_data.get("id"), block_data.get("occupied", False), self._on_component_event)
                self.components[f"{DeviceType.BLOCK.value}-{block.id}"] = block

            return True, ""

        except Exception as exc:
            print(f"Failed to load layout {str(exc)}")
            return False, str(exc)

    def add_listener(self, cb: Callable[[DeviceType, int, int], None]):
        """Add a listener to layout component events"""
        self._listeners.append(cb)

    def send_message(self, \
                     message_type: MessageType, \
                     device_type: DeviceType, \
                     device_id: int, \
                     value: int):
        # Encodes and sends message via communicator
        message = encode_message(
            message_type=message_type.value,
            device_type=device_type.value,
            device_id=device_id,
            value=value
        )
        # for my_byte in message:
        #     print(f'{my_byte:0>8b}', end=' ')
        # print("\n")

        ok, msg = self.communicator.send(message)
        # TODO: handle send message failure

    def _on_communication_event(self, name, value):
        """Triggers on receiving an event from communicator"""
        try:
            

            target_component: LayoutComponent = self.components.get(f"{device_type}-{device_id}")

            if target_component == None:
                print(f"device does not exist: {device_type}-{device_id}")
                return

            if target_component.process_message(MessageType(message_type), \
                                             DeviceType(device_type), \
                                             value):
                return

        except Exception as exc:
            print(str(exc))

    def _on_component_event(self, device_type, device_id, value):
        """Notifies listeners of layout component event, such as device value changes"""
        for cb in list(self._listeners):
            try:
                cb(DeviceType(device_type), device_id, value)
            except Exception:
                pass


class Track:
    """Encapsulates track voltage control.
    """

    def __init__(self, id: int, cb: Callable[[DeviceType, int, int], None]):
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
        if not self._ser or not getattr(self._ser, "is_open", False):
            return False, "Serial connection not established"

        if (voltage > 0 and (self._target_voltage < 0 or self._actual_voltage < 0)) or \
            (voltage < 0 and (self._target_voltage > 0 or self._actual_voltage > 0)):
            return False, "Must be stopped before changing directions"
        
        try:
            self.communicator.send(MessageType.SET, self.device_type, self.id, voltage)
            self._target_voltage = voltage
            return True, ""
        except Exception as e:
            return False, str(e)

    def process_message(self, \
                        message_type: MessageType, \
                        device_type: DeviceType, \
                        value) -> bool:

        if message_type == MessageType.SET and device_type == DeviceType.ACTUAL_VOLTAGE:
            self._actual_voltage = value
            self._cb(device_type, self.id, value)
            return True

        return False


class Block:
    """A block that is either occupied or not occupied
    """

    def __init__(self, id: int, occupied: bool, cb: Callable[[DeviceType, int, int], None]):
        self.id = id
        self._occupied = occupied
        self._cb = cb

    @property
    def occupied(self):
        return self._occupied

    @occupied.setter
    def occupied(self, value: bool):
        self._occupied = value
        self._cb(DeviceType.BLOCK, self.id, int(value))

    def process_message(self, \
                        message_type: MessageType, \
                        device_type: DeviceType, \
                        value) -> bool:
        return False


class Sensor:
    """For future use
    """

    def __init__(self, id: int, track: Track, block_f: Block, block_r: Block):
        self.id = id
        self._track = track
        self._block_f: Block = block_f
        self._block_r: Block = block_r
        self._on: bool = False

    @property
    def on(self):
        return self._on

    @on.setter
    def on(self, value: bool):
        if self._on == value:
            return

        if value:
            if self._track.actual_direction == 1 and self._block_f.occupied:
                raise Exception
            if self._track.actual_direction == -1 and self._block_r.occupied:
                raise Exception
            self._on = True
            self._block_f.occupied = True
            self._block_r.occupied = True
        else:
            self._on = False
            if self._track.actual_direction == 1:
                self._block_r.occupied = False
                self._block_f.occupied = True
            elif self._track.actual_direction == -1:
                self._block_f.occupied = False
                self._block_r.occupied = True


    def detect_on(self):
        if self._track.actual_direction == 1 and self._block_f.occupied:
            raise Exception
        if self._track.actual_direction == -1 and self._block_r.occupied:
            raise Exception
        self._on = True
        self._block_f.occupied = True
        self._block_r.occupied = True

    def detect_off(self):
        self._on = False
        if self._track.actual_direction == 1:
            self._block_r.occupied = False
            self._block_f.occupied = True
        elif self._track.actual_direction == -1:
            self._block_f.occupied = False
            self._block_r.occupied = True