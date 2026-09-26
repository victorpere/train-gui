import os
from time import time
from typing import Tuple, Protocol
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog as fd
from tkinter.ttk import Button
import tkinter.font as tkFont
from scenario import ScenarioRunner, ScenarioState, ScenarioStatus
from railway import Layout, Message, MessageType, DeviceType
from communication import Communicator


class ControllerCallback(Protocol):
    def __call__(self, message: Message) -> Tuple[bool, str]: ...


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
            message_type = MessageType.SET,
            device_type = DeviceType.TARGET_VOLTAGE,
            device_id = self.track_id,
            value = directional_voltage
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
    def __init__(self, root, layout_data, buttons_data=None):
        self.root = root
        self.root.title("N-Scale Train Controller")

        communicator = Communicator()
        self.layout = Layout(communicator)
        self.layout.add_listener(self._on_event)
        layout_ok, layout_msg = self.layout.load(layout_data)

        if not layout_ok:
            print(f"train_gui layout load failed: {layout_msg}")
            return

        self.buttons_data = buttons_data or []

        self.sensor_message = tk.StringVar()
        self.sensor_message.set("")
        self._last_sensor_event_time = -1

        self.scenario_runner = ScenarioRunner(layout=self.layout)
        self.scenario_runner.add_listener(self._on_scenario_event)
        self.scenario_name = tk.StringVar()
        self.scenario_status = tk.StringVar(value="")
        self.scenario_step = tk.StringVar(value="")

        self.controls: dict[int, TrackControl] = {}

        self.build_ui()

    def build_ui(self):
        # Serial connection frame
        conn_frame = ttk.LabelFrame(self.root, text="Serial Connection", padding=10)
        conn_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(conn_frame, text="Port:").grid(row=0, column=0)
        self.port_var = tk.StringVar(value="/dev/cu.usbmodem1301")  # Mac default; change as needed
        ttk.Entry(conn_frame, textvariable=self.port_var, width=20).grid(row=0, column=1)
        
        self.connect_button = ttk.Button(conn_frame, text="Connect", command=self.connect_serial)
        self.connect_button.grid(row=0, column=2, padx=5)
        self.status_label = ttk.Label(conn_frame, text="Disconnected", foreground="red")
        self.status_label.grid(row=0, column=3)       


        for device_type_name, component_list in self.layout.components.items():
            if device_type_name == DeviceType.TARGET_VOLTAGE.name:
                for component_id in component_list:
                    self._build_control_ui(component_id)


        scenario_frame = ttk.LabelFrame(self.root, text="Scenario", padding=10)
        scenario_frame.pack(fill="x", padx=10, pady=5)

        self.scenario_open_button = ttk.Button(scenario_frame, text='Load from file', command=self.select_file)
        self.scenario_open_button.grid(row=0, column=0, padx=5)

        self.run_scenario_button = ttk.Button(scenario_frame, text="Run", command=self.run_scenario, state="disabled")
        self.run_scenario_button.grid(row=0, column=2, padx=5)
        self.stop_scenario_button = ttk.Button(scenario_frame, text="Stop", command=self.stop_scenario, state="disabled")
        self.stop_scenario_button.grid(row=0, column=3, padx=5)

        ttk.Label(scenario_frame, text="Status:").grid(row=1, column=0, sticky="w", padx=5)
        self.scenario_status_label = ttk.Label(scenario_frame, textvariable=self.scenario_status)
        self.scenario_status_label.grid(row=1, column=1, columnspan=3, sticky="w", padx=5)

        ttk.Label(scenario_frame, text="Current step:").grid(row=2, column=0, sticky="w", padx=5)
        self.scenario_step_label = ttk.Label(scenario_frame, textvariable=self.scenario_step)
        self.scenario_step_label.grid(row=2, column=1, columnspan=3, sticky="w", padx=5)

        message_frame = ttk.LabelFrame(self.root, text="Messages", padding=10)
        message_frame.pack(fill="x", padx=10, pady=5)
        self.message_label = ttk.Label(message_frame, text="")
        self.message_label.pack()


    def _build_control_ui(self, track_id: int):
        DASH_FONT = tkFont.Font(family="Menlo", size=30)
        track_control = TrackControl(track_id, self.forward_message)
        self.controls[track_id] = track_control

        dash_frame = ttk.LabelFrame(self.root, text=f"Track {track_id}", padding=10)
        dash_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(dash_frame, text="Direction").grid(row=0, column=0)
        ttk.Label(dash_frame, text="Target").grid(row=0, column=1)
        ttk.Label(dash_frame, text="Actual").grid(row=0, column=2)
        track_control.direction_label = ttk.Label(dash_frame, textvariable=track_control.direction, font=DASH_FONT, width=3, justify=tk.CENTER)
        track_control.direction_label.grid(row=1, column=0, padx=5)
        track_control.target_voltage_label = ttk.Label(dash_frame, textvariable=track_control.target_voltage, font=DASH_FONT, width=3, justify=tk.RIGHT)
        track_control.target_voltage_label.grid(row=1, column=1, padx=5)
        track_control.actual_voltage_label = ttk.Label(dash_frame, textvariable=track_control.actual_voltage, font=DASH_FONT, width=3, justify=tk.RIGHT)
        track_control.actual_voltage_label.grid(row=1, column=2, padx=5)

        control_frame = ttk.LabelFrame(self.root, text="", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)

        track_control.reverse_button = ttk.Button(control_frame, text="◀ REV", state="normal", command=track_control.set_reverse)
        track_control.reverse_button.grid(row=0, column=0, padx=2)
        track_control.forward_button = ttk.Button(control_frame, text="FWD ▶", state="disabled", command=track_control.set_forward)
        track_control.forward_button.grid(row=0, column=1, padx=2)

        track_control.control_buttons = []
        try:
            for idx, button in enumerate(self.buttons_data):
                voltage = button.get("value", 0)
                label = button.get("label", str(voltage))
                btn = ttk.Button(control_frame, text=label)
                btn.grid(row=1, column=idx, padx=2)
                track_control.control_buttons.append(btn)
                btn.config(command=lambda v=voltage, b=btn: track_control.set_voltage(v, b))
        except Exception as e:
            print(f"Error building control buttons: {e}")

        message_frame = ttk.LabelFrame(self.root, text=f"Track {track_id} messages", padding=10)
        message_frame.pack(fill="x", padx=10, pady=5)
        track_control.message_label = ttk.Label(message_frame, text="")
        track_control.message_label.pack()


    def select_file(self):
        filepath = fd.askopenfilename(title='Open a file', initialdir=os.path.join("data", "scenarios"), filetypes=[('JSON files', '*.json')])
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
            self.scenario_step.set("")
            self.set_message("info", f"Scenario loaded: {data.get('name', self.scenario_runner.scenario.name)}")
        else:
            self.set_message("error", f"Scenario failed to load: {msg}")
        
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
                    self.scenario_step.set("")
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
                self.scenario_status.set(f"{scenario_state.status.value} {self.scenario_runner.scenario.name}")
                if scenario_state.step is not None:
                    self.scenario_step.set(str(scenario_state.step.name))
                else:
                    self.scenario_step.set("")

        self.root.after(0, apply_event)

    def _on_event(self, name: str, value: object):
        def apply_event():
            if name == "component":
                try:
                    message: Message = value
                    self._handle_component_event(message)
                except Exception as exc:
                    self.set_message("error", f"Error handling component event: {str(exc)}")
            elif name == "status":
                txt = str(value).capitalize()
                fg = "green" if str(value).lower() == "connected" else "red"
                self.status_label.config(text=txt, foreground=fg)

        self.root.after(0, apply_event)

    def _handle_component_event(self, message: Message) -> Tuple[bool, str]:
        if message.device_type == DeviceType.ACTUAL_VOLTAGE:
            control = self.controls.get(message.device_id)
            if not control is None:
                control.actual_voltage.set(abs(message.value))
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
        elif message.device_type == DeviceType.SENSOR:
            print(f"Sensor event received: {message.value}")
            if message.value == 1:
                sensor_event_time = int(time() * 1000)
                if self._last_sensor_event_time != -1:
                    elapsed_time = sensor_event_time - self._last_sensor_event_time
                    print(f"Last lap time: {elapsed_time} ms")
                    
                    # speed in mm per second
                    speed = self.layout.length / elapsed_time  # length per second

                    # prototype speed in km/h
                    prototype_speed = speed * self.layout.scale * 3.6  # convert mm/s to km/h

                    self.set_message("info", f"Prototype speed: {prototype_speed:.1f} km/h")
                self._last_sensor_event_time = sensor_event_time
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

    try:
        from util import load_data_from_file
        layout = load_data_from_file("data/layouts/layout01.json")
    except Exception as e:
        print(f"Error loading layout01.json: {e}")

    root = tk.Tk()
    app = TrainController(root, layout_data=layout, buttons_data=buttons)
    root.mainloop()
