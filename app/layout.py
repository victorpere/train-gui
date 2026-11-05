"""Layout definition: the data model shared by the layout editor and the railway control code."""

CURVE_EXTENTS = (15, 30, 45, 90, 180)  # allowed arc sizes in degrees, either direction
MAX_DEVICE_ID = 15  # the serial protocol packs device ids into 4 bits


def new_layout() -> dict:
    return {
        "name": "New layout",
        "description": "",
        "scale": 150.0,
        "nodes": [],
        "segments": [],
        "insulated_joints": [],
        "tracks": [],
        "blocks": [],
        "sensors": [],
        "points": [],
        "speed_traps": [],
    }


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
