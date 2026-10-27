from time import monotonic, sleep
from pydantic import BaseModel
from typing import List, Tuple, Protocol, overload
from enum import Enum
from communication import Communicator
from diagram_helper import CURVE_EXTENTS


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
    POINT_DIRECTION_SKIP_CHECK = 12


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


def derive_blocks(segment_nodes: dict[int, tuple], sensor_nodes: set) -> dict[int, list[int]]:
    """Groups segments into blocks: segments joined at a node without a sensor share a block.
    A block is identified by its lowest segment id."""
    node_segments: dict[int, list[int]] = {}
    for segment_id, nodes in segment_nodes.items():
        for node in nodes:
            node_segments.setdefault(node, []).append(segment_id)

    blocks: dict[int, list[int]] = {}
    seen: set = set()
    for start in sorted(segment_nodes):
        if start in seen:
            continue
        members = [start]
        seen.add(start)
        for segment_id in members:
            for node in segment_nodes[segment_id]:
                if node in sensor_nodes:
                    continue
                for other_id in node_segments[node]:
                    if other_id not in seen:
                        seen.add(other_id)
                        members.append(other_id)
        blocks[start] = sorted(members)
    return blocks


def validate_layout(layout_data: dict) -> list[str]:
    """Returns a list of problems found in a layout definition (empty if valid)"""
    errors: list[str] = []

    def collect_ids(label: str, items: list) -> set:
        ids = set()
        for item in items:
            item_id = item.get("id")
            if not isinstance(item_id, int):
                errors.append(f"{label}: missing or non-integer id in {item}")
            elif item_id in ids:
                errors.append(f"{label}: duplicate id {item_id}")
            else:
                ids.add(item_id)
        return ids

    if "diagram" in layout_data:
        errors.append("diagram: no longer supported, define nodes (with x and y) and segments at the layout root")

    nodes = layout_data.get("nodes", [])
    node_ids = collect_ids("nodes", nodes)
    node_at: dict[tuple, int] = {}
    for node in nodes:
        x, y = node.get("x"), node.get("y")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (x, y)):
            errors.append(f"node {node.get('id')}: x and y must be numbers")
        elif node_at.setdefault((x, y), node.get("id")) != node.get("id"):
            errors.append(f"node {node.get('id')}: same position as node {node_at[(x, y)]}")

    segments = layout_data.get("segments", [])
    segment_ids = collect_ids("segments", segments)
    segment_nodes: dict[int, tuple] = {}
    for segment in segments:
        where = f"segment {segment.get('id')}"
        ends = (segment.get("from"), segment.get("to"))
        if not all(isinstance(end, int) for end in ends):
            errors.append(f"{where}: from and to must be integer node ids")
        elif any(end not in node_ids for end in ends):
            errors.append(f"{where}: unknown node {next(end for end in ends if end not in node_ids)}")
        elif ends[0] == ends[1]:
            errors.append(f"{where}: from and to must be different nodes")
        else:
            segment_nodes[segment.get("id")] = ends

        shape, extent = segment.get("shape", "straight"), segment.get("extent")
        if shape == "straight":
            if extent is not None:
                errors.append(f"{where}: extent only applies to curves")
        elif shape == "curve":
            if not isinstance(extent, (int, float)) or abs(extent) not in CURVE_EXTENTS:
                errors.append(f"{where}: curve extent must be one of {list(CURVE_EXTENTS)} "
                              f"(negative for clockwise), found {extent}")
        else:
            errors.append(f"{where}: shape must be straight or curve, found {shape}")

    track_ids = collect_ids("tracks", layout_data.get("tracks", []))
    collect_ids("blocks", layout_data.get("blocks", []))
    sensor_ids = collect_ids("sensors", layout_data.get("sensors", []))
    collect_ids("speed_traps", layout_data.get("speed_traps", []))
    points = layout_data.get("points", [])
    collect_ids("points", points)

    sensor_nodes: dict[int, int] = {}
    for sensor in layout_data.get("sensors", []):
        where = f"sensor {sensor.get('id')}"
        if "diagram" in sensor:
            errors.append(f"{where}: diagram location is no longer supported, define the sensor's node")
        node = sensor.get("node")
        if node not in node_ids:
            errors.append(f"{where}: unknown node {node}")
        elif node in sensor_nodes.values():
            errors.append(f"{where}: node {node} already has a sensor")
        else:
            sensor_nodes[sensor.get("id")] = node

    block_ids = derive_blocks(segment_nodes, set(sensor_nodes.values()))
    for block in layout_data.get("blocks", []):
        if block.get("id") not in block_ids:
            errors.append(f"block {block.get('id')}: no such block, blocks are identified by their "
                          f"lowest segment id (valid ids: {sorted(block_ids)})")

    for joint in layout_data.get("insulated_joints", []):
        node, joined = joint.get("node"), joint.get("segments")
        where = f"insulated joint at node {node}"
        if not isinstance(joined, list) or len(joined) != 2 or joined[0] == joined[1]:
            errors.append(f"{where}: segments must list 2 different segments")
        elif any(node not in segment_nodes.get(segment_id, ()) for segment_id in joined):
            errors.append(f"{where}: segments {joined} must both touch the node")

    point_nodes: set = set()
    for point in points:
        where = f"point {point.get('id')}"
        node = point.get("node")
        if node in point_nodes:
            errors.append(f"{where}: node {node} already has a point")
        point_nodes.add(node)
        if point.get("initial_direction") not in (0, 1):
            errors.append(f"{where}: initial_direction must be 0 or 1")
        routes = point.get("direction_segments")
        if not isinstance(routes, list) or len(routes) != 2 or routes[0] == routes[1]:
            errors.append(f"{where}: direction_segments must list 2 different segments")
            continue
        unknown = [route for route in routes if route not in segment_ids]
        for route in unknown:
            errors.append(f"{where}: unknown segment {route}")
        if unknown:
            continue
        touching = [segment_id for segment_id, nodes in segment_nodes.items() if node in nodes]
        if any(route not in touching for route in routes):
            errors.append(f"{where}: direction_segments {routes} must both touch node {node}")
        elif len(touching) != 3:
            errors.append(f"{where}: node {node} must join exactly 3 segments, found {len(touching)}")

    for track in layout_data.get("tracks", []):
        where = f"track {track.get('id')}"
        if "segments" in track:
            errors.append(f"{where}: nested segments are no longer supported, define top-level segments")
        feeder = track.get("feeder_segment_id")
        if feeder is not None and feeder not in segment_ids:
            errors.append(f"{where}: unknown feeder segment {feeder}")

    for trap in layout_data.get("speed_traps", []):
        where = f"speed trap {trap.get('id')}"
        if trap.get("track_id") not in track_ids:
            errors.append(f"{where}: unknown track {trap.get('track_id')}")
        for key in ("sensor_1_id", "sensor_2_id"):
            if trap.get(key) not in sensor_ids:
                errors.append(f"{where}: unknown sensor {trap.get(key)} in {key}")
        distance = trap.get("distance")
        if not isinstance(distance, (int, float)) or distance <= 0:
            errors.append(f"{where}: distance must be a positive number")

    return errors


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
        self._speed_trap_listeners: List[Callback] = []
        self.segments: dict[int, dict] = {}
        self._node_segments: dict[int, list[int]] = {}
        self._segment_nodes: dict[int, tuple[int, int]] = {}
        self._points_by_node: dict[int, Point] = {}
        self._insulated_joints: set[tuple[int, frozenset]] = set()
        self.node_locations: dict[int, tuple] = {}
        self._sensor_blocks: dict[int, list[int]] = {}
        # Block a train is leaving while its sensor is on, freed when the sensor goes off
        self._leaving_block: dict[int, set[int]] = {}
        self._segment_blocks: dict[int, int] = {}
        # Lets points switch without a serial connection
        self.test_mode = False

    def load(self, layout_data: dict) -> Tuple[bool, str]:
        """Creates layout and components from a dictionary definition"""
        try:
            errors = validate_layout(layout_data)
            if errors:
                msg = "; ".join(errors)
                print(f"Invalid layout: {msg}")
                return False, msg

            for cb in self._speed_trap_listeners:
                self._listeners.remove(cb)
            self._speed_trap_listeners.clear()
            self.name = layout_data.get("name", "n/a")
            self.description = layout_data.get("description", "n/a")
            self.scale: float = layout_data.get("scale", 0)
            tracks = layout_data.get("tracks", [])
            blocks = layout_data.get("blocks", [])
            sensors = layout_data.get("sensors", [])
            speed_traps = layout_data.get("speed_traps", [])
            points = layout_data.get("points", [])

            for device_type_name, _ in DeviceType.__members__.items():
                """Add all device types to components"""
                self.components[device_type_name] = dict()

            for track_data in tracks:
                track = Track(track_data.get("id"), self._on_component_event,
                              feeder_segment_id=track_data.get("feeder_segment_id"))
                self.components[DeviceType.TARGET_VOLTAGE.name][track.id] = track
                self.components[DeviceType.ACTUAL_VOLTAGE.name][track.id] = track

            for sensor_data in sensors:
                sensor = Sensor(sensor_data.get("id"), self._on_component_event, node=sensor_data.get("node"))
                self.components[DeviceType.SENSOR.name][sensor.id] = sensor

            for speed_trap_data in speed_traps:
                speed_trap = SpeedTrap(id=speed_trap_data.get("id"),
                                       track_id=speed_trap_data.get("track_id"),
                                       sensor_1_id=speed_trap_data.get("sensor_1_id"),
                                       sensor_2_id=speed_trap_data.get("sensor_2_id"),
                                       distance=speed_trap_data.get("distance"),
                                       cb=self._on_component_event)
                self.add_listener(speed_trap.receive_component_event)
                self._speed_trap_listeners.append(speed_trap.receive_component_event)
                self.components[DeviceType.SPEED.name][speed_trap.id] = speed_trap

            self.segments = {s["id"]: s for s in layout_data.get("segments", [])}
            self._segment_nodes = {s_id: (s["from"], s["to"]) for s_id, s in self.segments.items()}
            self._node_segments = {}
            for segment_id, nodes in self._segment_nodes.items():
                for node in nodes:
                    self._node_segments.setdefault(node, []).append(segment_id)

            self._insulated_joints = {(joint["node"], frozenset(joint["segments"]))
                                      for joint in layout_data.get("insulated_joints", [])}

            self.node_locations = {n["id"]: (n["x"], n["y"]) for n in layout_data.get("nodes", [])}

            sensor_nodes = {sensor.node: sensor.id for sensor in self.components[DeviceType.SENSOR.name].values()}
            initially_occupied = {b["id"]: b.get("occupied", False) for b in blocks}
            for block_id, segment_ids in derive_blocks(self._segment_nodes, set(sensor_nodes)).items():
                touched_nodes = {node for segment_id in segment_ids for node in self._segment_nodes[segment_id]}
                block = Block(block_id, initially_occupied.get(block_id, False), self._on_component_event,
                              segment_ids=segment_ids,
                              sensor_ids=sorted(sensor_nodes[node] for node in touched_nodes if node in sensor_nodes))
                self.components[DeviceType.BLOCK.name][block.id] = block

            self._sensor_blocks = {}
            self._leaving_block = {}
            self._segment_blocks = {}
            for block in self.components[DeviceType.BLOCK.name].values():
                for segment_id in block.segment_ids:
                    self._segment_blocks[segment_id] = block.id
                for sensor_id in block.sensor_ids:
                    self._sensor_blocks.setdefault(sensor_id, []).append(block.id)

            self._points_by_node = {}
            for point_data in points:
                point = Point(point_data, layout=self, cb=self._on_component_event)
                self.components[DeviceType.POINT_DIRECTION.name][point.id] = point
                self.components[DeviceType.POINT_DIRECTION_SKIP_CHECK.name][point.id] = point
                self._points_by_node[point.node] = point

            return True, ""

        except Exception as exc:
            print(f"Failed to load layout {str(exc)}")
            return False, str(exc)

    def add_listener(self, cb: Callback):
        """Add a listener to layout component events"""
        self._listeners.append(cb)

    @property
    def insulated_joint_nodes(self) -> set[int]:
        return {node for node, _ in self._insulated_joints}

    def node_location(self, node: int) -> tuple | None:
        """Diagram coordinates of a node"""
        return self.node_locations.get(node)

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
            segments[track.id] = self._connected_segments(track.feeder_segment_id)
        return segments

    def _connected_segments(self, start_segment_id: int) -> list[int]:
        """Segments reachable from a segment, passing through points only along their active route"""
        if start_segment_id not in self._segment_nodes:
            return []
        reachable = [start_segment_id]
        for segment_id in reachable:
            for node in self._segment_nodes[segment_id]:
                for other_id in self._node_segments[node]:
                    if other_id not in reachable and self._joined_at_node(node, segment_id, other_id):
                        reachable.append(other_id)
        return reachable

    def _joined_at_node(self, node: int, segment_id: int, other_id: int) -> bool:
        if (node, frozenset((segment_id, other_id))) in self._insulated_joints:
            return False
        return self._point_allows(node, segment_id, other_id)

    def _point_allows(self, node: int, segment_id: int, other_id: int) -> bool:
        """Whether a point (if any) at the node connects the two segments in its current direction"""
        point = self._points_by_node.get(node)
        if point is None:
            return True
        routes = point.direction_segments
        stem_id = next(s for s in self._node_segments[node] if s not in routes)
        return {segment_id, other_id} == {stem_id, routes[point.direction]}

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
        if message.message_type == MessageType.SET and \
            (message.device_type == DeviceType.TARGET_VOLTAGE or \
             message.device_type == DeviceType.POINT_DIRECTION or \
             message.device_type == DeviceType.POINT_DIRECTION_SKIP_CHECK):
            is_point = message.device_type != DeviceType.TARGET_VOLTAGE
            if not (is_point and self.test_mode and not self.communicator.is_connected):
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

        if message.message_type == MessageType.SET and message.device_type == DeviceType.SENSOR:
            self._update_blocks_from_sensor(message.device_id)

        return True, ""

    def _update_blocks_from_sensor(self, sensor_id: int):
        """A train over a sensor occupies the blocks on both sides of it. When the sensor goes off,
        the block the train came from is freed. The track voltage gives the direction of travel;
        without it, the block the train came from is only known if it was the only one occupied."""
        blocks: dict[int, Block] = self.components[DeviceType.BLOCK.name]
        adjacent_ids = set(self._sensor_blocks.get(sensor_id, []))
        sensor: Sensor = self.components[DeviceType.SENSOR.name][sensor_id]
        if sensor.on:
            travel = self._blocks_along_travel(sensor.node)
            if travel is None:
                occupied = {block_id for block_id in adjacent_ids if blocks[block_id].occupied}
                leaving = occupied if len(adjacent_ids) > 1 and len(occupied) == 1 else set()
                entering = adjacent_ids - leaving
            else:
                entering, leaving = travel
            self._leaving_block[sensor_id] = leaving - entering
            for block_id in entering | leaving:
                blocks[block_id].occupied = True
        else:
            for block_id in self._leaving_block.pop(sensor_id, set()):
                blocks[block_id].occupied = False

    def _blocks_along_travel(self, node: int) -> tuple[set[int], set[int]] | None:
        """(entering, leaving) block ids for a train passing the node, or None if its direction is unknown"""
        touching = set(self._node_segments.get(node, []))
        directions = set()
        for track_id, segment_ids in self.electrified_segments().items():
            track: Track = self.components[DeviceType.TARGET_VOLTAGE.name][track_id]
            if track.travel_direction != 0 and touching.intersection(segment_ids):
                directions.add(track.travel_direction)
        if len(directions) != 1:
            return None

        arrive_at = 1 if directions.pop() > 0 else 0
        arriving = [s for s in touching if self._segment_nodes[s][arrive_at] == node]
        departing = [s for s in touching if self._segment_nodes[s][1 - arrive_at] == node]
        passes = [(a, d) for a in arriving for d in departing if self._point_allows(node, a, d)]
        if not passes:
            return None
        return {self._segment_blocks[d] for _, d in passes}, {self._segment_blocks[a] for a, _ in passes}


