import configparser
import json
import os
import yaml
from typing import Optional

def load_canvas_size(config_path: str = "config/config.ini") -> tuple[int, int]:
    """Diagram canvas (width, height), shared by the train GUI and the layout editor."""
    config = configparser.ConfigParser()
    config.read(config_path)
    return int(config.get("Diagram", "canvas_width")), int(config.get("Diagram", "canvas_height"))

def load_data_from_file(filename):
    """Load data from a JSON or YAML file, based on its extension."""
    ext = os.path.splitext(filename)[1].lower()
    try:
        with open(filename, 'r') as f:
            if ext in ('.yaml', '.yml'):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)
        return data
    except FileNotFoundError:
        raise FileNotFoundError(f"File {filename} not found.")
    except Exception as e:
        raise Exception(f"Error loading data from {filename}: {e}")

def save_data_to_file(data, filename):
    """Save data to a JSON or YAML file, based on its extension."""
    ext = os.path.splitext(filename)[1].lower()
    try:
        with open(filename, 'w') as f:
            if ext in ('.yaml', '.yml'):
                yaml.safe_dump(data, f, sort_keys=False)
            else:
                json.dump(data, f, indent=4)
    except Exception as e:
        raise Exception(f"Error saving data to {filename}: {e}")

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

def encode_message(message: dict) -> bytes:
    """Encode a 3-byte message following the protocol.
    
    Byte 0: [message_type:1 | device_type:3 | device_id:4]
    Byte 1: [value:8] (signed, -128 to +127)
    Byte 2: [CRC8]
    """
    message_type: int = message.get("message_type", 0)
    device_type: int = message.get("device_type", 0)
    device_id: int = message.get("device_id", 0)
    value: int = message.get("value", 0)

    # Byte 0: pack bits
    byte0 = (message_type << 7) | ((device_type & 0x07) << 4) | (device_id & 0x0F)
    
    # Byte 1: ensure value is in signed byte range
    value = max(-128, min(127, value))
    byte1 = value & 0xFF
    
    # Bytes for CRC calculation (everything except CRC itself)
    data = bytes([byte0, byte1])
    crc = crc8(data)
    
    return bytes([byte0, byte1, crc])


def decode_message(data: bytes) -> Optional[dict]:
    """Decode a 3-byte message and validate CRC.
    
    Returns a dict with keys: message_type, device_type, device_id, value
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
    message_type = (byte0 >> 7) & 0x01
    device_type = (byte0 >> 4) & 0x07
    device_id = byte0 & 0x0F
    
    # Decode byte 1 as signed
    byte1 = data[1]
    if byte1 & 0x80:
        value = byte1 - 256  # Convert to signed
    else:
        value = byte1
    
    return {
        "message_type": message_type,
        "device_type": device_type,
        "device_id": device_id,
        "value": value,
    }
