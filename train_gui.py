import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import serial
import csv
import json
from threading import Thread

class TrainController:
    def __init__(self, root):
        self.root = root
        self.root.title("N-Scale Train Controller")
        # self.root.geometry("600x700")
        
        self.ser = None
        self.current_speed = 0
        self.direction = 1  # 1 for forward, -1 for backward
        self.speed_table = []  # List of (speed, pwm) tuples
        
        # Build GUI
        self.build_ui()
        
    def build_ui(self):
        # Serial connection frame
        conn_frame = ttk.LabelFrame(self.root, text="Serial Connection", padding=10)
        conn_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(conn_frame, text="Port:").grid(row=0, column=0)
        self.port_var = tk.StringVar(value="/dev/cu.usbmodem1301")  # Mac default; change as needed
        ttk.Entry(conn_frame, textvariable=self.port_var, width=20).grid(row=0, column=1)
        
        ttk.Button(conn_frame, text="Connect", command=self.connect_serial).grid(row=0, column=2, padx=5)
        self.status_label = ttk.Label(conn_frame, text="Disconnected", foreground="red")
        self.status_label.grid(row=0, column=3)       

        # Control frame
        control_frame = ttk.LabelFrame(self.root, text="Control", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)
        
        # Direction buttons
        ttk.Button(control_frame, text="◀ Reverse", command=self.set_reverse, width=10).grid(row=0, column=0, padx=5)
        ttk.Button(control_frame, text="Forward ▶", command=self.set_forward, width=10).grid(row=0, column=1, padx=5)

        # Speed slider
        slider_frame = ttk.Frame(control_frame)
        slider_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Label(slider_frame, text="Speed:").grid(row=0, column=0, padx=5)
        self.speed_slider = ttk.Scale(slider_frame, from_=0, to=100, orient="horizontal", command=self.on_slider_change)
        self.speed_slider.grid(row=0, column=1, sticky="ew", padx=5)
        self.speed_display = ttk.Label(slider_frame, text="0 km/h", width=10)
        self.speed_display.grid(row=0, column=2, padx=5)

        # Preset speed buttons
        ttk.Button(control_frame, text="Stop", command=self.stop, width=10).grid(row=2, column=0, padx=2)
        ttk.Button(control_frame, text="1", command=lambda: self.set_speed(60)).grid(row=2, column=1, padx=2)
        ttk.Button(control_frame, text="2", command=lambda: self.set_speed(70)).grid(row=2, column=2, padx=2)
        ttk.Button(control_frame, text="3", command=lambda: self.set_speed(80)).grid(row=2, column=3, padx=2)
        ttk.Button(control_frame, text="4", command=lambda: self.set_speed(90)).grid(row=2, column=4, padx=2)
        ttk.Button(control_frame, text="5", command=lambda: self.set_speed(100)).grid(row=2, column=5, padx=2)
        
        # Status frame
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=10)
        status_frame.pack(fill="x", padx=10, pady=5)
        self.current_status = ttk.Label(status_frame, text="Speed: 0 km/h | Direction: Stop | PWM: 0")
        self.current_status.pack()
    
    def connect_serial(self):
        try:
            port = self.port_var.get()
            self.ser = serial.Serial(port, 9600, timeout=1)
            self.status_label.config(text="Connected", foreground="green")
        except Exception as e:
            messagebox.showerror("Connection Error", str(e))
    
    def on_slider_change(self, value):
        speed_value = float(value)
        self.speed_display.config(text=f"{speed_value:.1f} km/h")
        self.send_command(speed_value)

    def set_speed(self, speed):
        self.speed_slider.set(speed)
        self.send_command(speed)
    
    def send_command(self, speed):
        """Send speed command to Arduino."""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Serial connection not established")
            return
        
        pwm = speed
        command = int(pwm * self.direction)  # Negative for reverse
        
        self.ser.write(f"{command}\n".encode())
        self.current_status.config(text=f"Speed: {speed:.1f} km/h | Direction: {'Forward' if self.direction > 0 else 'Reverse'} | PWM: {pwm}")
    
    def set_forward(self):
        self.direction = 1
        self.send_command(float(self.speed_slider.get()))
    
    def set_reverse(self):
        self.direction = -1
        self.send_command(float(self.speed_slider.get()))
    
    def stop(self):
        self.speed_slider.set(0)
        self.send_command(0)
  
if __name__ == "__main__":
    root = tk.Tk()
    app = TrainController(root)
    root.mainloop()
