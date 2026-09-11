import glob
import os
import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Button
import tkinter.font as tkFont
from scenario_runner import ScenarioRunner
from track import Track


class TrainController:
    def __init__(self, root, track=None, buttons_data=None):
        self.root = root
        self.root.title("N-Scale Train Controller")
        self.track = track or Track()
        self.track.add_listener(self._on_track_event)
        self.buttons_data = buttons_data or []
        self.direction = tk.IntVar()
        self.direction.set(1)

        self.target_voltage = tk.IntVar()
        self.target_voltage.set(0)

        self.actual_voltage = tk.IntVar()
        self.actual_voltage.set(0)

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
        self.scenario_status_label = ttk.Label(scenario_frame, textvariable=self.scenario_status, foreground="blue")
        self.scenario_status_label.grid(row=1, column=1, columnspan=3, sticky="w", padx=5)

        ttk.Label(scenario_frame, text="Current step:").grid(row=2, column=0, sticky="w", padx=5)
        self.scenario_step_label = ttk.Label(scenario_frame, textvariable=self.scenario_step, foreground="darkgreen")
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

        self.scenario_runner = ScenarioRunner(data, track=self.track)
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
            ok, msg = self.track.connect(port)
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
        ok, msg = self.track.set_voltage(directional_voltage)
        if ok:
            self.target_voltage.set(voltage)
            self.reset_buttons()
            button_pressed.config(state="disabled")
        else:
            self.set_message("error", msg)
            self.connect_button.config(state="normal")
            self.status_label.config(text="Disconnected", foreground="red")
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
            self.message_label.config(text=message, foreground="blue")
        elif level == "warning":
            self.message_label.config(text=message, foreground="orange")
        elif level == "error":
            self.message_label.config(text=message, foreground="red")
        else:
            self.message_label.config(text=message, foreground="black")

    def reset_buttons(self):
        for btn in self.control_buttons:
            btn.config(state="normal")

    def _on_scenario_event(self, name, value):
        def apply_event():
            if name == "scenario_step":
                self.scenario_step.set(str(value) if value else "")
            elif name == "scenario_status":
                self.scenario_status.set(str(value))

        self.root.after(0, apply_event)

    def _on_track_event(self, name, value):
        def apply_event():
            if name == "actual_voltage":
                self.actual_voltage.set(abs(value))
            elif name == "target_voltage":
                self.target_voltage.set(abs(value))
            elif name == "status":
                txt = str(value).capitalize()
                fg = "green" if str(value).lower() == "connected" else "red"
                self.status_label.config(text=txt, foreground=fg)

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

    root = tk.Tk()
    app = TrainController(root, buttons_data=buttons)
    root.mainloop()
