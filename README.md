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

### Run the layout editor

```bash
python3 app/layout_editor.py [data/layouts/layout01.json]
```

### MCP server

The GUI can expose the layout and its devices to MCP clients (e.g. Copilot, Claude). The server runs inside the GUI
process, so it shares the live layout and serial connection. It requires the `mcp` package (Python 3.10+) and is off by
default; use the **Start MCP** / **Stop MCP** button in the GUI to toggle it. The address is set in `config/config.ini`:

```ini
[MCP]
host=127.0.0.1
port=8765
```

Then start the server and point the client at `http://127.0.0.1:8765/mcp` (streamable HTTP), e.g. in VS Code `mcp.json`:

```json
{ "servers": { "train-gui": { "type": "http", "url": "http://127.0.0.1:8765/mcp" } } }
```

Tools commanding devices follow the same rules as the GUI and act on real hardware when connected. The server has no
authentication, so keep it bound to localhost.

| Area | Tools |
| --- | --- |
| Layout information | `get_layout`, `get_layout_state`, `list_devices`, `get_device`, `get_connection_status` |
| Device control | `set_track_voltage`, `emergency_stop`, `set_point_direction`, `set_sensor` |
| Connection | `list_serial_ports`, `connect`, `disconnect`, `set_test_mode` |
| Layout files | `list_layout_files`, `load_layout` (from `data/layouts`) |
| Scenarios | `list_scenario_files`, `load_scenario`, `start_scenario`, `stop_scenario`, `get_scenario_status` (from `data/scenarios`) |

### Run tests

```bash
python3 -m pytest -q
```

#### Testing without hardware
- Use `fake_serial.FakeSerial` by passing a `serial_factory` to `Track` (see `tests` folder).

