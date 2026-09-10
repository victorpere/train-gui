import threading


class FakeSerial:
    """A minimal, thread-safe fake serial for testing TrackModel."""

    def __init__(self):
        self._in = bytearray()
        self._lock = threading.Lock()
        self.is_open = True
        # record writes
        self.written = []

    @property
    def in_waiting(self):
        with self._lock:
            return len(self._in)

    def write(self, data: bytes):
        with self._lock:
            self.written.append(data)

    def read(self, n: int = 1) -> bytes:
        with self._lock:
            if not self._in:
                return b""
            out = self._in[:n]
            del self._in[:n]
            return bytes(out)

    def inject_bytes(self, data: bytes):
        with self._lock:
            self._in.extend(data)

    def close(self):
        self.is_open = False
