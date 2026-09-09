# Train GUI

Lightweight GUI and model for controlling an N-scale train via a serial-connected microcontroller.

Overview
- `train_gui.py` — Tkinter-based GUI (thin view layer). Accepts injected `buttons_data` and a `TrainModel` instance.
- `train_model.py` — Encapsulates serial I/O, state (direction/target/actual), and a background reader thread. Notifies listeners via callbacks.
- `fake_serial.py` — Thread-safe fake serial used for tests and local development without hardware.
- `util.py` — small helpers (e.g. `load_data_from_file`).
- `control_buttons.json` — button configuration (labels and values).

Prerequisites
- Python 3.8+
- Optional: `pyserial` if you want to run with real hardware:

```bash
pip install pyserial
```

Run the GUI

```bash
python3 train_gui.py
```

The GUI loads `control_buttons.json` at startup (in the `__main__` block) and injects it into `TrainController`.

Run the fake-serial integration test

```bash
python3 tests/run_fake_test.py
```

Testing without hardware
- Use `fake_serial.FakeSerial` by passing a `serial_factory` to `TrainModel` (see `tests/run_fake_test.py`).

Development notes
- The project separates concerns: UI in `train_gui.py`, logic/serial in `train_model.py`. This makes unit testing and mocking easier.
- To add CI later, convert the test into `pytest` format and run it in your pipeline.

