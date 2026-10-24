import math

CURVE_EXTENTS = (15, 30, 45, 90, 180)  # allowed arc sizes in degrees, either direction


def curve_geometry(start_point, end_point, extent: float) -> dict:
    """Circle of the arc running from start_point to end_point through `extent` degrees.
    A positive extent is counter-clockwise on the screen. Returns the screen centre, the radius and
    the tkinter start angle (degrees, counter-clockwise from 3 o'clock).
    """
    if not extent or abs(extent) >= 360:
        raise ValueError("extent must be non-zero and less than 360 degrees")
    # Work with y pointing up, like the tkinter angles
    x1, y1 = start_point[0], -start_point[1]
    x2, y2 = end_point[0], -end_point[1]
    chord = math.hypot(x2 - x1, y2 - y1)
    if chord == 0:
        raise ValueError("a curve needs two distinct end points")
    half = math.radians(abs(extent)) / 2
    radius = chord / (2 * math.sin(half))
    ux, uy = (x2 - x1) / chord, (y2 - y1) / chord
    # The centre is left of the chord for counter-clockwise arcs and right of it for clockwise ones
    offset = math.copysign(radius * math.cos(half), extent)
    cx = (x1 + x2) / 2 - uy * offset
    cy = (y1 + y2) / 2 + ux * offset
    return {"center": (cx, -cy), "radius": radius, "start_angle": math.degrees(math.atan2(y1 - cy, x1 - cx))}


def curve_to_line_points(start_point, end_point, extent: float, step_degrees=15):
    """Flat x,y list of points along a curve, for canvas.create_line(..., smooth=True)."""
    geometry = curve_geometry(start_point, end_point, extent)
    cx, cy = geometry["center"]
    count = max(3, math.ceil(abs(extent) / step_degrees) + 1)
    points = []
    for i in range(count):
        angle = math.radians(geometry["start_angle"] + extent * i / (count - 1))
        points += [cx + geometry["radius"] * math.cos(angle), cy - geometry["radius"] * math.sin(angle)]
    return points


def segment_line_points(segment: dict, node_positions: dict) -> list:
    """Flat x,y list of points along a layout segment, drawn from its `from` node to its `to` node."""
    start, end = node_positions[segment["from"]], node_positions[segment["to"]]
    if segment.get("shape", "straight") == "curve":
        return curve_to_line_points(start, end, segment["extent"])
    return [*start, *end]


def feeder_symbol(cx:float, cy:float):
    x0 = cx + 1
    y0 = cy - 10

    x1 = cx
    y1 = cy - 2

    x2 = cx + 4
    y2 = cy - 2

    x3 = cx - 1
    y3 = cy + 10

    x4 = cx
    y4 = cy + 2

    x5 = cx - 4
    y5 = cy + 2

    return x0, y0, x1, y1, x2, y2, x3, y3, x4, y4, x5, y5


def isolator_symbol(cx: float, cy: float):
    p0 = cx, cy - 2
    p1 = cx + 4, cy - 6
    p2 = cx + 6, cy - 4
    p3 = cx + 2, cy
    p4 = cx + 6, cy + 4
    p5 = cx + 4, cy + 6
    p6 = cx, cy + 2
    p7 = cx - 4, cy + 6
    p8 = cx - 6, cy + 4
    p9 = cx - 2, cy
    p10 = cx - 6, cy - 4
    p11 = cx - 4, cy - 6

    return p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11


def round_symbol(cx: float, cy: float, diameter: float):
    radius = diameter / 2
    x1 = cx - radius
    y1 = cy - radius
    x2 = cx + radius
    y2 = cy + radius
    return x1, y1, x2, y2


def center_point(segment: dict, node_positions: dict):
    """Midpoint between a segment's end nodes"""
    start, end = node_positions[segment["from"]], node_positions[segment["to"]]
    return (start[0] + end[0]) / 2, (start[1] + end[1]) / 2