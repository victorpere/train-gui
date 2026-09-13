import time
from threading import Thread
from typing import Callable, Optional, Tuple, List
from util import encode_message, decode_message

try:
    import serial
except Exception:
    serial = None  # Allow importing on systems without pyserial for testing


class Communicator:
    def __init__(self, serial_factory: Optional[Callable[[str], object]] = None):
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

    def send(self, message):
        try:
            self._ser.write(message)
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
                                    self._notify(decoded["message_type"], \
                                                 decoded["device_type"], \
                                                 decoded["device_id"], \
                                                 decoded["value"])
                                    
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