class Track:
    """Encapsulates track voltage control.
    """

    def __init__(self, id: int, cb: Callback, feeder_segment_id: int = None):
        self.id = id
        self._target_voltage = 0
        self._actual_voltage = 0
        self._cb = cb
        self.feeder_segment_id = feeder_segment_id
        # Positive voltage moves trains along segments from -> to; kept while coasting to a stop
        self.travel_direction = 0

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
            if voltage != 0:
                self.travel_direction = 1 if voltage > 0 else -1
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
            if message.value != 0:
                self.travel_direction = 1 if message.value > 0 else -1
            return self._cb(message)

        if message.message_type == MessageType.SET and message.device_type == DeviceType.TARGET_VOLTAGE:
            return self.set_voltage(message.value)

        if message.message_type == MessageType.QUERY and message.device_type == DeviceType.ACTUAL_VOLTAGE:
            return True, str(self._actual_voltage)

        return False, "Unknown message"


class Block:
    """A block that is either occupied or not occupied
    """

    def __init__(self, id: int, occupied: bool, cb: Callback, segment_ids: list[int] = (), sensor_ids: list[int] = ()):
        self.id = id
        self._occupied = occupied
        self._cb = cb
        self.segment_ids = list(segment_ids)
        # Sensors located at the block's boundary nodes
        self.sensor_ids = list(sensor_ids)

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

    def __init__(self, id: int, cb: Callback, node: int = None):
        self.id = id
        self._cb = cb
        self.node = node
        self._on: bool = False
        self.ON_THRESHOLD = 1

    @property
    def on(self):
        return self._on

    def process_message(self, message: Message) -> Tuple[bool, str]:
        if message.message_type == MessageType.SET and message.device_type == DeviceType.SENSOR:
            if message.value >= self.ON_THRESHOLD:
                if self._on:
                    return False, f"Sensonf {self.id} is already on"
                self._on = True
                return self._cb(message)
            else:
                if not self._on:
                    return False, f"Sensor {self.id} is lready off"
                self._on = False
                return self._cb(message)
        elif message.message_type == MessageType.QUERY and message.device_type == DeviceType.SENSOR:
            return True, int(self.on)
        return False, f"Sensor {self.id}: unknown message"


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
        self.node: int = point_data.get("node")
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
        if (message.device_type == DeviceType.POINT_DIRECTION or message.device_type == DeviceType.POINT_DIRECTION_SKIP_CHECK) \
            and message.device_id == self.id:
            if message.message_type == MessageType.SET:
                if message.device_type != DeviceType.POINT_DIRECTION_SKIP_CHECK and self._direction != message.value:
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
