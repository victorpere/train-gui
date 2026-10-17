import os
import configparser
from typing import Tuple, Protocol
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog as fd
from tkinter.ttk import Button
import tkinter.font as tkFont
from scenario import ScenarioRunner, ScenarioState, ScenarioStatus
from railway import Layout, Message, MessageType, DeviceType, Sensor, Point
from communication import Communicator
from util import load_data_from_file, save_data_to_file, load_canvas_size
import diagram_helper

DEFAULT_LAYOUT_PATH = os.path.join("data", "layouts", "layout01.json")
STATE_FILE = os.path.join("config", "state.json")


def load_last_layout_path():
    try:
        return load_data_from_file(STATE_FILE).get("last_layout")
    except Exception:
        return None


def save_last_layout_path(layout_path: str):
    try:
        save_data_to_file({"last_layout": layout_path}, STATE_FILE)
    except Exception as exc:
        print(f"Failed to save last layout: {exc}")


class DiagramConfig:
    def __init__(self):
        config = configparser.ConfigParser()
        # Read the configuration file
        config.read('config/config.ini')
        self.canvas_width, self.canvas_height = load_canvas_size()
        self.line_width = int(config.get("Diagram", "line_width"))
        self.line_width_point_active = int(config.get(
            "Diagram", "line_width_point_active"))
        self.block_width = int(config.get("Diagram", "block_width"))
        self.block_unoccupied_color = config.get("Diagram", "block_unoccupied_color")
        self.block_occupied_color = config.get("Diagram", "block_occupied_color")
        self.line_color = config.get("Diagram", "line_color")
        self.electrified_color = config.get("Diagram", "electrified_color")
        self.symbol_outline_color = config.get(
            "Diagram", "symbol_outline_color")
        self.symbol_outline_width = int(config.get(
            "Diagram", "symbol_outline_width"))
        self.symbol_fill_color = config.get("Diagram", "symbol_fill_color")
        self.symbol_active_color = config.get("Diagram", "symbol_active_color")
        self.symbol_diameter = float(config.get("Diagram", "symbol_diameter"))
        self.symbol_text_color = config.get("Diagram", "symbol_text_color")


class ControllerCallback(Protocol):
    def __call__(self, message: Message) -> Tuple[bool, str]: ...


class SpeedDisplay:
    speed_trap_id: int
    track_id: int
    last_speed: tk.DoubleVar
    speed_label: ttk.Label

    def __init__(self, speed_trap_id: int):
        self.speed_trap_id = speed_trap_id
        self.last_speed = tk.DoubleVar(value=0)


class TrackControl:
    """Encapsulates UI controls for a track"""

    track_id: int
    direction: tk.IntVar
    target_voltage: tk.IntVar
    actual_voltage: tk.IntVar
    direction_label: ttk.Label
    target_voltage_label: ttk.Label
    actual_voltage_label: ttk.Label
    reverse_button: ttk.Button
    forward_button: ttk.Button
    control_buttons: list[ttk.Button]
    message_label: ttk.Label

    def __init__(self, track_id: int, callback: ControllerCallback):
        self.track_id = track_id
        self.direction = tk.IntVar(value=1)
        self.target_voltage = tk.IntVar(value=0)
        self.actual_voltage = tk.IntVar(value=0)
        self.callback = callback

    def reset_buttons(self):
        for btn in self.control_buttons:
            btn.config(state="normal")

    def set_voltage(self, voltage: int, button_pressed: Button):
        self.set_message()
        directional_voltage = voltage * self.direction.get()

        message = Message(
            message_type=MessageType.SET,
            device_type=DeviceType.TARGET_VOLTAGE,
            device_id=self.track_id,
            value=directional_voltage
        )

        ok, msg = self.callback(message)

        if ok:
            self.target_voltage.set(voltage)
            self.reset_buttons()
            button_pressed.config(state="disabled")
        else:
            self.set_message("error", msg)
            self.reset_buttons()

    def set_forward(self):
        self.set_message()
        if self.direction.get() == 1:
            self.set_message("info", "Already moving forward")
            return
        self.direction.set(1)
        self.forward_button.config(state="disabled")
        self.reverse_button.config(state="normal")

    def set_reverse(self):
        self.set_message()
        if self.direction.get() == -1:
            self.set_message("info", "Already moving reverse")
            return
        self.direction.set(-1)
        self.reverse_button.config(state="disabled")
        self.forward_button.config(state="normal")

    def set_message(self, level="", message=""):
        """Display a track control message with a given level (info, warning, error)."""
        if level == "info":
            self.message_label.config(text=message, foreground="")
        elif level == "warning":
            self.message_label.config(text=message, foreground="orange")
        elif level == "error":
            self.message_label.config(text=message, foreground="red")
        else:
            self.message_label.config(text=message, foreground="")


