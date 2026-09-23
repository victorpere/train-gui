import glob
import os
from time import time
import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Button
import tkinter.font as tkFont
from scenario import ScenarioRunner, ScenarioState
from railway import Layout, Message, MessageType, DeviceType
from communication import Communicator


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
        self.direction = tk.IntVar()
        self.direction.set(1)

        self.target_voltage = tk.IntVar()
        self.target_voltage.set(0)

        self.actual_voltage = tk.IntVar()
        self.actual_voltage.set(0)

        self.sensor_message = tk.StringVar()
        self.sensor_message.set("")
        self._last_sensor_event_time = -1

        self.scenario_runner = None
        self.scenario_files = self._discover_scenarios()
        self.scenario_name = tk.StringVar()
        self.scenario_status = tk.StringVar(value="No scenario loaded")
        self.scenario_step = tk.StringVar(value="")

        self.build_ui()

    def _discover_scenarios(self):
        pattern = os.path.join("data", "scenarios", "*.json")
        return sorted(glob.glob(pattern))

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

        dash_font = tkFont.Font(family="Menlo", size=30)
        dash_frame = ttk.LabelFrame(self.root, text="Voltage", padding=10)
        dash_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(dash_frame, text="Direction").grid(row=0, column=0)
        ttk.Label(dash_frame, text="Target").grid(row=0, column=1)
        ttk.Label(dash_frame, text="Actual").grid(row=0, column=2)
        self.direction_label = ttk.Label(dash_frame, textvariable=self.direction, font=dash_font, width=3, justify=tk.CENTER)
        self.direction_label.grid(row=1, column=0, padx=5)
        self.target_voltage_label = ttk.Label(dash_frame, textvariable=self.target_voltage, font=dash_font, width=3, justify=tk.RIGHT)
        self.target_voltage_label.grid(row=1, column=1, padx=5)
        self.actual_voltage_label = ttk.Label(dash_frame, textvariable=self.actual_voltage, font=dash_font, width=3, justify=tk.RIGHT)
        self.actual_voltage_label.grid(row=1, column=2, padx=5)
        self.sensor_label = ttk.Label(dash_frame, textvariable=self.sensor_message, font=dash_font, foreground="red")
        self.sensor_label.grid(row=1, column=3, padx=5)

        control_frame = ttk.LabelFrame(self.root, text="Control", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)

        self.reverse_button = ttk.Button(control_frame, text="◀ REV", state="normal", command=self.set_reverse)
        self.reverse_button.grid(row=0, column=0, padx=2)
        self.forward_button = ttk.Button(control_frame, text="FWD ▶", state="disabled", command=self.set_forward)
        self.forward_button.grid(row=0, column=1, padx=2)

        self.control_buttons = []
        try:
            for idx, button in enumerate(self.buttons_data):
                voltage = button.get("value", 0)
                label = button.get("label", str(voltage))
                btn = ttk.Button(control_frame, text=label)
                btn.grid(row=1, column=idx, padx=2)
                self.control_buttons.append(btn)
                btn.config(command=lambda v=voltage, b=btn: self.set_voltage(v, b))
        except Exception as e:
            print(f"Error building control buttons: {e}")

        scenario_frame = ttk.LabelFrame(self.root, text="Scenario", padding=10)
        scenario_frame.pack(fill="x", padx=10, pady=5)

        scenario_names = [os.path.basename(path) for path in self.scenario_files]
        self.scenario_combo = ttk.Combobox(scenario_frame, values=scenario_names, state="readonly", width=30)
        if scenario_names:
            self.scenario_combo.current(0)
        self.scenario_combo.grid(row=0, column=0, padx=5, pady=5)

        self.load_scenario_button = ttk.Button(scenario_frame, text="Load", command=self.load_scenario)
        self.load_scenario_button.grid(row=0, column=1, padx=5)
        self.run_scenario_button = ttk.Button(scenario_frame, text="Run", command=self.run_scenario)
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
    
    def load_scenario(self):
        selected = self.scenario_combo.get()
        if not selected:
            self.set_message("warning", "No scenario selected")
            return

        scenario_path = os.path.join("data", "scenarios", selected)
        try:
            from util import load_data_from_file
            data = load_data_from_file(scenario_path)
        except Exception as exc:
            self.set_message("error", str(exc))
            return

        self.scenario_runner = ScenarioRunner(data, layout=self.layout)
        self.scenario_runner.add_listener(self._on_scenario_event)
        self.scenario_name.set(data.get("name", selected))
        self.scenario_status.set(f"Loaded {data.get('name', selected)}")
        self.scenario_step.set("")
        self.set_message("info", f"Scenario loaded: {data.get('name', selected)}")

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

    def set_voltage(self, voltage, button_pressed: Button):
        self.set_message()
        directional_voltage = voltage * self.direction.get()

        message = Message(
            message_type = MessageType.SET,
            device_type = DeviceType.TARGET_VOLTAGE,
            device_id = 1,
            value = directional_voltage
        )

        ok, msg = self.layout.command(message)

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
        """Display a message in the message label with a given level (info, warning, error)."""
        if level == "info":
            self.message_label.config(text=message, foreground="")
        elif level == "warning":
            self.message_label.config(text=message, foreground="orange")
        elif level == "error":
            self.message_label.config(text=message, foreground="red")
        else:
            self.message_label.config(text=message, foreground="")

    def reset_buttons(self):
        for btn in self.control_buttons:
            btn.config(state="normal")

    def _on_scenario_event(self, name, value):
        def apply_event():
            if name == "scenario_step":
                self.scenario_step.set(str(value) if value else "")
            elif name == "scenario_status":
                self.scenario_status.set(str(value))
                if str(value).startswith("Completed"):
                    self.stop_scenario_button.config(state="disabled")
            elif name == "scenario_state":
                scenario_state: ScenarioState = value
                self.scenario_status.set(f"{scenario_state.status.value} {self.scenario_runner.scenario.name}")
                if scenario_state.step is not None:
                    self.scenario_step.set(str(scenario_state.step.name))
                else:
                    self.scenario_step.set("")

        self.root.after(0, apply_event)

    def _on_event(self, name: str, value: object):
        def apply_event():
            if name == "actual_voltage":
                self.actual_voltage.set(abs(value))
            elif name == "target_voltage":
                self.target_voltage.set(abs(value))
            elif name == "status":
                txt = str(value).capitalize()
                fg = "green" if str(value).lower() == "connected" else "red"
                self.status_label.config(text=txt, foreground=fg)
            elif name == "sensor":
                print(f"Sensor event received: {value}")
                if value == 1:
                    self.sensor_message.set("TRAIN DETECTED")
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
                    def clear_message():
                        self.sensor_message.set("")
                    self.root.after(2000, clear_message)

        self.root.after(0, apply_event)


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
