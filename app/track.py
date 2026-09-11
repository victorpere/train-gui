import time
from threading import Thread
from typing import Callable, List, Optional, Tuple
import sys

try:
    import serial
except Exception:
    serial = None  # Allow importing on systems without pyserial for testing


def crc8(data: bytes) -> int:
    """Calculate CRC8 checksum using polynomial 0x07."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0x07
            else:
                crc = crc << 1
            crc &= 0xFF
    return crc


def encode_message(request_type: int, device_type: int, device_id: int, value: int) -> bytes:
    """Encode a 3-byte message following the protocol.
    
    Byte 0: [request_type:1 | device_type:3 | device_id:4]
    Byte 1: [value:8] (signed, -128 to +127)
    Byte 2: [CRC8]
    """
    # Byte 0: pack bits
    byte0 = (request_type << 7) | (device_type << 4) | (device_id & 0x0F)
    
    # Byte 1: ensure value is in signed byte range
    value = max(-128, min(127, value))
    byte1 = value & 0xFF
    
    # Bytes for CRC calculation (everything except CRC itself)
    data = bytes([byte0, byte1])
    crc = crc8(data)
    
    return bytes([byte0, byte1, crc])


def decode_message(data: bytes) -> Optional[dict]:
    """Decode a 3-byte message and validate CRC.
    
    Returns a dict with keys: request_type, device_type, device_id, value
    Returns None if CRC is invalid or data length is not 3.
    """
    if len(data) != 3:
        return None
    
    # Validate CRC
    expected_crc = crc8(data[:2])
    if data[2] != expected_crc:
        return None
    
    # Decode byte 0
    byte0 = data[0]
    request_type = (byte0 >> 7) & 0x01
    device_type = (byte0 >> 4) & 0x07
    device_id = byte0 & 0x0F
    
    # Decode byte 1 as signed
    byte1 = data[1]
    if byte1 & 0x80:
        value = byte1 - 256  # Convert to signed
    else:
        value = byte1
    
    return {
        "request_type": request_type,
        "device_type": device_type,
        "device_id": device_id,
        "value": value,
    }


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
