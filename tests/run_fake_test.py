import sys
import time
import os

# Ensure project root is on sys.path when running this script from tests/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from train_model import TrainModel
from fake_serial import FakeSerial


events = []


def listener(name, value):
    events.append((name, value))


def factory(port):
    fs = FakeSerial()
    factory.last = fs
    return fs


def main():
    model = TrainModel(serial_factory=factory)
    model.add_listener(listener)

    ok, msg = model.connect("/dev/fake")
    if not ok:
        print("CONNECT FAILED:", msg)
        sys.exit(1)

    ok, msg = model.set_voltage(42)
    if not ok:
        print("SET VOLTAGE FAILED:", msg)
        sys.exit(1)

    # allow background thread to run and record write
    time.sleep(0.1)

    written = getattr(factory, "last").written
    if not written:
        print("NO WRITE")
        sys.exit(1)
    if written[-1] != b"42\n":
        print("WRONG WRITE:", written[-1])
        sys.exit(1)

    # inject incoming byte and wait for actual_voltage notification
    factory.last.inject_bytes(bytes([13]))
    time.sleep(0.2)

    found = any(e for e in events if e[0] == "actual_voltage" and e[1] == 13)
    if not found:
        print("NO ACTUAL EVENT", events)
        sys.exit(1)

    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
