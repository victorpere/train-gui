"""Layout editor: builds and edits layout definition files in its own window.

Run with: python3 app/layout_editor.py [layout file]
"""
import copy
import math
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import diagram_helper
from railway import derive_blocks, validate_layout
from util import load_canvas_size, load_data_from_file, save_data_to_file

GRID = 10
SNAP_DISTANCE = 8
MAX_DEVICE_ID = 15  # the serial protocol packs device ids into 4 bits
BLOCK_WIDTH = 10
UNOCCUPIED_COLOR = "lightgreen"
OCCUPIED_COLOR = "lightpink"
INITIAL_DIRECTIONS = ["0 (primary route)", "1 (secondary route)"]
TOOL_HINTS = {
    "select": "Click to select, drag a node to move it",
    "straight": "Click the start, then the end of the segment (Esc cancels)",
    "curve": "Click the start, then the end of the curve (Esc cancels)",
}


class LayoutError(ValueError):
    """An edit the layout cannot accept"""


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


def _find(items: list, item_id: int):
    return next((item for item in items if item.get("id") == item_id), None)


def _free_id(items: list, first: int = 0, limit: int | None = None) -> int:
    used = {item.get("id") for item in items}
    candidate = first
    while candidate in used:
        candidate += 1
    if limit is not None and candidate > limit:
        raise LayoutError(f"No free id left (the serial protocol allows {first} to {limit})")
    return candidate


def _number(text: str):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return int(value) if value.is_integer() else value


def _grid_snap(point) -> tuple[int, int]:
    return round(point[0] / GRID) * GRID, round(point[1] / GRID) * GRID


