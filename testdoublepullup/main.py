# Save as main.py in the root directory of the RP2040 board.
# Starts automatically after power-on/reset; no Run button needed.
# GPIO14: 300 Hz, 50% duty, HIGH approximately 1.667 ms.
# GPIO15: one 2 ms HIGH pulse per 60 GPIO14 pulses (5 Hz, 1% duty).
# Both rising edges coincide at the start of each 60-pulse group.
from machine import Pin
import rp2
import time


@rp2.asm_pio(set_init=(rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW))
def pulse_60_to_1():
    # At 30 kHz, each instruction cycle lasts 1/30000 second.
    # Bit 0 = GPIO14, bit 1 = GPIO15.
    wrap_target()
    # First GPIO14 period: 100 cycles, GPIO15 HIGH for 60 cycles.
    set(pins, 0b11) [24]
    nop() [24]
    set(pins, 0b10) [9]
    set(pins, 0b00) [31]
    set(x, 58) [7]
    # Remaining 59 GPIO14 periods: 50 HIGH + 50 LOW cycles each.
    label("remaining")
    set(pins, 0b01) [24]
    nop() [24]
    set(pins, 0b00) [31]
    nop() [16]
    jmp(x_dec, "remaining")
    wrap()


sm = rp2.StateMachine(0, pulse_60_to_1, freq=300, set_base=Pin(14))
sm.active(1)

while True:
    time.sleep(1)
