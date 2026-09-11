import json
from typing import Optional

def load_data_from_file(filename):
    """Load data from a JSON file."""
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        raise FileNotFoundError(f"File {filename} not found.")
    except Exception as e:
        raise Exception(f"Error loading data from {filename}: {e}")

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
