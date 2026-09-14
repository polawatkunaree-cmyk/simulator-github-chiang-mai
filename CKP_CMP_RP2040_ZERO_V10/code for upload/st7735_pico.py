from micropython import const
import framebuf
from time import sleep_ms

BLACK = const(0x0000)
WHITE = const(0xFFFF)
RED = const(0xF800)
GREEN = const(0x07E0)
BLUE = const(0x001F)
CYAN = const(0x07FF)
YELLOW = const(0xFFE0)
GRAY = const(0x8410)


class ST7735(framebuf.FrameBuffer):
    def __init__(self, spi, cs, dc, reset, rotation=1):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.reset = reset
        self.rotation = rotation
        self.width = 160 if rotation in (1, 3) else 128
        self.height = 128 if rotation in (1, 3) else 160
        self.buffer = bytearray(self.width * self.height * 2)
        super().__init__(self.buffer, self.width, self.height, framebuf.RGB565)
        self._reset()
        self._init_display()

    def _write(self, command, data=None):
        self.spi.init(baudrate=20_000_000, polarity=0, phase=0)
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((command,)))
        if data is not None:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _reset(self):
        self.reset(1)
        sleep_ms(20)
        self.reset(0)
        sleep_ms(20)
        self.reset(1)
        sleep_ms(120)

    def _init_display(self):
        self._write(0x01)
        sleep_ms(150)
        self._write(0x11)
        sleep_ms(150)
        self._write(0x3A, b"\x05")       # RGB565
        madctl = (0x00, 0x60, 0xC0, 0xA0)[self.rotation]
        self._write(0x36, bytes((madctl,)))
        self._write(0x21)                 # inversion on for common red PCB module
        self._write(0x29)
        sleep_ms(100)

    def _window(self, x0, y0, x1, y1):
        # Common ST7735S 1.8-inch panel offsets.
        if self.rotation in (1, 3):
            x0 += 1
            x1 += 1
            y0 += 2
            y1 += 2
        else:
            x0 += 2
            x1 += 2
            y0 += 1
            y1 += 1
        self._write(0x2A, bytes((0, x0, 0, x1)))
        self._write(0x2B, bytes((0, y0, 0, y1)))
        self._write(0x2C)

    def show(self):
        self.spi.init(baudrate=20_000_000, polarity=0, phase=0)
        self._window(0, 0, self.width - 1, self.height - 1)
        self.cs(0)
        self.dc(1)
        # framebuf stores each RGB565 pixel little-endian; TFT expects MSB first.
        chunk = bytearray(512)
        view = memoryview(self.buffer)
        for start in range(0, len(self.buffer), len(chunk)):
            source = view[start:start + len(chunk)]
            n = len(source)
            for i in range(0, n, 2):
                chunk[i] = source[i + 1]
                chunk[i + 1] = source[i]
            self.spi.write(memoryview(chunk)[:n])
        self.cs(1)
