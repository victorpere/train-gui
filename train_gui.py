import time
import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Button
import tkinter.font as tkFont
import serial
from threading import Thread
from util import load_data_from_file

class TrainController:
    def __init__(self, root):
        self.root = root
        self.root.title("N-Scale Train Controller")
        
        self.ser = None

        self.direction = tk.IntVar()
        self.direction.set(1)  # 1 for forward, -1 for backward

        self.target_voltage = tk.IntVar()  # selected target voltage
        self.target_voltage.set(0)

        self.actual_voltage = tk.IntVar()  # current voltage from Arduino
        self.actual_voltage.set(0)

        self.reading_serial = False  # Flag to control serial reading thread
        
        # Build GUI
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

        # Dashboard frame
        dash_font = tkFont.Font(family="Menlo", size=30)
        dash_frame = ttk.LabelFrame(self.root, text="Voltage", padding = 10)
        dash_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(dash_frame, text="Target").grid(row=0, column=0)
        ttk.Label(dash_frame, text="Actual").grid(row=0, column=1)
        self.target_voltage_label = ttk.Label(dash_frame, textvariable=self.target_voltage, font=dash_font, width=3, justify=tk.RIGHT)
        self.target_voltage_label.grid(row=1, column=0, padx=5)
        self.actual_voltage_label = ttk.Label(dash_frame, textvariable=self.actual_voltage, font=dash_font, width=3, justify=tk.RIGHT)
        self.actual_voltage_label.grid(row=1, column=1, padx=5)
        # Control frame
        control_frame = ttk.LabelFrame(self.root, text="Control", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)
        
        # Direction buttons
        self.reverse_button = ttk.Button(control_frame, text="◀ REV", state="normal", command=self.set_reverse)
        self.reverse_button.grid(row=0, column=0, padx=2)
        self.forward_button = ttk.Button(control_frame, text="FWD ▶", state="disabled", command=self.set_forward)
        self.forward_button.grid(row=0, column=1, padx=2)

        # Voltage control buttons
        self.control_buttons = []
        try:
            buttons_data = load_data_from_file("control_buttons.json")
            for idx, button in enumerate(buttons_data):
                voltage = button.get("value", 0)
                label = button.get("label", str(voltage))
                btn = ttk.Button(control_frame, text=label, command=lambda v=voltage, b=idx: self.set_voltage(v, self.control_buttons[b]))
                btn.grid(row=1, column=idx, padx=2)
                self.control_buttons.append(btn)
        except FileNotFoundError:
            print("control_buttons.json not found. Please ensure the file exists.")
        except Exception as e:
            print(f"Error loading control_buttons.json: {e}")

        # Message frame
        message_frame = ttk.LabelFrame(self.root, text="Messages", padding=10)
        message_frame.pack(fill="x", padx=10, pady=5)
        self.message_label = ttk.Label(message_frame, text="")
        self.message_label.pack()
    
    def connect_serial(self):
        self.set_message()
        try:
            port = self.port_var.get()
            self.ser = serial.Serial(port, 9600, timeout=1)
            self.connect_button.config(state="disabled")
            self.status_label.config(text="Connected", foreground="green")
            self.message_label.config(text="")

            # Start serial reading thread
            self.reading_serial = True
            serial_thread = Thread(target=self.read_serial, daemon=True)
            serial_thread.start()
        except Exception as e:
            self.connect_button.config(state="normal")
            self.set_message("error", str(e))

    def set_voltage(self, voltage, button_pressed: Button):
        self.set_message()
        directional_voltage = voltage * self.direction.get()
        if self.write_serial(directional_voltage):
            self.target_voltage.set(voltage)  # Store the voltage           
            # Update button states
            self.reset_buttons()
            button_pressed.config(state="disabled")
        else:
            self.set_message("error", "Serial connection not established")
            self.connect_button.config(state="normal")
            self.status_label.config(text="Disconnected", foreground="red")
            self.reset_buttons()
        
    def set_forward(self):
        self.set_message()
        if self.direction.get() == 1:
            self.set_message("info", "Already moving forward")
            return  # Already moving forward
        if self.target_voltage.get() != 0 or self.actual_voltage.get() != 0:
            self.set_message("warning", "Can't change direction while moving")
            return  # Can't change direction while moving
        self.direction.set(1)
        self.forward_button.config(state="disabled")
        self.reverse_button.config(state="normal")

    def set_reverse(self):
        self.set_message()
        if self.direction.get() == -1:
            self.set_message("info", "Already moving reverse")
            return  # Already moving reverse
        if self.target_voltage.get() != 0 or self.actual_voltage.get() != 0:
            self.set_message("warning", "Can't change direction while moving")
            return  # Can't change direction while moving
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

    def write_serial(self, value):
        """Send command to Arduino."""
        if not self.ser or not self.ser.is_open:
            return False
        command = int(value)
        self.ser.write(f"{command}\n".encode())
        return True
    
    def read_serial(self):
        """Read serial data from Arduino"""
        while self.reading_serial and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    byte = self.ser.read(1)
                    if byte:
                        self.actual_voltage.set(byte[0])
                        # self.root.after(0, self.update_arduino_status)
            except Exception as e:
                self.set_message("error", e)
                print(f"Serial read error: {e}")
            
            time.sleep(0.05)


if __name__ == "__main__":
    root = tk.Tk()
    app = TrainController(root)
    root.mainloop()