class TrainController:
    def __init__(self, root, layout_data, buttons_data=None, layout_path=None):
        self.root = root
        self.layout_data = layout_data
        self.layout_path = layout_path
        self.root.title("N-Scale Train Controller")

        # Mac default; change as needed
        self.port_var = tk.StringVar(value="/dev/cu.usbmodem101")
        communicator = Communicator()
        self.layout = Layout(communicator)
        self.layout.add_listener(self._on_event)
        layout_ok, layout_msg = self.layout.load(layout_data)

        if not layout_ok:
            print(f"train_gui layout load failed: {layout_msg}")
            return

        self.buttons_data = buttons_data or []

        self.scenario_runner = ScenarioRunner(layout=self.layout)
        self.scenario_runner.add_listener(self._on_scenario_event)
        self.layout_file = tk.StringVar()
        self.layout_name = tk.StringVar()
        self.layout_description = tk.StringVar()
        self.scenario_file = tk.StringVar()
        self.scenario_name = tk.StringVar()
        self.scenario_description = tk.StringVar()
        self.scenario_status = tk.StringVar(value="")
        self.scenario_iteration = tk.StringVar()
        self.scenario_times = tk.IntVar(value=1)
        self._highlighted_step_iid = None

        self.controls: dict[int, TrackControl] = {}
        self.speed_displays: dict[int, SpeedDisplay] = {}
        self.sensor_indicators: dict[int, int] = {}
        self.segments: dict[int, Tuple[str, int]] = {}
        self.block_items: dict[int, list[int]] = {}

        self.diagram_config = DiagramConfig()
        self.build_ui()

    def build_ui(self):
        self.left_frame = ttk.LabelFrame(self.root, text="Layout")
        self.right_frame = ttk.LabelFrame(self.root)
        self.left_frame.pack(side="left", fill="y")
        self.right_frame.pack(side="right", fill="y")

        # Serial connection frame
        conn_frame = ttk.Frame(self.left_frame, padding=10)
        conn_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(conn_frame, text="Port:").grid(row=0, column=0)
        ttk.Entry(conn_frame, textvariable=self.port_var,
                  width=20).grid(row=0, column=1)

        self.connect_button = ttk.Button(
            conn_frame, text="Connect", command=self.connect_serial)
        self.connect_button.grid(row=0, column=2, padx=5)
        self.status_label = ttk.Label(
            conn_frame, text="Disconnected", foreground="red")
        self.status_label.grid(row=0, column=3)

        self.test_mode_var = tk.BooleanVar(value=self.layout.test_mode)
        ttk.Checkbutton(conn_frame, text="Test Mode", variable=self.test_mode_var,
                        command=self._toggle_test_mode).grid(row=0, column=4, columnspan=2, sticky="w", pady=(5, 0))

        layout_file_frame = ttk.LabelFrame(self.left_frame, padding=10)
        layout_file_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(layout_file_frame, text="Load layout from file",
                   command=self.select_layout_file).grid(row=0, column=0, sticky="w")
        ttk.Label(layout_file_frame, textvariable=self.layout_file).grid(
            row=0, column=1, sticky="w", padx=(10, 0))
        for row, (caption, variable) in enumerate((
                ("Name:", self.layout_name),
                ("Description:", self.layout_description)), start=1):
            ttk.Label(layout_file_frame, text=caption).grid(
                row=row, column=0, sticky="nw", padx=(0, 5))
            ttk.Label(layout_file_frame, textvariable=variable, wraplength=380,
                      justify="left").grid(row=row, column=1, sticky="w")

        self.layout_content_frame = ttk.Frame(self.left_frame)
        self.layout_content_frame.pack(fill="x")

        self.scenario_panel_visible = False
        self.scenario_toggle_button = ttk.Button(
            self.right_frame, text="Scenario \u00bb", command=self._toggle_scenario_panel)
        self.scenario_toggle_button.pack(side="top")

        self.speed_frame_container = ttk.Frame(self.right_frame)
        self.speed_frame_container.pack(side="top")

        self._build_layout_ui()

        self.scenario_panel = ttk.LabelFrame(self.root, text="Scenario")

        self.scenario_open_button = ttk.Button(
            self.scenario_panel, text='Load from file', command=self.select_file)
        self.scenario_open_button.grid(row=0, column=0, padx=5)

        self.run_scenario_button = ttk.Button(
            self.scenario_panel, text="Run", command=self.run_scenario, state="disabled")
        self.run_scenario_button.grid(row=0, column=2, padx=5)
        self.stop_scenario_button = ttk.Button(
            self.scenario_panel, text="Stop", command=self.stop_scenario, state="disabled")
        self.stop_scenario_button.grid(row=0, column=3, padx=5)

        ttk.Label(self.scenario_panel, text="Times:").grid(
            row=0, column=4, sticky="e", padx=(15, 5))
        ttk.Button(self.scenario_panel, text="\u25bc", width=2,
                   command=self._decrement_scenario_times).grid(row=0, column=5)
        ttk.Label(self.scenario_panel, textvariable=self.scenario_times, width=3,
                  anchor="center").grid(row=0, column=6)
        ttk.Button(self.scenario_panel, text="\u25b2", width=2,
                   command=self._increment_scenario_times).grid(row=0, column=7)

        info_rows = [
            ("File:", self.scenario_file),
            ("Name:", self.scenario_name),
            ("Description:", self.scenario_description),
            ("Status:", self.scenario_status),
            ("Iteration:", self.scenario_iteration),
        ]
        for row, (caption, variable) in enumerate(info_rows, start=1):
            ttk.Label(self.scenario_panel, text=caption).grid(
                row=row, column=0, sticky="nw", padx=5, pady=(8, 0) if row == 1 else 0)
            ttk.Label(self.scenario_panel, textvariable=variable, wraplength=380,
                      justify="left").grid(
                row=row, column=1, columnspan=7, sticky="w", padx=5,
                pady=(8, 0) if row == 1 else 0)

        steps_frame = ttk.Frame(self.scenario_panel)
        steps_frame.grid(row=len(info_rows) + 1, column=0,
                         columnspan=8, sticky="nsew", pady=(10, 0))
        self.scenario_panel.rowconfigure(len(info_rows) + 1, weight=1)

        columns = ("number", "action", "device_type", "device_id", "value")
        self.steps_table = ttk.Treeview(
            steps_frame, columns=columns, show="headings", height=15, selectmode="none")
        for column, heading, width in (
                ("number", "#", 40),
                ("action", "Action", 110),
                ("device_type", "Device type", 210),
                ("device_id", "Device ID", 75),
                ("value", "Value", 60)):
            self.steps_table.heading(column, text=heading)
            self.steps_table.column(
                column, width=width, anchor="w" if column in ("action", "device_type") else "e")
        self.steps_table.tag_configure(
            "current", background="#ffe08a", foreground="black")
        steps_scrollbar = ttk.Scrollbar(
            steps_frame, orient="vertical", command=self.steps_table.yview)
        self.steps_table.configure(yscrollcommand=steps_scrollbar.set)
        self.steps_table.pack(side="left", fill="both", expand=True)
        steps_scrollbar.pack(side="right", fill="y")

        message_frame = ttk.LabelFrame(
            self.left_frame, text="Messages", padding=10)
        message_frame.pack(fill="x", padx=10, pady=5)
        self.message_label = ttk.Label(message_frame, text="")
        self.message_label.pack()

    def _build_layout_ui(self):
        self.layout_file.set(os.path.basename(self.layout_path) if self.layout_path else "")
        self.layout_name.set(self.layout.name)
        self.layout_description.set(self.layout.description)

        self._build_diagram()

        for device_type_name, component_list in self.layout.components.items():
            if device_type_name == DeviceType.TARGET_VOLTAGE.name:
                for component_id in component_list:
                    self._build_control_ui(component_id)
            elif device_type_name == DeviceType.SPEED.name:
                for component_id in component_list:
                    self._build_speed_ui(component_id)
            elif device_type_name == DeviceType.SENSOR.name:
                for component_id, sensor in component_list.items():
                    self._add_sensor_indicator(sensor)
            elif device_type_name == DeviceType.POINT_DIRECTION.name:
                for component_id, point in component_list.items():
                    self._build_point_diagram(point)

        self._update_electrified_segments()

    def _clear_layout_ui(self):
        for container in (self.layout_content_frame, self.speed_frame_container):
            for child in container.winfo_children():
                child.destroy()
        self.controls.clear()
        self.speed_displays.clear()
        self.sensor_indicators.clear()
        self.segments.clear()
        self.block_items.clear()

    def select_layout_file(self):
        if self.scenario_runner.is_running:
            self.set_message("warning", "Stop the running scenario before changing the layout")
            return
        initial_dir = os.path.dirname(self.layout_path) if self.layout_path else os.path.join("data", "layouts")
        filepath = fd.askopenfilename(title='Open a layout file', initialdir=initial_dir,
                                      filetypes=[('Layout files', '*.json *.yaml *.yml'), ('JSON files', '*.json'), ('YAML files', '*.yaml *.yml')])
        if len(filepath) > 0:
            self.load_layout_file(filepath)

    def load_layout_file(self, layout_path):
        try:
            data = load_data_from_file(layout_path)
        except Exception as exc:
            self.set_message("error", str(exc))
            return

        previous_data, previous_path = self.layout_data, self.layout_path
        ok, msg = self.layout.load(data)
        if ok:
            self.layout_data, self.layout_path = data, layout_path
            save_last_layout_path(layout_path)
            self.set_message("info", f"Layout loaded: {self.layout.name}")
        else:
            # Layout.load may have partially replaced components; restore the previous one.
            self.layout.load(previous_data)
            self.set_message("error", f"Layout failed to load: {msg}")
        self._clear_layout_ui()
        self._build_layout_ui()

    def _build_speed_ui(self, speed_trap_id: int):
        DASH_FONT = tkFont.Font(family="Menlo", size=30)
        speed_display = SpeedDisplay(speed_trap_id)

        dash_frame = ttk.LabelFrame(
            self.speed_frame_container, text=f"Speed trap {speed_trap_id}", padding=10)
        dash_frame.pack(side="top")

        speed_display.speed_label = ttk.Label(
            dash_frame, textvariable=speed_display.last_speed, font=DASH_FONT, width=5, justify=tk.CENTER)
        speed_display.speed_label.grid(row=0, column=0)
        ttk.Label(dash_frame, text="km/h", width=5,
                  justify=tk.LEFT).grid(row=1, column=0)
        self.speed_displays[speed_trap_id] = speed_display

    def _build_control_ui(self, track_id: int):
        DASH_FONT = tkFont.Font(family="Menlo", size=30)
        track_control = TrackControl(track_id, self.forward_message)
        self.controls[track_id] = track_control

        track_frame = ttk.LabelFrame(self.layout_content_frame, padding=10)
        track_frame.pack(fill="x", padx=10, pady=5)

        dash_frame = ttk.LabelFrame(
            track_frame, text=f"Track {track_id} Voltage", padding=0)
        dash_frame.pack(fill="x", padx=0, pady=0)
        ttk.Label(dash_frame, text="Direction").grid(row=0, column=0)
        ttk.Label(dash_frame, text="Target").grid(row=0, column=1)
        ttk.Label(dash_frame, text="Actual").grid(row=0, column=2)
        track_control.direction_label = ttk.Label(
            dash_frame, textvariable=track_control.direction, font=DASH_FONT, width=3, justify=tk.CENTER)
        track_control.direction_label.grid(row=1, column=0, padx=5)
        track_control.target_voltage_label = ttk.Label(
            dash_frame, textvariable=track_control.target_voltage, font=DASH_FONT, width=3, justify=tk.RIGHT)
        track_control.target_voltage_label.grid(row=1, column=1, padx=5)
        track_control.actual_voltage_label = ttk.Label(
            dash_frame, textvariable=track_control.actual_voltage, font=DASH_FONT, width=3, justify=tk.RIGHT)
        track_control.actual_voltage_label.grid(row=1, column=2, padx=5)

        control_frame = ttk.LabelFrame(track_frame, padding=0)
        control_frame.pack(fill="x", padx=0, pady=0)

        track_control.reverse_button = ttk.Button(
            control_frame, text="◀ REV", state="normal", command=track_control.set_reverse)
        track_control.reverse_button.grid(row=0, column=0, padx=2)
        track_control.forward_button = ttk.Button(
            control_frame, text="FWD ▶", state="disabled", command=track_control.set_forward)
        track_control.forward_button.grid(row=0, column=1, padx=2)

        track_control.control_buttons = []
        try:
            for idx, button in enumerate(self.buttons_data):
                voltage = button.get("value", 0)
                label = button.get("label", str(voltage))
                btn = ttk.Button(control_frame, text=label)
                btn.grid(row=1, column=idx, padx=2)
                track_control.control_buttons.append(btn)
                btn.config(command=lambda v=voltage,
                           b=btn: track_control.set_voltage(v, b))
        except Exception as e:
            print(f"Error building control buttons: {e}")

        message_frame = ttk.LabelFrame(track_frame, padding=0)
        message_frame.pack(fill="x", padx=0, pady=0)
        track_control.message_label = ttk.Label(message_frame, text="")
        track_control.message_label.pack()

    def _build_diagram(self):
        if self.layout.diagram_data is None:
            return
        try:
            self.canvas = tk.Canvas(self.layout_content_frame, width=self.diagram_config.canvas_width,
                                    height=self.diagram_config.canvas_height)
            segments: list = self.layout.diagram_data.get("segments")
            for s in segments:
                if s["shape"] == "straight":
                    segment = self.canvas.create_line(
                        s["start_point"][0], s["start_point"][1], s["end_point"][0], s["end_point"][1], width=self.diagram_config.line_width)
                    self.segments[s["id"]] = "straight", segment
                elif s["shape"] == "curve":
                    segment = self.canvas.create_line(
                        *diagram_helper.curve_to_line_points(s), smooth=True, splinesteps=48, width=self.diagram_config.line_width)
                    self.segments[s["id"]] = "curve", segment
                # self.canvas.create_text(s["start_point"][0], s["start_point"][1], text=str(s["id"]), fill="red")
                if s.get("feeder") == True:
                    segment_center = diagram_helper.center_point(s)
                    self.canvas.create_polygon(diagram_helper.feeder_symbol(
                        segment_center[0], segment_center[1]), fill=self.diagram_config.electrified_color, outline=self.diagram_config.symbol_outline_color, width=self.diagram_config.symbol_outline_width)
                self.canvas.pack()
            self._draw_blocks(segments)
        except Exception as exc:
            print(f"Error drawing diagram: {str(exc)}")

    def _draw_blocks(self, diagram_segments: list):
        segments_by_id = {s["id"]: s for s in diagram_segments}
        for block in self.layout.components[DeviceType.BLOCK.name].values():
            color = self._block_color(block.occupied)
            items = []
            for segment_id in block.segment_ids:
                s = segments_by_id[segment_id]
                width = self.diagram_config.block_width
                if s["shape"] == "straight":
                    items.append(self.canvas.create_line(
                        s["start_point"][0], s["start_point"][1], s["end_point"][0], s["end_point"][1],
                        width=width, fill=color, tags="block"))
                elif s["shape"] == "curve":
                    items.append(self.canvas.create_line(
                        *diagram_helper.curve_to_line_points(s), smooth=True,
                        width=width, fill=color, tags="block"))
            self.block_items[block.id] = items
        self.canvas.tag_lower("block")

    def _block_color(self, occupied: bool) -> str:
        return self.diagram_config.block_occupied_color if occupied else self.diagram_config.block_unoccupied_color

    def _update_block_diagram(self, block_id: int):
        block = self.layout.components[DeviceType.BLOCK.name][block_id]
        for item in self.block_items.get(block_id, []):
            self.canvas.itemconfig(item, fill=self._block_color(block.occupied))

    def _build_point_diagram(self, point: Point):
        try:
            def updateLambda(
                p): return self._switch_point_direction(point=point)
            for direction_segment_id in point.direction_segments:
                self.canvas.tag_bind(
                    self.segments[direction_segment_id][1], '<Button-1>', updateLambda)
            self._update_point_diagram(point)
        except Exception as exc:
            print(f"Error building point: {point}")

    def _switch_point_direction(self, point: Point):
        # TODO: move to railway/layout?
        try:
            for index in range(len(point.direction_segments)):
                if index != point.direction:
                    message = Message(
                        message_type=MessageType.SET,
                        device_type=DeviceType.POINT_DIRECTION,
                        device_id=point.id,
                        value=index
                    )
                    ok, msg = self.layout.command(message)

                    if not ok:
                        print(f"_switch_point_direction error: {msg}")
                        self.set_message("error", msg)
                    return
        except Exception as exc:
            print(f"_switch_point_direction exception: {str(exc)}")

    def _update_point_diagram(self, point: Point):
        try:
            for index, segment_id in enumerate(point.direction_segments):
                if index == point.direction:
                    self.canvas.itemconfig(
                        self.segments[segment_id][1], width=self.diagram_config.line_width_point_active)
                    self.canvas.tag_raise(self.segments[segment_id][1])
                else:
                    self.canvas.itemconfig(
                        self.segments[segment_id][1], width=self.diagram_config.line_width)
        except Exception as exc:
            print(f"Failed to update point diagram: {str(exc)}")

    def _add_sensor_indicator(self, sensor: Sensor):
        s = self.layout.node_location(sensor.node)
        if s is None:
            return
        try:
            sensor_indicator_id = self.canvas.create_oval(
                diagram_helper.round_symbol(s[0], s[1], self.diagram_config.symbol_diameter), fill=self.diagram_config.symbol_fill_color)
            self.canvas.create_text(s[0], s[1], text=f"S{sensor.id}", fill=self.diagram_config.symbol_text_color)
            self.sensor_indicators[sensor.id] = sensor_indicator_id
        except Exception as exc:
            print(f"Error drawing sensor: {str(exc)}")

    def _update_electrified_segments(self):
        try:
            electrified_segments = self.layout.electrified_segments()
            for segment in self.segments.values():
                self.canvas.itemconfig(
                    segment[1], fill=self.diagram_config.line_color, arrow=tk.NONE)
            for track_id, track_segment_ids in electrified_segments.items():
                track = self.layout.components[DeviceType.TARGET_VOLTAGE.name][track_id]
                # Lines are drawn from the segment's start to its end, the direction of positive voltage
                arrow = {1: tk.LAST, -1: tk.FIRST}.get(track.actual_direction, tk.NONE)
                for segment_id in track_segment_ids:
                    self.canvas.itemconfig(
                        self.segments[segment_id][1], fill=self.diagram_config.electrified_color, arrow=arrow)
        except Exception as exc:
            print(f"_update_electrified_segments exception: {str(exc)}")

    def select_file(self):
        filepath = fd.askopenfilename(title='Open a file', initialdir=os.path.join(
            "data", "scenarios"), filetypes=[('Scenario files', '*.json *.yaml *.yml'), ('JSON files', '*.json'), ('YAML files', '*.yaml *.yml')])
        if len(filepath) > 0:
            self.load_scenario_file(filepath)

    def load_scenario_file(self, scenario_path):
        try:
            from util import load_data_from_file
            data = load_data_from_file(scenario_path)
        except Exception as exc:
            self.set_message("error", str(exc))
            return

        ok, msg = self.scenario_runner.load_scenario(data)
        if ok:
            scenario = self.scenario_runner.scenario
            self.scenario_file.set(os.path.basename(scenario_path))
            self.scenario_name.set(scenario.name)
            self.scenario_description.set(scenario.description)
            self.scenario_iteration.set("")
            self._populate_steps_table(scenario.steps)
            self.scenario_times.set(scenario.times)
            self.set_message(
                "info", f"Scenario loaded: {data.get('name', self.scenario_runner.scenario.name)}")
        else:
            self.set_message("error", f"Scenario failed to load: {msg}")

    def _increment_scenario_times(self):
        self.scenario_times.set(self.scenario_times.get() + 1)
        self._apply_scenario_times()

    def _decrement_scenario_times(self):
        if self.scenario_times.get() > 1:
            self.scenario_times.set(self.scenario_times.get() - 1)
            self._apply_scenario_times()

    def _apply_scenario_times(self):
        if self.scenario_runner and self.scenario_runner.scenario:
            self.scenario_runner.scenario.times = self.scenario_times.get()

    def _populate_steps_table(self, steps):
        self.steps_table.delete(*self.steps_table.get_children())
        self._highlighted_step_iid = None
        for index, step in enumerate(steps):
            self.steps_table.insert("", "end", iid=str(index), values=(
                index + 1,
                step.action,
                step.device_type or "",
                "" if step.device_id is None else step.device_id,
                step.value))

    def _highlight_step(self, step):
        if self._highlighted_step_iid is not None:
            self.steps_table.item(self._highlighted_step_iid, tags=())
            self._highlighted_step_iid = None
        if step is None:
            return
        # Steps can be textually identical, so match on object identity.
        for index, candidate in enumerate(self.scenario_runner.scenario.steps):
            if candidate is step:
                iid = str(index)
                self.steps_table.item(iid, tags=("current",))
                self.steps_table.see(iid)
                self._highlighted_step_iid = iid
                break

    def _toggle_scenario_panel(self):
        if self.scenario_panel_visible:
            self.scenario_panel.pack_forget()
            self.scenario_toggle_button.config(text="Scenario \u00bb")
        else:
            self.scenario_panel.pack(side="right", fill="y", before=self.right_frame)
            # Force a redraw; on macOS the re-mapped panel's children stay blank otherwise.
            self.root.update_idletasks()
            self.scenario_toggle_button.config(text="Scenario \u00ab")
        self.scenario_panel_visible = not self.scenario_panel_visible

    def run_scenario(self):
        if not self.scenario_runner:
            self.set_message("warning", "Load a scenario first")
            return
        if self.scenario_runner.is_running:
            self.set_message("info", "Scenario already running")
            return

        self.stop_scenario_button.config(state="normal")
        self.scenario_runner.start()

    def stop_scenario(self):
        if self.scenario_runner is not None:
            self.scenario_runner.stop()
        self.stop_scenario_button.config(state="disabled")
        self.set_message("warning", "Stopping scenario")

    def _toggle_test_mode(self):
        self.layout.test_mode = self.test_mode_var.get()
        self.set_message("info", "Test mode: points switch without a serial connection"
                         if self.layout.test_mode else "")

    def connect_serial(self):
        self.set_message()
        try:
            port = self.port_var.get()
            ok, msg = self.layout.communicator.connect(port)
            if ok:
                self.connect_button.config(state="disabled")
                self.status_label.config(text="Connected", foreground="green")
                self.message_label.config(text="")
            else:
                raise RuntimeError(msg)
        except Exception as e:
            self.connect_button.config(state="normal")
            self.set_message("error", str(e))

    def set_message(self, level="", message=""):
        """Display a message in the message label with a given level (info, warning, error)."""
        if level == "info":
            self.message_label.config(text=message, foreground="")
        elif level == "warning":
            self.message_label.config(text=message, foreground="orange")
        elif level == "error":
            self.message_label.config(text=message, foreground="red")
        else:
            self.message_label.config(text=message, foreground="")

    def _on_scenario_event(self, name, value):
        def apply_event():
            if name == "scenario_state":
                if value == None:
                    self.scenario_status.set("")
                    self.scenario_iteration.set("")
                    self._highlight_step(None)
                    self.run_scenario_button.config(state="disabled")
                    self.stop_scenario_button.config(state="disabled")
                    return
                scenario_state: ScenarioState = value
                if scenario_state.status == ScenarioStatus.READY:
                    self.run_scenario_button.config(state="normal")
                    self.stop_scenario_button.config(state="disabled")
                elif scenario_state.status == ScenarioStatus.RUNNING:
                    self.run_scenario_button.config(state="disabled")
                    self.stop_scenario_button.config(state="normal")
                elif scenario_state.status == ScenarioStatus.ERROR:
                    self.run_scenario_button.config(state="normal")
                    self.stop_scenario_button.config(state="disabled")
                    self.set_message("error", scenario_state.message)
                status_text = scenario_state.status.value
                if scenario_state.message:
                    status_text += f" - {scenario_state.message}"
                self.scenario_status.set(status_text)
                if scenario_state.iteration is not None:
                    self.scenario_iteration.set(
                        f"{scenario_state.iteration} of {self.scenario_runner.scenario.times}")
                elif scenario_state.status == ScenarioStatus.READY and not scenario_state.message:
                    self.scenario_iteration.set("")
                self._highlight_step(scenario_state.step)

        self.root.after(0, apply_event)

    def _on_event(self, name: str, value: object):
        def apply_event():
            if name == "component":
                try:
                    message: Message = value
                    self._handle_component_event(message)
                except Exception as exc:
                    self.set_message(
                        "error", f"Error handling component event: {str(exc)}")
            elif name == "status":
                txt = str(value).capitalize()
                fg = "green" if str(value).lower() == "connected" else "red"
                self.status_label.config(text=txt, foreground=fg)
                if str(value).lower() == "disconnected":
                    self.connect_button.config(state="normal")

        self.root.after(0, apply_event)

    def _handle_component_event(self, message: Message) -> Tuple[bool, str]:
        if message.device_type == DeviceType.ACTUAL_VOLTAGE:
            control = self.controls.get(message.device_id)
            if not control is None:
                control.actual_voltage.set(abs(message.value))
                self._update_electrified_segments()
            else:
                self.set_message("error", f"Unknown track id: {message}")
                return False, "Unknown device id"
        elif message.device_type == DeviceType.TARGET_VOLTAGE:
            control = self.controls.get(message.device_id)
            if not control is None:
                control.target_voltage.set(abs(message.value))
            else:
                self.set_message("error", f"Unknown track id: {message}")
                return False, "Unknown device id"
        elif message.device_type == DeviceType.SPEED:
            speed_display = self.speed_displays.get(message.device_id)
            if not speed_display is None:
                # convert to scale in km/h
                speed: float = float(message.value) * \
                    self.layout.scale * 0.0036
                speed_display.last_speed.set(speed)
        elif message.device_type == DeviceType.BLOCK:
            self._update_block_diagram(message.device_id)
        elif message.device_type == DeviceType.SENSOR:
            sensor_indicator = self.sensor_indicators.get(message.device_id)
            if not sensor_indicator is None:
                if message.value == 1:
                    self.canvas.itemconfig(
                        sensor_indicator, fill=self.diagram_config.symbol_active_color)
                elif message.value == 0:
                    def sensor_indicator_off():
                        self.canvas.itemconfig(
                            sensor_indicator, fill=self.diagram_config.symbol_fill_color)
                    self.root.after(100, sensor_indicator_off)
        elif message.device_type == DeviceType.POINT_DIRECTION or \
             message.device_type == DeviceType.POINT_DIRECTION_SKIP_CHECK:
            try:
                point = self.layout.components[DeviceType.POINT_DIRECTION.name][message.device_id]
                self._update_point_diagram(point)
                self._update_electrified_segments()
            except Exception as exc:
                print(f"_handle_component_event POINT exception: {str(exc)}")
                return False, str(exc)
        else:
            return False, "Unknown device type"

        return True, ""

    def forward_message(self, message: Message) -> Tuple[bool, str]:
        return self.layout.command(message)


if __name__ == "__main__":
    # Load configuration outside the GUI and inject it — keeps GUI thin and testable
    try:
        from util import load_data_from_file
        buttons = load_data_from_file("config/control_buttons.json")
    except FileNotFoundError:
        print("control_buttons.json not found. Using no buttons.")
        buttons = []
    except Exception as e:
        print(f"Error loading control_buttons.json: {e}")
        buttons = []

    layout = None
    layout_path = None
    for candidate in (load_last_layout_path(), DEFAULT_LAYOUT_PATH):
        if not candidate:
            continue
        try:
            layout = load_data_from_file(candidate)
            layout_path = candidate
            break
        except Exception as e:
            print(f"Error loading layout {candidate}: {e}")

    if layout is None:
        raise SystemExit("No layout could be loaded")

    root = tk.Tk()
    app = TrainController(root, layout_data=layout, buttons_data=buttons,
                          layout_path=layout_path)
    root.mainloop()
