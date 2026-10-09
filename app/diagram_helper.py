import math


def curve_to_tkinter_arc(arc):
    """Convert a {start_point, end_point, start_angle, extent} arc definition into
    tkinter Canvas.create_arc bounding-box/start/extent parameters.
    """
    x1, y1 = arc["start_point"][0], arc["start_point"][1]
    x2, y2 = arc["end_point"][0], arc["end_point"][1]
    start_angle = arc["start_angle"]
    extent = arc["extent"]

    a1 = math.radians(start_angle)
    a2 = math.radians(start_angle + extent)
    cos1, sin1 = math.cos(a1), math.sin(a1)
    cos2, sin2 = math.cos(a2), math.sin(a2)

    # Solve x = cx + rx*cos(theta), y = cy - ry*sin(theta) for each axis independently,
    # since the two points don't necessarily lie on a circle (rx may differ from ry).
    dcos = cos1 - cos2
    dsin = sin2 - sin1
    rx = (x1 - x2) / dcos if not math.isclose(dcos, 0, abs_tol=1e-9) else None
    ry = (y1 - y2) / dsin if not math.isclose(dsin, 0, abs_tol=1e-9) else None

    if rx is None and ry is None:
        raise ValueError("extent must not be a multiple of 360 degrees")
    # If one axis doesn't constrain its radius (points share that coordinate), mirror the other.
    rx = ry if rx is None else rx
    ry = rx if ry is None else ry

    cx = x1 - rx * cos1
    cy = y1 + ry * sin1

    return {
        "x1": cx - rx,
        "y1": cy - ry,
        "x2": cx + rx,
        "y2": cy + ry,
        "start": start_angle,
        "extent": extent,
    }


def mid_point(segment):
    x = (segment["start_point"][0] + segment["end_point"][0]) / 2
    y = (segment["start_point"][1] + segment["end_point"][1]) / 2
    return x, y


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


def center_point(segment: dict):
    segment_center_x = (segment["start_point"][0] + segment["end_point"][0]) / 2
    segment_center_y = (segment["start_point"][1] + segment["end_point"][1]) / 2
    return segment_center_x, segment_center_y