class LayoutDocument:
    """An editable layout definition. Nodes are created where segments end and dropped when
    no segment uses them any more."""

    def __init__(self, data: dict | None = None):
        self.data = new_layout() if data is None else data
        for key, empty in new_layout().items():
            if self.data.get(key) is None:
                self.data[key] = empty

    def problems(self) -> list[str]:
        try:
            return validate_layout(self.data)
        except Exception as exc:
            return [f"Could not validate the layout: {exc}"]

    def set_metadata(self, name: str, description: str, scale: float):
        self.data["name"], self.data["description"], self.data["scale"] = name, description, scale

    # Geometry

    def segment_nodes(self) -> dict[int, tuple]:
        return {s["id"]: (s["from"], s["to"]) for s in self.data["segments"]}

    def node_positions(self) -> dict[int, tuple]:
        return {n["id"]: (n["x"], n["y"]) for n in self.data["nodes"]}

    def segments_at(self, node: int) -> list[int]:
        return sorted(segment_id for segment_id, nodes in self.segment_nodes().items() if node in nodes)

    def node_at(self, point, tolerance: float = SNAP_DISTANCE) -> int | None:
        nearest = None
        for node, position in self.node_positions().items():
            distance = math.dist(position, point)
            if distance <= tolerance and (nearest is None or distance < nearest[0]):
                nearest = (distance, node)
        return nearest[1] if nearest else None

    def snap(self, point) -> tuple:
        node = self.node_at(point)
        return self.node_positions()[node] if node is not None else _grid_snap(point)

    def add_segment(self, start, end, shape: str = "straight", flipped: bool = False, extent: int = 90) -> int:
        positions = self.node_positions()
        next_node = max(positions, default=-1) + 1
        nodes, points, new_nodes = [], [], []
        for point in (start, end):
            node = self.node_at(point)
            if node is None:
                node, next_node = next_node, next_node + 1
                point = _grid_snap(point)
                new_nodes.append({"id": node, "x": point[0], "y": point[1]})
            else:
                point = positions[node]
            nodes.append(node)
            points.append(point)
        if nodes[0] == nodes[1] or math.dist(points[0], points[1]) < SNAP_DISTANCE:
            raise LayoutError("A segment needs two distinct end points")
        if shape == "curve" and extent not in diagram_helper.CURVE_EXTENTS:
            raise LayoutError(f"Curve extent must be one of {list(diagram_helper.CURVE_EXTENTS)}")

        segment_id = _free_id(self.data["segments"], 1)
        segment = {"id": segment_id, "from": nodes[0], "to": nodes[1], "shape": shape}
        if shape == "curve":
            segment["extent"] = extent if flipped else -extent
        self.data["nodes"].extend(new_nodes)
        self.data["segments"].append(segment)
        self._cleanup()
        return segment_id

    def delete_segment(self, segment_id: int):
        if _find(self.data["segments"], segment_id) is None:
            raise LayoutError(f"Unknown segment {segment_id}")
        self.data["segments"] = [s for s in self.data["segments"] if s["id"] != segment_id]
        for track in self.data["tracks"]:
            if track.get("feeder_segment_id") == segment_id:
                del track["feeder_segment_id"]
        self._cleanup()

    def move_node(self, node: int, point, snap: bool = True):
        target = _grid_snap(point) if snap else tuple(point)
        for other, position in self.node_positions().items():
            if other != node and math.dist(position, target) < SNAP_DISTANCE:
                raise LayoutError("Another node is already there")
        moved = _find(self.data["nodes"], node)
        if moved is None:
            raise LayoutError(f"Unknown node {node}")
        moved["x"], moved["y"] = target

    def reverse_segment(self, segment_id: int):
        """Swaps the segment's ends, which flips the direction positive voltage moves trains."""
        segment = _find(self.data["segments"], segment_id)
        if segment is None:
            raise LayoutError(f"Unknown segment {segment_id}")
        segment["from"], segment["to"] = segment["to"], segment["from"]
        if segment.get("shape") == "curve":
            segment["extent"] = -segment["extent"]

    def _curve(self, segment_id: int) -> dict:
        segment = _find(self.data["segments"], segment_id)
        if segment is None or segment.get("shape") != "curve":
            raise LayoutError(f"Segment {segment_id} is not a curve")
        return segment

    def set_curve(self, segment_id: int, extent: float):
        """Sets the arc of a curve in degrees; negative is clockwise from the segment's start to its end."""
        segment = self._curve(segment_id)
        if abs(extent) not in diagram_helper.CURVE_EXTENTS:
            raise LayoutError(f"Curve extent must be one of {list(diagram_helper.CURVE_EXTENTS)} (negative for clockwise)")
        segment["extent"] = extent

    def flip_curve(self, segment_id: int):
        """Bends the curve the other way between the same end points."""
        segment = self._curve(segment_id)
        segment["extent"] = -segment["extent"]

    # Sensors, points and insulated joints

    def sensor_at(self, node: int) -> int | None:
        sensor = next((s for s in self.data["sensors"] if s.get("node") == node), None)
        return sensor["id"] if sensor else None

    def add_sensor(self, node: int) -> int:
        existing = self.sensor_at(node)
        if existing is not None:
            return existing
        sensor_id = _free_id(self.data["sensors"], 0, MAX_DEVICE_ID)
        self.data["sensors"].append({"id": sensor_id, "node": node})
        self._cleanup()
        return sensor_id

    def remove_sensor(self, node: int):
        self.data["sensors"] = [s for s in self.data["sensors"] if s.get("node") != node]
        self._cleanup()

    def set_sensor_id(self, node: int, sensor_id: int):
        sensor = next((s for s in self.data["sensors"] if s.get("node") == node), None)
        if sensor is None:
            raise LayoutError(f"Node {node} has no sensor")
        if not 0 <= sensor_id <= MAX_DEVICE_ID:
            raise LayoutError(f"Sensor id must be between 0 and {MAX_DEVICE_ID}")
        if sensor_id != sensor["id"] and _find(self.data["sensors"], sensor_id) is not None:
            raise LayoutError(f"Sensor {sensor_id} is already used by another node")
        for trap in self.data["speed_traps"]:
            for key in ("sensor_1_id", "sensor_2_id"):
                if trap.get(key) == sensor["id"]:
                    trap[key] = sensor_id
        sensor["id"] = sensor_id

    def point_at(self, node: int) -> dict | None:
        return next((p for p in self.data["points"] if p.get("node") == node), None)

    def set_point(self, node: int, primary: int, secondary: int, initial_direction: int = 0):
        touching = self.segments_at(node)
        if len(touching) != 3:
            raise LayoutError("A point needs exactly 3 segments at its node")
        if primary == secondary or primary not in touching or secondary not in touching:
            raise LayoutError("Choose two different segments at the node as the point's routes")
        point = self.point_at(node)
        if point is None:
            point = {"id": _free_id(self.data["points"], 0, MAX_DEVICE_ID), "node": node}
            self.data["points"].append(point)
        point.update({"initial_direction": initial_direction, "direction_segments": [primary, secondary]})

    def remove_point(self, node: int):
        self.data["points"] = [p for p in self.data["points"] if p.get("node") != node]

    def joints_at(self, node: int) -> list[dict]:
        return [j for j in self.data["insulated_joints"] if j.get("node") == node]

    def add_joint(self, node: int, first: int, second: int):
        touching = self.segments_at(node)
        if first == second or first not in touching or second not in touching:
            raise LayoutError("Choose two different segments that meet at the node")
        if not any(set(j["segments"]) == {first, second} for j in self.joints_at(node)):
            self.data["insulated_joints"].append({"node": node, "segments": [first, second]})

    def remove_joints(self, node: int):
        self.data["insulated_joints"] = [j for j in self.data["insulated_joints"] if j.get("node") != node]

    # Tracks and speed traps

    def add_track(self) -> int:
        track_id = _free_id(self.data["tracks"], 0, MAX_DEVICE_ID)
        self.data["tracks"].append({"id": track_id})
        return track_id

    def remove_track(self, track_id: int):
        self.data["tracks"] = [t for t in self.data["tracks"] if t["id"] != track_id]

    def feeder_tracks(self, segment_id: int) -> list[int]:
        return [t["id"] for t in self.data["tracks"] if t.get("feeder_segment_id") == segment_id]

    def set_feeder(self, track_id: int, segment_id: int):
        track = _find(self.data["tracks"], track_id)
        if track is None:
            raise LayoutError(f"Unknown track {track_id}")
        if _find(self.data["segments"], segment_id) is None:
            raise LayoutError(f"Unknown segment {segment_id}")
        self.clear_feeder(segment_id)
        track["feeder_segment_id"] = segment_id

    def clear_feeder(self, segment_id: int):
        for track in self.data["tracks"]:
            if track.get("feeder_segment_id") == segment_id:
                del track["feeder_segment_id"]

    def set_speed_trap(self, trap_id: int | None, track_id: int, sensor_1_id: int, sensor_2_id: int,
                       distance: float) -> int:
        if distance <= 0:
            raise LayoutError("Distance must be positive")
        traps = self.data["speed_traps"]
        trap = _find(traps, trap_id) if trap_id is not None else None
        if trap is None:
            trap = {"id": _free_id(traps, 0, MAX_DEVICE_ID)}
            traps.append(trap)
        trap.update({"track_id": track_id, "sensor_1_id": sensor_1_id, "sensor_2_id": sensor_2_id,
                     "distance": distance})
        return trap["id"]

    def remove_speed_trap(self, trap_id: int):
        self.data["speed_traps"] = [t for t in self.data["speed_traps"] if t["id"] != trap_id]

    # Blocks are derived from the sensors; only their initial occupancy is stored

    def blocks(self) -> dict[int, list[int]]:
        return derive_blocks(self.segment_nodes(), {s.get("node") for s in self.data["sensors"]})

    def block_summaries(self) -> list[dict]:
        nodes = self.segment_nodes()
        sensor_at_node = {s.get("node"): s["id"] for s in self.data["sensors"]}
        occupied = {b["id"] for b in self.data["blocks"] if b.get("occupied")}
        summaries = []
        for block_id, segment_ids in self.blocks().items():
            touched = {node for segment_id in segment_ids for node in nodes[segment_id]}
            summaries.append({
                "id": block_id,
                "segments": segment_ids,
                "sensors": sorted(sensor_at_node[node] for node in touched if node in sensor_at_node),
                "occupied": block_id in occupied,
            })
        return summaries

    def set_block_occupied(self, block_id: int, occupied: bool):
        if block_id not in self.blocks():
            raise LayoutError(f"Unknown block {block_id}")
        blocks = [b for b in self.data["blocks"] if b["id"] != block_id]
        if occupied:
            blocks.append({"id": block_id, "occupied": True})
        self.data["blocks"] = sorted(blocks, key=lambda b: b["id"])

    # Housekeeping

    def _cleanup(self):
        """Drops references left dangling by an edit, so the layout stays loadable."""
        nodes = self.segment_nodes()
        known = {node for pair in nodes.values() for node in pair}
        self.data["nodes"] = [n for n in self.data["nodes"] if n["id"] in known]
        self.data["sensors"] = [s for s in self.data["sensors"] if s.get("node") in known]
        self.data["insulated_joints"] = [
            j for j in self.data["insulated_joints"]
            if j.get("node") in known and all(sid in nodes and j["node"] in nodes[sid] for sid in j["segments"])]
        self.data["points"] = [
            p for p in self.data["points"]
            if p.get("node") in known and len(self.segments_at(p["node"])) == 3
            and all(sid in self.segments_at(p["node"]) for sid in p["direction_segments"])]
        derived = self.blocks()
        self.data["blocks"] = [b for b in self.data["blocks"] if b.get("occupied") and b["id"] in derived]


