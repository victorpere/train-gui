# Train GUI

Lightweight GUI and model for controlling an N-scale model railway via a serial-connected microcontroller.

### Prerequisites
- Python 3.8+
- pyserial
- pytest

### Run the GUI

```bash
python3 app/train_gui.py
```

### Run tests

```bash
python3 -m pytest -q
```

#### Testing without hardware
- Use `fake_serial.FakeSerial` by passing a `serial_factory` to `Track` (see `tests` folder).

