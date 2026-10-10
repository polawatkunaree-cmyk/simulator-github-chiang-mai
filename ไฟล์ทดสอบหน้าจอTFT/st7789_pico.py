import micropython
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
MAGENTA = const(0xF81F)

# Keep the proven-stable V14 clock. V15 gets its extra speed from partial
# transfers, not from pushing the wiring closer to the ST7789 clock limit.
TFT_BAUDRATE = const(40_000_000)


@micropython.viper
def _swap_rgb565_bytes(buf, length: int):
    p = ptr8(buf)
    i = 0
    while i < length:
        a = p[i]
        p[i] = p[i + 1]
        p[i + 1] = a
        i += 2


@micropython.viper
def _swap_rgb565_rect(buf, screen_width: int, x: int, y: int,
                      w: int, h: int):
    """Swap RGB565 byte order only inside a framebuffer rectangle."""
    p = ptr8(buf)
    stride = screen_width * 2
    row_bytes = w * 2
    row = 0
    while row < h:
        i = (y + row) * stride + x * 2
        end = i + row_bytes
        while i < end:
            a = p[i]
            p[i] = p[i + 1]
            p[i + 1] = a
            i += 2
        row += 1


class ST7789(framebuf.FrameBuffer):
    """ST7789 240x320 driver for RP2040 MicroPython.

    rotation=1 gives 320x240 landscape.
    V15 adds show_rect(), so small UI changes do not resend 153,600 bytes.
    """

    def __init__(self, spi, cs, dc, reset, rotation=1):
        self.spi = spi
        self.cs = cs
        self.dc = dc
        self.reset = reset
        self.rotation = rotation & 3

        if self.rotation in (1, 3):
            self.width = 320
            self.height = 240
        else:
            self.width = 240
            self.height = 320

        self.buffer = bytearray(self.width * self.height * 2)
        super().__init__(self.buffer, self.width, self.height, framebuf.RGB565)
        self._view = memoryview(self.buffer)

        self._reset()
        self._init_display()

    def _spi_tft(self):
        # XPT2046 uses the same SPI peripheral at a lower clock.
        self.spi.init(baudrate=TFT_BAUDRATE, polarity=0, phase=0)

    def _write(self, command, data=None):
        self._spi_tft()
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((command,)))
        if data is not None:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _reset(self):
        self.reset(1)
        sleep_ms(50)
        self.reset(0)
        sleep_ms(50)
        self.reset(1)
        sleep_ms(150)

    def _init_display(self):
        self._write(0x01)
        sleep_ms(150)
        self._write(0x11)
        sleep_ms(120)
        self._write(0x3A, b"\x55")
        madctl = (0x00, 0x60, 0xC0, 0xA0)[self.rotation]
        self._write(0x36, bytes((madctl,)))
        self._write(0x21)
        self._write(0x29)
        sleep_ms(100)

    def _window(self, x0, y0, x1, y1):
        self._write(0x2A, bytes(((x0 >> 8) & 0xFF, x0 & 0xFF,
                                 (x1 >> 8) & 0xFF, x1 & 0xFF)))
        self._write(0x2B, bytes(((y0 >> 8) & 0xFF, y0 & 0xFF,
                                 (y1 >> 8) & 0xFF, y1 & 0xFF)))
        self._write(0x2C)

    def show(self):
        """Push the complete framebuffer."""
        self._spi_tft()
        self._window(0, 0, self.width - 1, self.height - 1)
        n = len(self.buffer)
        _swap_rgb565_bytes(self.buffer, n)
        self.cs(0)
        self.dc(1)
        self.spi.write(self.buffer)
        self.cs(1)
        _swap_rgb565_bytes(self.buffer, n)

    def show_rect(self, x, y, w, h):
        """Push only a rectangle from the existing framebuffer.

        No second framebuffer is allocated. The selected RGB565 bytes are
        swapped in-place, transmitted row-by-row through one display window,
        then restored to FrameBuffer byte order.
        """
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        if x + w > self.width:
            w = self.width - x
        if y + h > self.height:
            h = self.height - y
        if w <= 0 or h <= 0:
            return

        self._spi_tft()
        _swap_rgb565_rect(self.buffer, self.width, x, y, w, h)
        self._window(x, y, x + w - 1, y + h - 1)

        stride = self.width * 2
        row_bytes = w * 2
        offset = y * stride + x * 2
        self.cs(0)
        self.dc(1)
        for _ in range(h):
            self.spi.write(self._view[offset:offset + row_bytes])
            offset += stride
        self.cs(1)

        _swap_rgb565_rect(self.buffer, self.width, x, y, w, h)
