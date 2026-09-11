import time
from threading import Thread
from typing import Callable, List, Optional, Tuple
from util import encode_message, decode_message

try:
    import serial
except Exception:
    serial = None  # Allow importing on systems without pyserial for testing

class Track:
    """Encapsulates track control logic and serial handling.

    Responsibilities:
    - Manage serial connection
    - Maintain direction/target/actual state
    - Run serial reader thread
    - Notify listeners of state changes via callbacks
    """

    def __init__(self, serial_factory: Optional[Callable[[str], object]] = None):
        self.direction = 1
        self.target_voltage = 0
        self.actual_voltage = 0

        self._ser = None
        self._reading = False
        self._listeners: List[Callable[[str, object], None]] = []

        # Default serial factory uses pyserial if available
        if serial_factory is not None:
            self._serial_factory = serial_factory
        else:
            if serial is None:
                # raise at connect time if pyserial isn't available
                self._serial_factory = lambda port: (_ for _ in ()).throw(RuntimeError("pyserial not installed"))
            else:
                self._serial_factory = lambda port: serial.Serial(port, 9600, timeout=1)

    def add_listener(self, cb: Callable[[str, object], None]):
        self._listeners.append(cb)

    def _notify(self, name: str, value: object):
        for cb in list(self._listeners):
            try:
                cb(name, value)
            except Exception:
                pass

    def connect(self, port: str) -> Tuple[bool, str]:
        try:
            self._ser = self._serial_factory(port)
            self._notify("status", "connected")
            self.start_reading()
            return True, ""
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        self.stop_reading()
        try:
            if self._ser and getattr(self._ser, "is_open", False):
                self._ser.close()
        except Exception:
            pass
        self._notify("status", "disconnected")

    def set_direction(self, dir_value: int) -> Tuple[bool, str]:
        if self.target_voltage != 0 or self.actual_voltage != 0:
            return False, "Can't change direction while moving"
        if dir_value not in (1, -1):
            return False, "Invalid direction"
        self.direction = dir_value
        self._notify("direction", self.direction)
        return True, ""

    def set_voltage(self, voltage: int) -> Tuple[bool, str]:
        if not self._ser or not getattr(self._ser, "is_open", False):
            return False, "Serial connection not established"
        try:
            # Apply direction to voltage
            command = int(voltage * self.direction)
            
            # Encode message:
            # request_type=1 (Set), device_type=1 (Target voltage), device_id=1 (Track)
            message = encode_message(
                request_type=1,
                device_type=1,  # Target voltage
                device_id=1,    # Track Device ID
                value=command
            )

            # for my_byte in message:
            #     print(f'{my_byte:0>8b}', end=' ')
            # print("\n")
            self._ser.write(message)
            self.target_voltage = voltage
            self._notify("target_voltage", self.target_voltage)
            return True, ""
        except Exception as e:
            return False, str(e)

    def start_reading(self):
        if self._reading or not self._ser:
            return
        self._reading = True

        def _reader():
            buffer = bytearray()
            while self._reading and self._ser and getattr(self._ser, "is_open", False):
                try:
                    while getattr(self._ser, "in_waiting", 0) >= 3:
                        b = self._ser.read(3)
                        
                        if b:
                            buffer.extend(b)

                            # When we have 3 bytes, try to decode
                            while len(buffer) >= 3:
                                message_data = bytes(buffer[:3])
                                decoded = decode_message(message_data)
                                
                                if decoded is not None:
                                    # Valid message, process it
                                    device_type = decoded["device_type"]
                                    value = decoded["value"]
                                    
                                    if device_type == 0:  # Actual voltage
                                        self.actual_voltage = value
                                        self._notify("actual_voltage", self.actual_voltage)
                                    
                                    # Remove processed bytes
                                    del buffer[:3]
                                else:
                                    # CRC failed or invalid, try to resync
                                    # by removing the first byte and trying again
                                    del buffer[0]
                except Exception:
                    pass
                time.sleep(0.05)

        Thread(target=_reader, daemon=True).start()

    def stop_reading(self):
        self._reading = False
