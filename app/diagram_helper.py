import math


def curve_to_tkinter_arc(curve: dict) -> dict:
    """Convert a custom arc definition into tkinter Canvas.create_arc parameters.

    The custom definition describes an arc by the two points where it starts
    and ends, an unsigned start angle/extent (tkinter degree convention, 0 at
    3 o'clock), and a direction of travel from start_point to end_point.

    Expected input keys:
        start_point: {"x": float, "y": float}
        end_point: {"x": float, "y": float}
        start: float (degrees)
        extent: float (degrees, signed magnitude)

    Returns a dict with keys x1, y1, x2, y2, start, extent, matching the
    arguments expected by tkinter's Canvas.create_arc.
    """
    start_point = curve["start_point"]
    end_point = curve["end_point"]
    start_angle = curve["start_angle"]
    extent = curve["extent"]

    # The chord between the two points, combined with the angle it subtends
    # (the extent), is enough to solve for the circle's radius and center.
    chord_length = math.hypot(end_point["x"] - start_point["x"], end_point["y"] - start_point["y"])
    sin_half_extent = math.sin(math.radians(extent) / 2)
    if sin_half_extent == 0:
        raise ValueError("Arc extent must not be a multiple of 360 degrees")

    radius = chord_length / (2 * abs(sin_half_extent))
    start_angle_rad = math.radians(start_angle)
    center_x = start_point["x"] - radius * math.cos(start_angle_rad)
    center_y = start_point["y"] - radius * math.sin(start_angle_rad)

    return {
        "x1": center_x - radius,
        "y1": center_y - radius,
        "x2": center_x + radius,
        "y2": center_y + radius,
        "start": start_angle,
        "extent": extent,
    }
