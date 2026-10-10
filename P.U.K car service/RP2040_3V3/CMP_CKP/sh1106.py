# MicroPython SH1106 OLED driver (I2C), 128x64 compatible
from micropython import const
import framebuf
import time

_SET_CONTRAST = const(0x81)
_SET_ENTIRE_ON = const(0xA4)
_SET_NORM_INV = const(0xA6)
_SET_DISP = const(0xAE)
_SET_MEM_ADDR = const(0x20)
_SET_DISP_START_LINE = const(0x40)
_SET_SEG_REMAP = const(0xA0)
_SET_MUX_RATIO = const(0xA8)
_SET_COM_OUT_DIR = const(0xC0)
_SET_DISP_OFFSET = const(0xD3)
_SET_COM_PIN_CFG = const(0xDA)
_SET_DISP_CLK_DIV = const(0xD5)
_SET_PRECHARGE = const(0xD9)
_SET_VCOM_DESEL = const(0xDB)
_SET_CHARGE_PUMP = const(0x8D)


class SH1106_I2C(framebuf.FrameBuffer):
    def __init__(self, width, height, i2c, addr=0x3C, rotate=0):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.pages = height // 8
        self.rotate = rotate
        self.buffer = bytearray(self.pages * self.width)
        super().__init__(self.buffer, self.width, self.height, framebuf.MONO_VLSB)
        self.init_display()

    def write_cmd(self, cmd):
        self.i2c.writeto(self.addr, bytes((0x80, cmd)))

    def init_display(self):
        cmds = (
            _SET_DISP | 0x00,
            _SET_DISP_CLK_DIV, 0x80,
            _SET_MUX_RATIO, self.height - 1,
            _SET_DISP_OFFSET, 0x00,
            _SET_DISP_START_LINE | 0x00,
            _SET_CHARGE_PUMP, 0x14,
            _SET_MEM_ADDR, 0x02,
            _SET_SEG_REMAP | 0x01,
            _SET_COM_OUT_DIR | 0x08,
            _SET_COM_PIN_CFG, 0x12,
            _SET_CONTRAST, 0x7F,
            _SET_PRECHARGE, 0xF1,
            _SET_VCOM_DESEL, 0x40,
            _SET_ENTIRE_ON,
            _SET_NORM_INV,
            _SET_DISP | 0x01,
        )
        for cmd in cmds:
            self.write_cmd(cmd)
        self.fill(0)
        self.show()

    def poweroff(self):
        self.write_cmd(_SET_DISP | 0x00)

    def poweron(self):
        self.write_cmd(_SET_DISP | 0x01)

    def contrast(self, contrast):
        self.write_cmd(_SET_CONTRAST)
        self.write_cmd(contrast & 0xFF)

    def invert(self, invert):
        self.write_cmd(_SET_NORM_INV | (invert & 1))

    def show(self):
        # SH1106 RAM is 132 columns wide; 128-pixel displays commonly start at column 2.
        col_offset = 2
        for page in range(self.pages):
            self.write_cmd(0xB0 | page)
            self.write_cmd(0x00 | (col_offset & 0x0F))
            self.write_cmd(0x10 | (col_offset >> 4))
            start = page * self.width
            end = start + self.width
            self.i2c.writeto(self.addr, b"\x40" + self.buffer[start:end])
