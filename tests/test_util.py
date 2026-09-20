import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))

from util import encode_message, decode_message

def test_encode_decode_message():
    """Test that encode/decode roundtrip works correctly."""
    # Test positive value
    message = {
        "message_type": 1,
        "device_type": 1,
        "device_id": 1,
        "value": 42
    }
    msg = encode_message(message)
    decoded = decode_message(msg)
    assert decoded["message_type"] == 1
    assert decoded["device_type"] == 1
    assert decoded["device_id"] == 1
    assert decoded["value"] == 42
    
    # Test negative value
    message = {
            "message_type": 1,
            "device_type": 0,
            "device_id": 1,
            "value": -30
        }
    msg = encode_message(message)
    decoded = decode_message(msg)
    assert decoded["value"] == -30
    
    # Test CRC failure (corrupt one byte)
    message = {
            "message_type": 1,
            "device_type": 1,
            "device_id": 1,
            "value": 42
        }
    msg = encode_message(message)
    corrupted = bytes([msg[0] ^ 0x01, msg[1], msg[2]])  # flip a bit in byte 0
    decoded = decode_message(corrupted)
    assert decoded is None  # CRC should fail