class FormDialog(tk.Toplevel):
    """Modal dialog with one entry or drop-down per field."""

    def __init__(self, parent, title: str, fields: list):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.result = None
        self._vars: dict[str, tk.StringVar] = {}
        body = ttk.Frame(self, padding=10)
        body.pack()
        for row, (key, label, initial, choices) in enumerate(fields):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=initial)
            if choices:
                widget = ttk.Combobox(body, textvariable=var, values=choices, state="readonly", width=24)
            else:
                widget = ttk.Entry(body, textvariable=var, width=26)
            widget.grid(row=row, column=1, padx=(8, 0), pady=2)
            self._vars[key] = var
        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="right", padx=(0, 6))
        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_visibility()
        self.grab_set()

    def _ok(self):
        self.result = {key: var.get() for key, var in self._vars.items()}
        self.destroy()


def ask_form(parent, title: str, fields: list) -> dict | None:
    """fields are (key, label, initial value, choices or None); returns the entered strings or None."""
    dialog = FormDialog(parent, title, fields)
    dialog.wait_window()
    return dialog.result


class LayoutEditor:
    def __init__(self, root, path: str | None = None):
        self.root = root
        self.doc = LayoutDocument()
        self.path: str | None = None
        self.modified = False
        self.undo_stack: list[dict] = []
        self.selection: tuple[str, int] | None = None  # ("segment" | "node", id)
        self.pending_start: tuple | None = None
        self._drag: dict | None = None
        self._track_ids: list[int] = []
        self._trap_ids: list[int] = []
        self._block_ids: list[int] = []
        self.tool = tk.StringVar(value="select")
        self.show_ids = tk.BooleanVar(value=True)
        self.flip_curve = tk.BooleanVar(value=False)
        self.curve_extent = tk.StringVar(value="90")
        self._cursor: tuple | None = None
        self.name_var = tk.StringVar()
        self.description_var = tk.StringVar()
        self.scale_var = tk.StringVar()
        self.status = tk.StringVar()

        self._build_menu()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if path:
            self._load(path)
        self._refresh()

    # UI construction

    def _build_menu(self):
        modifier = "Command" if sys.platform == "darwin" else "Control"
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="New", command=self.new)
        file_menu.add_command(label="Open...", command=self.open, accelerator=f"{modifier}+O")
        file_menu.add_command(label="Save", command=self.save, accelerator=f"{modifier}+S")
        file_menu.add_command(label="Save As...", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Close", command=self.close)
        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator=f"{modifier}+Z")
        edit_menu.add_command(label="Validate", command=self.validate)
        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        self.root.config(menu=menubar)
        self.root.bind(f"<{modifier}-z>", lambda _: self.undo())
        self.root.bind(f"<{modifier}-s>", lambda _: self.save())
        self.root.bind(f"<{modifier}-o>", lambda _: self.open())

    def _build_ui(self):
        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        main.add(left, weight=1)
        toolbar = ttk.Frame(left, padding=4)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="New", command=self.new).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Open...", command=self.open).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Save", command=self.save).pack(side="left", padx=(0, 10))
        for label, value in (("Select / move", "select"), ("Straight", "straight"), ("Curve", "curve")):
            ttk.Radiobutton(toolbar, text=label, value=value, variable=self.tool,
                            command=self._on_tool_change).pack(side="left", padx=2)
        ttk.Label(toolbar, text="Arc").pack(side="left", padx=(6, 0))
        ttk.Combobox(toolbar, textvariable=self.curve_extent, state="readonly", width=4,
                     values=[str(extent) for extent in diagram_helper.CURVE_EXTENTS]).pack(side="left", padx=2)
        self.curve_extent.trace_add("write", lambda *_: self._refresh_preview())
        ttk.Checkbutton(toolbar, text="Flip curve (R)", variable=self.flip_curve,
                        command=self._refresh_preview).pack(side="left", padx=2)
        ttk.Checkbutton(toolbar, text="Show ids", variable=self.show_ids,
                        command=self._redraw).pack(side="left", padx=10)
        canvas_width, canvas_height = load_canvas_size()
        self.canvas = tk.Canvas(left, width=canvas_width, height=canvas_height, bg="white", highlightthickness=1,
                                highlightbackground="gray")
        self.canvas.pack(anchor="nw")
        ttk.Label(left, textvariable=self.status, anchor="w", padding=4,
                  wraplength=canvas_width).pack(fill="x")
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Escape>", lambda _: self._cancel_pending())
        self.canvas.bind("<r>", lambda _: self._toggle_flip())
        self.canvas.bind("<Delete>", lambda _: self._delete_selected())
        self.canvas.bind("<BackSpace>", lambda _: self._delete_selected())

        notebook = ttk.Notebook(main, width=340)
        main.add(notebook)
        self.selection_frame = ttk.Frame(notebook, padding=8)
        notebook.add(self.selection_frame, text="Selection")
        self.track_list = self._list_tab(notebook, "Tracks", [
            ("Add", lambda: self._edit(self.doc.add_track)),
            ("Remove", self._remove_track)])
        self.trap_list = self._list_tab(notebook, "Speed traps", [
            ("Add...", lambda: self._speed_trap_dialog(None)),
            ("Edit...", self._edit_speed_trap),
            ("Remove", self._remove_speed_trap)])
        self.block_list = self._list_tab(notebook, "Blocks", [
            ("Toggle occupied", self._toggle_block)])
        layout_tab = ttk.Frame(notebook, padding=8)
        notebook.add(layout_tab, text="Layout")
        for row, (label, var) in enumerate((("Name", self.name_var), ("Description", self.description_var),
                                            ("Scale", self.scale_var))):
            ttk.Label(layout_tab, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(layout_tab, textvariable=var, width=28)
            entry.grid(row=row, column=1, padx=(8, 0), pady=2)
            entry.bind("<FocusOut>", lambda _: self._apply_metadata())
            entry.bind("<Return>", lambda _: self._apply_metadata())

    @staticmethod
    def _list_tab(notebook, title: str, buttons: list) -> tk.Listbox:
        tab = ttk.Frame(notebook, padding=8)
        notebook.add(tab, text=title)
        listbox = tk.Listbox(tab, height=12, exportselection=False)
        listbox.pack(fill="both", expand=True)
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(6, 0))
        for label, command in buttons:
            ttk.Button(row, text=label, command=command).pack(side="left", padx=(0, 4))
        return listbox

    # Editing

    def _edit(self, action, *args):
        """Runs a document change, keeping an undo snapshot. Returns the action's result, or None if rejected."""
        snapshot = copy.deepcopy(self.doc.data)
        try:
            result = action(*args)
        except LayoutError as exc:
            self.doc.data = snapshot
            messagebox.showerror("Layout editor", str(exc), parent=self.root)
            return None
        self._push_undo(snapshot)
        self.modified = True
        self._refresh()
        return result

    def _push_undo(self, snapshot: dict):
        self.undo_stack.append(snapshot)
        del self.undo_stack[:-100]

    def undo(self):
        if not self.undo_stack:
            return
        self.doc.data = self.undo_stack.pop()
        self.modified = True
        self.pending_start = None
        self._refresh()

    def validate(self):
        problems = self.doc.problems()
        if problems:
            shown = "\n".join(f"- {p}" for p in problems[:15])
            more = f"\n... and {len(problems) - 15} more" if len(problems) > 15 else ""
            messagebox.showwarning("Layout problems", shown + more, parent=self.root)
        else:
            messagebox.showinfo("Layout editor", "The layout is valid.", parent=self.root)

    def _select(self, selection):
        self.selection = selection
        self._redraw()
        self._build_selection_panel()

    def _delete_selected(self):
        if self.selection and self.selection[0] == "segment":
            self._edit(self.doc.delete_segment, self.selection[1])

    # Canvas interaction

    def _on_tool_change(self):
        self._cancel_pending()

    def _cancel_pending(self):
        self.pending_start = None
        self.canvas.delete("preview")
        self._refresh_status()

    def _toggle_flip(self):
        self.flip_curve.set(not self.flip_curve.get())
        self._refresh_preview()

    def _refresh_preview(self):
        if self.pending_start is not None and self._cursor is not None:
            self._draw_preview(self.doc.snap(self._cursor))

    def _segment_at(self, point) -> int | None:
        x, y = point
        for item in reversed(self.canvas.find_overlapping(x - 4, y - 4, x + 4, y + 4)):
            for tag in self.canvas.gettags(item):
                if tag.startswith("segment:"):
                    return int(tag.split(":")[1])
        return None

    def _on_press(self, event):
        self.canvas.focus_set()
        point = (event.x, event.y)
        tool = self.tool.get()
        if tool == "select":
            node = self.doc.node_at(point)
            if node is not None:
                self._select(("node", node))
                self._drag = {"node": node, "snapshot": copy.deepcopy(self.doc.data), "moved": False}
            else:
                segment_id = self._segment_at(point)
                self._select(("segment", segment_id) if segment_id is not None else None)
            return

        snapped = self.doc.snap(point)
        if self.pending_start is None:
            self.pending_start = snapped
            self._cursor = point
            self._draw_preview(snapped)
            return
        start, self.pending_start = self.pending_start, None
        segment_id = self._edit(self.doc.add_segment, start, snapped, tool, self.flip_curve.get(),
                                int(self.curve_extent.get()))
        if segment_id is not None:
            self._select(("segment", segment_id))

    def _on_motion(self, event):
        self._cursor = (event.x, event.y)
        if self.pending_start is not None:
            self._draw_preview(self.doc.snap((event.x, event.y)))

    def _on_drag(self, event):
        if self._drag is None:
            return
        try:
            self.doc.move_node(self._drag["node"], (event.x, event.y))
        except LayoutError:
            return
        self._drag["moved"] = True
        self._redraw()

    def _on_release(self, _event):
        drag, self._drag = self._drag, None
        if drag and drag["moved"]:
            self._push_undo(drag["snapshot"])
            self.modified = True
            self._refresh()

    def _draw_preview(self, end):
        self.canvas.delete("preview")
        start = self.pending_start
        extent = int(self.curve_extent.get())
        segment = {"from": 0, "to": 1, "shape": self.tool.get(), "extent": extent if self.flip_curve.get() else -extent}
        points, smooth = self._segment_points(segment, {0: start, 1: end})
        self.canvas.create_line(*points, smooth=smooth, fill="#d9232d", dash=(4, 3), width=2, tags="preview")
        self.canvas.create_oval(start[0] - 5, start[1] - 5, start[0] + 5, start[1] + 5, outline="#d9232d",
                                tags="preview")

    # Drawing

    @staticmethod
    def _segment_points(segment: dict, positions: dict) -> tuple[list, bool]:
        """Line points and whether to smooth them; a curve that cannot be drawn falls back to a straight line."""
        if segment.get("shape") == "curve":
            try:
                return diagram_helper.segment_line_points(segment, positions), True
            except (ValueError, KeyError, ZeroDivisionError):
                pass
        return [*positions[segment["from"]], *positions[segment["to"]]], False

    @staticmethod
    def _midpoint(points: list) -> tuple:
        pairs = list(zip(points[0::2], points[1::2]))
        first, second = pairs[(len(pairs) - 1) // 2], pairs[len(pairs) // 2]
        return (first[0] + second[0]) / 2, (first[1] + second[1]) / 2

    def _redraw(self):
        canvas, doc = self.canvas, self.doc
        canvas.delete("all")
        positions = doc.node_positions()
        segments = {s["id"]: s for s in doc.data["segments"]}
        label_font = ("TkDefaultFont", 9, "bold")

        for block in doc.block_summaries():
            color = OCCUPIED_COLOR if block["occupied"] else UNOCCUPIED_COLOR
            for segment_id in block["segments"]:
                if segment_id in segments:
                    points, smooth = self._segment_points(segments[segment_id], positions)
                    canvas.create_line(*points, width=BLOCK_WIDTH, fill=color, smooth=smooth)

        for segment_id, segment in segments.items():
            points, smooth = self._segment_points(segment, positions)
            selected = self.selection == ("segment", segment_id)
            options = {"width": 4 if selected else 2, "fill": "#d9232d" if selected else "black",
                       "smooth": smooth, "arrow": tk.LAST, "arrowshape": (10, 12, 4),
                       "tags": ("segment", f"segment:{segment_id}")}
            if segment.get("shape") == "curve" and not smooth:
                options["dash"] = (4, 3)
            canvas.create_line(*points, **options)
            x, y = self._midpoint(points)
            if doc.feeder_tracks(segment_id):
                canvas.create_polygon(diagram_helper.feeder_symbol(x, y), fill="lime", outline="black")
            if self.show_ids.get():
                canvas.create_text(x + 9, y - 10, text=str(segment_id), fill="#1a4fd6", font=label_font)

        sensors = {s.get("node"): s["id"] for s in doc.data["sensors"]}
        points_by_node = {p.get("node"): p["id"] for p in doc.data["points"]}
        joint_nodes = {j.get("node") for j in doc.data["insulated_joints"]}
        for node, (x, y) in positions.items():
            if self.selection == ("node", node):
                canvas.create_oval(x - 13, y - 13, x + 13, y + 13, outline="orange", width=3)
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="white", outline="black")
            if node in sensors:
                canvas.create_oval(x - 10, y - 10, x + 10, y + 10, fill="#2f6fdb", outline="black")
                canvas.create_text(x, y, text=f"S{sensors[node]}", fill="white", font=label_font)
            if node in points_by_node:
                canvas.create_polygon(x, y - 8, x + 8, y, x, y + 8, x - 8, y, fill="", outline="#a01010", width=2)
                canvas.create_text(x + 16, y + 12, text=f"P{points_by_node[node]}", fill="#a01010", font=label_font)
            if node in joint_nodes:
                canvas.create_polygon(diagram_helper.isolator_symbol(x, y), fill="", outline="red", width=2)
            if self.show_ids.get():
                canvas.create_text(x - 12, y + 12, text=f"n{node}", fill="gray40", font=("TkDefaultFont", 8))

    # Selection panel

    def _build_selection_panel(self):
        frame = self.selection_frame
        for child in frame.winfo_children():
            child.destroy()
        if self.selection is None:
            ttk.Label(frame, text="Nothing selected.\nClick a node or a segment.", justify="left").pack(anchor="w")
            return
        kind, item_id = self.selection
        if kind == "segment":
            self._build_segment_panel(frame, item_id)
        else:
            self._build_node_panel(frame, item_id)

    def _build_segment_panel(self, frame, segment_id: int):
        segment = _find(self.doc.data["segments"], segment_id)
        start, end = segment["from"], segment["to"]
        shape = segment.get("shape", "straight")
        ttk.Label(frame, text=f"Segment {segment_id}", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, text=f"{shape}, from node {start} to node {end}").pack(anchor="w")
        ttk.Label(frame, text="Positive voltage moves trains from the start to the end.",
                  wraplength=300).pack(anchor="w")

        if shape == "curve":
            curve = ttk.LabelFrame(frame, text="Curve", padding=6)
            curve.pack(fill="x", pady=8)
            extent_var = tk.StringVar(value=str(segment.get("extent", "")))
            ttk.Label(curve, text="Extent").grid(row=0, column=0, sticky="w", pady=2)
            choices = [str(sign * extent) for sign in (-1, 1) for extent in diagram_helper.CURVE_EXTENTS]
            ttk.Combobox(curve, textvariable=extent_var, values=choices, width=6, state="readonly").grid(
                row=0, column=1, padx=6)
            ttk.Button(curve, text="Apply", command=lambda: self._apply_curve(
                segment_id, extent_var.get())).grid(row=1, column=0, columnspan=2, pady=(6, 0))
            ttk.Button(curve, text="Flip curve", command=lambda: self._edit(
                self.doc.flip_curve, segment_id)).grid(row=2, column=0, columnspan=2, pady=(4, 0))

        feeders = self.doc.feeder_tracks(segment_id)
        ttk.Label(frame, text=f"Feeder of track {', '.join(map(str, feeders))}" if feeders else "Not a feeder"
                  ).pack(anchor="w", pady=(8, 2))
        ttk.Button(frame, text="Set as feeder...", command=lambda: self._set_feeder(segment_id)).pack(anchor="w")
        if feeders:
            ttk.Button(frame, text="Clear feeder",
                       command=lambda: self._edit(self.doc.clear_feeder, segment_id)).pack(anchor="w", pady=2)
        ttk.Button(frame, text="Reverse direction",
                   command=lambda: self._edit(self.doc.reverse_segment, segment_id)).pack(anchor="w", pady=(8, 2))
        ttk.Button(frame, text="Delete segment",
                   command=lambda: self._edit(self.doc.delete_segment, segment_id)).pack(anchor="w")

    def _build_node_panel(self, frame, node: int):
        x, y = self.doc.node_positions()[node]
        touching = self.doc.segments_at(node)
        ttk.Label(frame, text=f"Node {node}", font=("TkDefaultFont", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, text=f"Joins segments {', '.join(map(str, touching))}",
                  wraplength=300).pack(anchor="w")
        position_row = ttk.Frame(frame)
        position_row.pack(anchor="w", pady=(6, 0))
        x_var, y_var = tk.StringVar(value=str(x)), tk.StringVar(value=str(y))
        for label, var in (("X", x_var), ("Y", y_var)):
            ttk.Label(position_row, text=label).pack(side="left")
            entry = ttk.Entry(position_row, textvariable=var, width=7)
            entry.pack(side="left", padx=(2, 8))
            entry.bind("<Return>", lambda _: self._apply_position(node, x_var.get(), y_var.get()))
        ttk.Button(position_row, text="Set",
                   command=lambda: self._apply_position(node, x_var.get(), y_var.get())).pack(side="left")

        sensor_id = self.doc.sensor_at(node)
        sensor_var = tk.BooleanVar(value=sensor_id is not None)
        ttk.Checkbutton(
            frame, text="Sensor" + (f" (S{sensor_id})" if sensor_id is not None else ""), variable=sensor_var,
            command=lambda: self._edit(self.doc.add_sensor if sensor_var.get() else self.doc.remove_sensor, node)
        ).pack(anchor="w", pady=(10, 4))
        if sensor_id is not None:
            id_row = ttk.Frame(frame)
            id_row.pack(anchor="w")
            ttk.Label(id_row, text="Sensor id").pack(side="left")
            id_var = tk.StringVar(value=str(sensor_id))
            ttk.Entry(id_row, textvariable=id_var, width=5).pack(side="left", padx=6)
            ttk.Button(id_row, text="Set", command=lambda: self._apply_sensor_id(node, id_var.get())).pack(side="left")

        point = self.doc.point_at(node)
        if point:
            routes = point["direction_segments"]
            stem = [s for s in touching if s not in routes]
            text = (f"Point P{point['id']}: stem {stem[0] if stem else '?'}, routes {routes[0]} / {routes[1]}, "
                    f"initial direction {point['initial_direction']}")
        else:
            text = "No point"
        ttk.Label(frame, text=text, wraplength=300).pack(anchor="w", pady=(6, 2))
        if len(touching) == 3:
            ttk.Button(frame, text="Edit point..." if point else "Make point...",
                       command=lambda: self._edit_point(node)).pack(anchor="w")
        if point:
            ttk.Button(frame, text="Remove point",
                       command=lambda: self._edit(self.doc.remove_point, node)).pack(anchor="w", pady=2)

        joints = self.doc.joints_at(node)
        text = ("Insulated joints: " + ", ".join(f"{a} | {b}" for a, b in (j["segments"] for j in joints))
                if joints else "No insulated joints")
        ttk.Label(frame, text=text, wraplength=300).pack(anchor="w", pady=(10, 2))
        if len(touching) >= 2:
            ttk.Button(frame, text="Add insulated joint...", command=lambda: self._add_joint(node)).pack(anchor="w")
        if joints:
            ttk.Button(frame, text="Remove joints",
                       command=lambda: self._edit(self.doc.remove_joints, node)).pack(anchor="w", pady=2)

    def _apply_position(self, node: int, x_text: str, y_text: str):
        try:
            point = (_number(x_text), _number(y_text))
        except ValueError:
            messagebox.showerror("Layout editor", "X and Y must be numbers", parent=self.root)
            return
        if point != self.doc.node_positions()[node]:
            self._edit(self.doc.move_node, node, point, False)

    def _apply_sensor_id(self, node: int, text: str):
        try:
            sensor_id = int(text)
        except ValueError:
            messagebox.showerror("Layout editor", "Sensor id must be a whole number", parent=self.root)
            return
        self._edit(self.doc.set_sensor_id, node, sensor_id)

    def _apply_curve(self, segment_id: int, extent_text: str):
        self._edit(self.doc.set_curve, segment_id, int(extent_text))

    def _set_feeder(self, segment_id: int):
        new_track = "(new track)"
        tracks = [str(t["id"]) for t in self.doc.data["tracks"]]
        choice = new_track
        if tracks:
            answer = ask_form(self.root, "Set feeder", [("track", "Track", tracks[0], tracks + [new_track])])
            if answer is None:
                return
            choice = answer["track"]

        def action():
            track_id = self.doc.add_track() if choice == new_track else int(choice)
            self.doc.set_feeder(track_id, segment_id)

        self._edit(action)

    def _edit_point(self, node: int):
        touching = [str(s) for s in self.doc.segments_at(node)]
        point = self.doc.point_at(node)
        routes = point["direction_segments"] if point else [int(touching[0]), int(touching[1])]
        initial = INITIAL_DIRECTIONS[point["initial_direction"]] if point else INITIAL_DIRECTIONS[0]
        answer = ask_form(self.root, "Point", [
            ("primary", "Primary route segment", str(routes[0]), touching),
            ("secondary", "Secondary route segment", str(routes[1]), touching),
            ("initial", "Initial direction", initial, INITIAL_DIRECTIONS)])
        if answer is not None:
            self._edit(self.doc.set_point, node, int(answer["primary"]), int(answer["secondary"]),
                       int(answer["initial"][0]))

    def _add_joint(self, node: int):
        touching = [str(s) for s in self.doc.segments_at(node)]
        answer = ask_form(self.root, "Insulated joint", [
            ("first", "First segment", touching[0], touching),
            ("second", "Second segment", touching[1], touching)])
        if answer is not None:
            self._edit(self.doc.add_joint, node, int(answer["first"]), int(answer["second"]))

    # Lists

    @staticmethod
    def _fill_list(listbox: tk.Listbox, rows: list) -> list[int]:
        listbox.delete(0, "end")
        for _, text in rows:
            listbox.insert("end", text)
        return [item_id for item_id, _ in rows]

    @staticmethod
    def _selected_id(listbox: tk.Listbox, ids: list[int]) -> int | None:
        selection = listbox.curselection()
        return ids[selection[0]] if selection else None

    def _refresh_lists(self):
        data = self.doc.data
        self._track_ids = self._fill_list(self.track_list, [
            (t["id"], f"Track {t['id']}  (feeder: segment {t['feeder_segment_id']})"
             if t.get("feeder_segment_id") is not None else f"Track {t['id']}  (no feeder)")
            for t in data["tracks"]])
        self._trap_ids = self._fill_list(self.trap_list, [
            (t["id"], f"Trap {t['id']}: track {t.get('track_id')}, S{t.get('sensor_1_id')} to "
                      f"S{t.get('sensor_2_id')}, distance {t.get('distance')}")
            for t in data["speed_traps"]])
        self._block_ids = self._fill_list(self.block_list, [
            (b["id"], f"Block {b['id']}: segments {b['segments']}, sensors {b['sensors']}"
                      f"{'  [occupied]' if b['occupied'] else ''}")
            for b in self.doc.block_summaries()])

    def _remove_track(self):
        track_id = self._selected_id(self.track_list, self._track_ids)
        if track_id is not None:
            self._edit(self.doc.remove_track, track_id)

    def _edit_speed_trap(self):
        trap_id = self._selected_id(self.trap_list, self._trap_ids)
        if trap_id is not None:
            self._speed_trap_dialog(trap_id)

    def _remove_speed_trap(self):
        trap_id = self._selected_id(self.trap_list, self._trap_ids)
        if trap_id is not None:
            self._edit(self.doc.remove_speed_trap, trap_id)

    def _toggle_block(self):
        block_id = self._selected_id(self.block_list, self._block_ids)
        if block_id is None:
            return
        summary = next(b for b in self.doc.block_summaries() if b["id"] == block_id)
        self._edit(self.doc.set_block_occupied, block_id, not summary["occupied"])

    def _speed_trap_dialog(self, trap_id: int | None):
        tracks = [str(t["id"]) for t in self.doc.data["tracks"]]
        sensors = [str(s["id"]) for s in self.doc.data["sensors"]]
        if not tracks or not sensors:
            messagebox.showinfo("Layout editor", "Add a track and at least one sensor first.", parent=self.root)
            return
        trap = _find(self.doc.data["speed_traps"], trap_id) or {}

        def initial(key: str, choices: list) -> str:
            value = str(trap.get(key, choices[0]))
            return value if value in choices else choices[0]

        answer = ask_form(self.root, "Speed trap", [
            ("track", "Track", initial("track_id", tracks), tracks),
            ("sensor_1", "First sensor", initial("sensor_1_id", sensors), sensors),
            ("sensor_2", "Second sensor", initial("sensor_2_id", sensors), sensors),
            ("distance", "Distance", str(trap.get("distance", "")), None)])
        if answer is None:
            return
        try:
            distance = _number(answer["distance"])
        except ValueError:
            messagebox.showerror("Layout editor", "Distance must be a number", parent=self.root)
            return
        self._edit(self.doc.set_speed_trap, trap_id, int(answer["track"]), int(answer["sensor_1"]),
                   int(answer["sensor_2"]), distance)

    def _apply_metadata(self):
        data = self.doc.data
        try:
            scale = _number(self.scale_var.get())
            if scale <= 0:
                raise ValueError
        except ValueError:
            self.scale_var.set(str(data["scale"]))
            self.status.set("Scale must be a positive number")
            return
        values = (self.name_var.get(), self.description_var.get(), scale)
        if values != (data["name"], data["description"], data["scale"]):
            self._edit(self.doc.set_metadata, *values)

    # Status and files

    def _refresh(self):
        if self.selection is not None:
            kind, item_id = self.selection
            exists = item_id in (self.doc.segment_nodes() if kind == "segment" else self.doc.node_positions())
            if not exists:
                self.selection = None
        self._redraw()
        self._build_selection_panel()
        self._refresh_lists()
        data = self.doc.data
        self.name_var.set(data["name"])
        self.description_var.set(data["description"])
        self.scale_var.set(str(data["scale"]))
        self._refresh_status()
        name = os.path.basename(self.path) if self.path else "untitled"
        self.root.title(f"Layout Editor - {name}{' *' if self.modified else ''}")

    def _refresh_status(self):
        problems = self.doc.problems()
        summary = f"{len(problems)} problem(s): {problems[0]}" if problems else "Layout is valid"
        self.status.set(f"{TOOL_HINTS[self.tool.get()]}   |   {summary}")

    def _confirm_discard(self) -> bool:
        if not self.modified:
            return True
        answer = messagebox.askyesnocancel("Layout editor", "Save the changes to this layout first?",
                                           parent=self.root)
        if answer is None:
            return False
        return self.save() if answer else True

    def _replace_document(self, doc: LayoutDocument, path: str | None):
        self.doc, self.path = doc, path
        self.modified = False
        self.undo_stack.clear()
        self.selection = None
        self.pending_start = None
        self._refresh()

    def new(self):
        if self._confirm_discard():
            self._replace_document(LayoutDocument(), None)

    def open(self):
        if not self._confirm_discard():
            return
        initial_dir = os.path.dirname(self.path) if self.path else os.path.join("data", "layouts")
        path = filedialog.askopenfilename(
            parent=self.root, title="Open a layout file", initialdir=initial_dir,
            filetypes=[("Layout files", "*.json *.yaml *.yml"), ("JSON files", "*.json"), ("YAML files", "*.yaml *.yml")])
        if path:
            self._load(path)

    def _load(self, path: str):
        try:
            data = load_data_from_file(path)
            if not isinstance(data, dict):
                raise ValueError("The file does not contain a layout")
            doc = LayoutDocument(data)
        except Exception as exc:
            messagebox.showerror("Layout editor", str(exc), parent=self.root)
            return
        self._replace_document(doc, path)

    def save(self) -> bool:
        return self._write(self.path) if self.path else self.save_as()

    def save_as(self) -> bool:
        initial_dir = os.path.dirname(self.path) if self.path else os.path.join("data", "layouts")
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save layout", initialdir=initial_dir, defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("YAML files", "*.yaml *.yml")])
        return self._write(path) if path else False

    def _write(self, path: str) -> bool:
        problems = self.doc.problems()
        if problems and not messagebox.askyesno(
                "Layout problems", f"The layout has {len(problems)} problem(s), for example:\n{problems[0]}\n\n"
                "It will not load in the train GUI until they are fixed. Save anyway?", parent=self.root):
            return False
        try:
            save_data_to_file(self.doc.data, path)
        except Exception as exc:
            messagebox.showerror("Layout editor", str(exc), parent=self.root)
            return False
        self.path = path
        self.modified = False
        self._refresh()
        return True

    def close(self):
        if self._confirm_discard():
            self.root.destroy()


def main():
    root = tk.Tk()
    LayoutEditor(root, sys.argv[1] if len(sys.argv) > 1 else None)
    root.mainloop()


if __name__ == "__main__":
    main()
