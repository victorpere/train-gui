import time
import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Button
import tkinter.font as tkFont
import serial
from threading import Thread

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

        # Preset voltage buttons
        self.stop_button = ttk.Button(control_frame, text="STOP", command=lambda: self.set_voltage(0, self.stop_button))
        self.stop_button.grid(row=2, column=0, padx=2)
        self.level1_button = ttk.Button(control_frame, text="IDLE", command=lambda: self.set_voltage(48, self.level1_button))
        self.level1_button.grid(row=2, column=1, padx=2)
        self.level2_button = ttk.Button(control_frame, text="1", command=lambda: self.set_voltage(70, self.level2_button))
        self.level2_button.grid(row=2, column=2, padx=2)
        self.level3_button = ttk.Button(control_frame, text="2", command=lambda: self.set_voltage(80, self.level3_button))
        self.level3_button.grid(row=2, column=3, padx=2)
        self.level4_button = ttk.Button(control_frame, text="3", command=lambda: self.set_voltage(96, self.level4_button))
        self.level4_button.grid(row=2, column=4, padx=2)
        self.level5_button = ttk.Button(control_frame, text="4", command=lambda: self.set_voltage(128, self.level5_button))
        self.level5_button.grid(row=2, column=5, padx=2)

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
        if self.send_command(directional_voltage):
            self.target_voltage.set(voltage)  # Store the voltage           
            # Update button states
            self.reset_buttons()
            button_pressed.config(state="disabled")
    
    def send_command(self, voltage):
        """Send voltage command to Arduino."""
        if not self.ser or not self.ser.is_open:
            self.set_message("error", "Serial connection not established")
            self.connect_button.config(state="normal")
            self.status_label.config(text="Disconnected", foreground="red")
            self.reset_buttons()
            return False
        
        command = int(voltage)  # Negative for reverse
        
        self.ser.write(f"{command}\n".encode())
        return True
    
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
        for btn in [self.stop_button, self.level1_button, self.level2_button, self.level3_button, self.level4_button, self.level5_button]:
            btn.config(state="normal")

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
