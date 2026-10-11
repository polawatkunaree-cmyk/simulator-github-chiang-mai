from time import sleep_us


class XPT2046:
    def __init__(self, spi, cs, irq, width, height,
                 x_min=200, x_max=3900, y_min=200, y_max=3900,
                 swap_xy=False, invert_x=False, invert_y=False):
        self.spi = spi
        self.cs = cs
        self.irq = irq
        self.width = width
        self.height = height
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max
        self.swap_xy = swap_xy
        self.invert_x = invert_x
        self.invert_y = invert_y

    def _read12(self, command):
        self.cs(0)
        self.spi.write(bytes((command,)))
        data = self.spi.read(2)
        self.cs(1)
        return ((data[0] << 8) | data[1]) >> 3

    def raw(self):
        if self.irq.value():
            return None

        # V15: 2 MHz + median of 3 samples. V14 used 1 MHz + 5 samples.
        # The median still rejects a bad edge sample, while a short tap is
        # captured much sooner. If IRQ releases during sampling, the samples
        # already collected are still usable.
        self.spi.init(baudrate=2_000_000, polarity=0, phase=0)
        xs = []
        ys = []
        for _ in range(3):
            xs.append(self._read12(0xD0))
            ys.append(self._read12(0x90))
            sleep_us(20)
        xs.sort()
        ys.sort()
        return xs[1], ys[1]

    @staticmethod
    def _map(value, low, high, size):
        if high == low:
            return 0
        value = min(max(value, low), high)
        return int((value - low) * (size - 1) / (high - low))

    def get_touch(self):
        point = self.raw()
        if point is None:
            return None
        rx, ry = point
        if self.swap_xy:
            rx, ry = ry, rx
        x = self._map(rx, self.x_min, self.x_max, self.width)
        y = self._map(ry, self.y_min, self.y_max, self.height)
        if self.invert_x:
            x = self.width - 1 - x
        if self.invert_y:
            y = self.height - 1 - y
        return x, y
