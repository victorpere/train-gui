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
        self.root.geometry("600x700")
        
        self.ser = None
        self.current_speed = 0
        self.direction = 1  # 1 for forward, -1 for backward
        self.speed_table = []  # List of (speed, pwm) tuples
        
        # Build GUI
        self.build_ui()
        self.load_table_from_file("speed_table.json")
        
    def build_ui(self):
        # Serial connection frame
        conn_frame = ttk.LabelFrame(self.root, text="Serial Connection", padding=10)
        conn_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(conn_frame, text="Port:").grid(row=0, column=0)
        self.port_var = tk.StringVar(value="/dev/cu.usbmodem14201")  # Mac default; change as needed
        ttk.Entry(conn_frame, textvariable=self.port_var, width=20).grid(row=0, column=1)
        
        ttk.Button(conn_frame, text="Connect", command=self.connect_serial).grid(row=0, column=2, padx=5)
        self.status_label = ttk.Label(conn_frame, text="Disconnected", foreground="red")
        self.status_label.grid(row=0, column=3)
        
        # Speed table frame
        table_frame = ttk.LabelFrame(self.root, text="Speed vs PWM Table", padding=10)
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Table display
        self.table_tree = ttk.Treeview(table_frame, columns=("Speed", "PWM"), height=8)
        self.table_tree.column("#0", width=0, stretch=False)
        self.table_tree.column("Speed", anchor="center", width=100)
        self.table_tree.column("PWM", anchor="center", width=100)
        self.table_tree.heading("Speed", text="Speed (km/h)")
        self.table_tree.heading("PWM", text="PWM (0-255)")
        self.table_tree.pack(fill="both", expand=True)
        
        # Table edit buttons
        button_frame = ttk.Frame(table_frame)
        button_frame.pack(fill="x", pady=5)
        ttk.Button(button_frame, text="Add Row", command=self.add_table_row).pack(side="left", padx=2)
        ttk.Button(button_frame, text="Delete Row", command=self.delete_table_row).pack(side="left", padx=2)
        ttk.Button(button_frame, text="Save Table", command=self.save_table_to_file).pack(side="left", padx=2)
        ttk.Button(button_frame, text="Load Table", command=self.load_table_dialog).pack(side="left", padx=2)
        
        # Control frame
        control_frame = ttk.LabelFrame(self.root, text="Control", padding=10)
        control_frame.pack(fill="x", padx=10, pady=5)
        
        # Direction buttons
        ttk.Button(control_frame, text="◀ Reverse", command=self.set_reverse, width=10).pack(side="left", padx=5)
        ttk.Button(control_frame, text="Stop", command=self.stop, width=10).pack(side="left", padx=5)
        ttk.Button(control_frame, text="Forward ▶", command=self.set_forward, width=10).pack(side="left", padx=5)
        
        # Speed slider
        slider_frame = ttk.Frame(control_frame)
        slider_frame.pack(fill="x", pady=10)
        ttk.Label(slider_frame, text="Speed:").pack(side="left")
        self.speed_slider = ttk.Scale(slider_frame, from_=0, to=100, orient="horizontal", command=self.on_slider_change)
        self.speed_slider.pack(side="left", fill="x", expand=True, padx=5)
        self.speed_display = ttk.Label(slider_frame, text="0 km/h", width=10)
        self.speed_display.pack(side="left")
        
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
    
    def speed_to_pwm(self, speed):
        """Interpolate speed (km/h) to PWM (0-255) using the table."""
        if not self.speed_table:
            return 0
        
        # Sort table by speed
        sorted_table = sorted(self.speed_table, key=lambda x: x[0])
        
        # Clamp speed to table range
        if speed <= sorted_table[0][0]:
            return sorted_table[0][1]
        if speed >= sorted_table[-1][0]:
            return sorted_table[-1][1]
        
        # Linear interpolation
        for i in range(len(sorted_table) - 1):
            s1, pwm1 = sorted_table[i]
            s2, pwm2 = sorted_table[i + 1]
            if s1 <= speed <= s2:
                ratio = (speed - s1) / (s2 - s1)
                return int(pwm1 + ratio * (pwm2 - pwm1))
        
        return 0
    
    def on_slider_change(self, value):
        speed_value = float(value)
        self.speed_display.config(text=f"{speed_value:.1f} km/h")
        self.send_command(speed_value)
    
    def send_command(self, speed):
        """Send speed command to Arduino."""
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not Connected", "Serial connection not established")
            return
        
        pwm = self.speed_to_pwm(speed)
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
        self.direction = 1
        self.speed_slider.set(0)
    
    def add_table_row(self):
        """Add a new row to the table."""
        self.speed_table.append((0, 0))
        self.refresh_table_display()
    
    def delete_table_row(self):
        """Delete selected row from the table."""
        selected = self.table_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Select a row to delete")
            return
        index = int(selected[0])
        self.speed_table.pop(index)
        self.refresh_table_display()
    
    def refresh_table_display(self):
        """Refresh the treeview display."""
        for item in self.table_tree.get_children():
            self.table_tree.delete(item)
        
        for i, (speed, pwm) in enumerate(self.speed_table):
            self.table_tree.insert("", "end", iid=i, values=(speed, pwm))
        
        # Allow editing cells (simple method: double-click and edit directly)
        self.table_tree.bind("<Double-1>", self.edit_table_cell)
    
    def edit_table_cell(self, event):
        """Allow editing of table cells (simplified inline edit)."""
        item = self.table_tree.selection()
        if not item:
            return
        
        col = self.table_tree.identify_column(event.x)
        if col == "#1":  # Speed column
            self.show_edit_dialog(int(item[0]), "Speed", 0)
        elif col == "#2":  # PWM column
            self.show_edit_dialog(int(item[0]), "PWM", 1)
    
    def show_edit_dialog(self, row_index, field_name, field_index):
        """Show a dialog to edit a cell."""
        value = self.speed_table[row_index][field_index]
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit {field_name}")
        dialog.geometry("300x100")
        
        ttk.Label(dialog, text=f"Enter {field_name}:").pack(pady=10)
        entry = ttk.Entry(dialog, width=10)
        entry.pack(pady=5)
        entry.insert(0, str(value))
        entry.focus()
        
        def save():
            try:
                new_value = int(entry.get())
                table_list = list(self.speed_table)
                table_list[row_index] = (
                    new_value if field_index == 0 else table_list[row_index][0],
                    new_value if field_index == 1 else table_list[row_index][1]
                )
                self.speed_table = table_list
                self.refresh_table_display()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter a valid number")
        
        ttk.Button(dialog, text="Save", command=save).pack(pady=5)
    
    def save_table_to_file(self):
        """Save the table to a JSON file."""
        filename = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if filename:
            with open(filename, 'w') as f:
                json.dump(self.speed_table, f, indent=2)
            messagebox.showinfo("Success", f"Table saved to {filename}")
    
    def load_table_dialog(self):
        """Load a table from a JSON file."""
        filename = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if filename:
            self.load_table_from_file(filename)
    
    def load_table_from_file(self, filename):
        """Load a table from a JSON file."""
        try:
            with open(filename, 'r') as f:
                self.speed_table = json.load(f)
            self.refresh_table_display()
        except FileNotFoundError:
            pass
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

if __name__ == "__main__":
    root = tk.Tk()
    app = TrainController(root)
    root.mainloop()
