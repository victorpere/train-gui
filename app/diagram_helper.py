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
