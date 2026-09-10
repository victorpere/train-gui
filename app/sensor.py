from block import Block
from track import Track

class Sensor:

    def __init__(self, id: int, track: Track, block_f: Block, block_r: Block):
        self.id = id
        self._track = track
        self._block_f: Block = block_f
        self._block_r: Block = block_r
        self._on: bool = False

    @property
    def is_on(self):
        return self._on

    def detect_on(self):
        if self._track.direction == 1 and self._block_f.occupied:
            raise Exception
        if self._track.direction == -1 and self._block_r.occupied:
            raise Exception
        self._on = True
        self._block_f.occupied = True
        self._block_r.occupied = True

    def detect_off(self):
        self._on = False
        if self._track.direction == 1:
            self._block_r.occupied = False
            self._block_f.occupied = True
        elif self._track.direction == -1:
            self._block_f.occupied = False
            self._block_r.occupied = True