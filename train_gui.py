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
        self.direction = 1  # 1 for forward, -1 for backward

        self.target_speed = tk.IntVar()  # selected target speed
        self.target_speed.set(0)

        self.actual_speed = tk.IntVar()  # current speed from Arduino
        self.actual_speed.set(0)

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

        # Control frame
        control_frame = ttk.LabelFrame(self.root, text="Control", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)
        
        # Direction buttons
        self.reverse_button = ttk.Button(control_frame, text="◀ REV", command=self.set_reverse, width=10)
        self.reverse_button.grid(row=0, column=0, padx=5)
        self.forward_button = ttk.Button(control_frame, text="FWD ▶", command=self.set_forward, width=10)
        self.forward_button.grid(row=0, column=1, padx=5)

        # Preset speed buttons
        self.stop_button = ttk.Button(control_frame, text="Stop", command=lambda: self.set_speed(0, self.stop_button))
        self.stop_button.grid(row=2, column=0, padx=2)
        self.speed1_button = ttk.Button(control_frame, text="Station", command=lambda: self.set_speed(48, self.speed1_button))
        self.speed1_button.grid(row=2, column=1, padx=2)
        self.speed2_button = ttk.Button(control_frame, text="Slow", command=lambda: self.set_speed(70, self.speed2_button))
        self.speed2_button.grid(row=2, column=2, padx=2)
        self.speed3_button = ttk.Button(control_frame, text="1", command=lambda: self.set_speed(80, self.speed3_button))
        self.speed3_button.grid(row=2, column=3, padx=2)
        self.speed4_button = ttk.Button(control_frame, text="2", command=lambda: self.set_speed(96, self.speed4_button))
        self.speed4_button.grid(row=2, column=4, padx=2)
        self.speed5_button = ttk.Button(control_frame, text="3", command=lambda: self.set_speed(128, self.speed5_button))
        self.speed5_button.grid(row=2, column=5, padx=2)
        
        # Status frame
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=10)
        status_frame.pack(fill="x", padx=10, pady=5)
        self.current_status = ttk.Label(status_frame, text="Direction: Stop | PWM: 0")
        self.current_status.pack()

        # # Dashboard frame
        custom_font = tkFont.Font(family="Menlo", size=25)
        dash_frame = ttk.LabelFrame(self.root, padding = 10)
        dash_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(dash_frame, text="Target speed").grid(row=0, column=0)
        ttk.Label(dash_frame, text="Actual speed").grid(row=0, column=1)
        self.target_speed_label = ttk.Label(dash_frame, textvariable=self.target_speed, background="#222", font=custom_font)
        self.target_speed_label.grid(row=1, column=0, padx=5)
        self.actual_speed_label = ttk.Label(dash_frame, textvariable=self.actual_speed, background="#222", font=custom_font)
        self.actual_speed_label.grid(row=1, column=1, padx=5)

        # Message frame
        message_frame = ttk.LabelFrame(self.root, text="Messages", padding=10)
        message_frame.pack(fill="x", padx=10, pady=5)
        self.message_label = ttk.Label(message_frame, text="")
        self.message_label.pack()
    
    def connect_serial(self):
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
            self.show_message("error", str(e))

    def set_speed(self, speed, button_pressed: Button):
        if self.send_command(speed):
            self.target_speed.set(speed)  # Store the speed
            self.current_status.config(text=f"Direction: {'Forward' if self.direction > 0 else 'Reverse'} | Set speed: {self.target_speed}")
            
            # Update button states
            self.reset_buttons()
            button_pressed.config(state="disabled")
    
    def send_command(self, speed):
        """Send speed command to Arduino."""
        if not self.ser or not self.ser.is_open:
            self.show_message("error", "Serial connection not established")
            self.connect_button.config(state="normal")
            self.status_label.config(text="Disconnected", foreground="red")
            self.reset_buttons()
            return False
        
        pwm = speed
        command = int(pwm * self.direction)  # Negative for reverse
        
        self.ser.write(f"{command}\n".encode())
        return True
    
    def set_forward(self):
        if self.direction == 1:
            self.show_message("info", "Already moving forward")
            return  # Already moving forward
        if self.target_speed != 0:
            self.show_message("warning", "Can't change direction while moving")
            return  # Can't change direction while moving
        self.direction = 1
        self.send_command(self.target_speed)  # Use stored speed

    def set_reverse(self):
        if self.direction == -1:
            self.show_message("info", "Already moving reverse")
            return  # Already moving reverse
        if self.target_speed != 0:
            self.show_message("warning", "Can't change direction while moving")
            return  # Can't change direction while moving
        self.direction = -1
        self.send_command(self.target_speed)  # Use stored speed

    def stop(self):
        self.target_speed.set(0)
        self.send_command(0)

    def show_message(self, level, message):
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
        for btn in [self.stop_button, self.speed1_button, self.speed2_button, self.speed3_button, self.speed4_button, self.speed5_button]:
            btn.config(state="normal")

    def read_serial(self):
        """Read serial data from Arduino"""
        while self.reading_serial and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    byte = self.ser.read(1)
                    if byte:
                        self.actual_speed.set(byte[0])
                        # self.root.after(0, self.update_arduino_status)
            except Exception as e:
                self.show_message("error", e)
                print(f"Serial read error: {e}")
            
            time.sleep(0.05)


if __name__ == "__main__":
    root = tk.Tk()
    app = TrainController(root)
    root.mainloop()
