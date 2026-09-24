# CKP/CMP V16 ULTRA FAST + TOUCH LOCK / MOVE TOLERANCE
import rp2
import framebuf
import ujson
from machine import Pin, SPI
from time import ticks_diff, ticks_ms, sleep_ms

from st7789_pico import ST7789, BLACK, WHITE, RED, GREEN, BLUE, CYAN, YELLOW, GRAY
from xpt2046_pico import XPT2046


# ============================================================
# RP2040 PIN ASSIGNMENT
# ============================================================
CMP_PIN = 14
CKP_PIN = 15

# One SPI bus is shared by the TFT and touch controller.
SPI_ID = 0
# RP2040-Zero exposes GPIO0-15 and GPIO26-29. SPI0 uses GPIO0-3 here.
SPI_SCK_PIN = 2        # TFT SCK  + T_CLK
SPI_MOSI_PIN = 3       # TFT SDA  + T_DIN
SPI_MISO_PIN = 0       # T_DO (TFT has no MISO pin)
TFT_CS_PIN = 1
TFT_DC_PIN = 4         # A0 / DC
TFT_RESET_PIN = 5
TOUCH_CS_PIN = 6
TOUCH_IRQ_PIN = 7

# Connect TFT LED directly to 3V3 for always-on backlight.


# ============================================================
# PIO: GPIO14 = CMP, GPIO15 = CKP
# bit 0 = GPIO14 (CMP), bit 1 = GPIO15 (CKP)
# ============================================================
@rp2.asm_pio(
    out_init=(rp2.PIO.OUT_LOW, rp2.PIO.OUT_LOW),
    out_shiftdir=rp2.PIO.SHIFT_RIGHT,
)
def ckp_cmp_pio():
    pull(block)
    out(pins, 2)
    out(y, 2)
    out(x, 28)
    mov(isr, x)
    label("first_half")
    jmp(x_dec, "first_half")
    mov(osr, y)
    out(pins, 2)
    mov(x, isr)
    label("second_half")
    jmp(x_dec, "second_half")
    nop() [1]


# ============================================================
# ENGINE PATTERNS / RPM
# ============================================================
patterns = {
    # Vehicle/engine text is an example only. The real CKP/CMP pattern can
    # differ by model year, market, ECU, or an aftermarket trigger wheel.
    1: {"name": "60-2", "car1": "GENERIC 60-2", "car2": "CHECK ECU / ENGINE", "slots": 60, "missing": (58, 59), "cmp_start": 10, "cmp_end": 20},
    2: {"name": "36-2", "car1": "TOYOTA 1NZ-FE", "car2": "TOYOTA 2AZ-FE", "slots": 36, "missing": (34, 35), "cmp_start": 6, "cmp_end": 12},
    3: {"name": "36-1", "car1": "FORD BARRA", "car2": "MAZDA3 LF-DE", "slots": 36, "missing": (35,), "cmp_start": 8, "cmp_end": 14},
    4: {"name": "24-2", "car1": "NISSAN CAS 24-2", "car2": "AFTERMARKET WHEEL", "slots": 24, "missing": (22, 23), "cmp_start": 4, "cmp_end": 8},
    5: {"name": "24-1", "car1": "NISSAN RB/SR 24-1", "car2": "AFTERMARKET WHEEL", "slots": 24, "missing": (23,), "cmp_start": 4, "cmp_end": 8},
    6: {"name": "12+1", "car1": "HONDA K20 / K24", "car2": "12+1 SYSTEM", "slots": 12, "missing": (), "extra_tooth_slot": 11, "cmp_start": 2, "cmp_end": 4},
    # Isuzu service-training waveform for D-Max 4JK1-TC / 4JJ1-TC.
    # CKP: 56 active-low pulses per crank revolution on a 60 x 6-degree grid.
    # Positions 56..59 are absent, so the last falling edge to the next one is
    # 30 crank degrees. The missing-tooth region therefore remains HIGH.
    # CMP: 5 active-low pulses per 720 crank degrees. Four main falling edges
    # are 180 crank degrees apart. The extra reference falling edge is 30
    # degrees before the main edge beside the CKP gap. From the enlarged Isuzu
    # waveform: the reference pulse rises at the last CKP rising edge before
    # the gap, while the adjacent main pulse rises at the first CKP rising edge
    # after the gap. Pulse width is digitised to 12 crank degrees (the nearest
    # 3-degree half-slot used by this generator).
    7: {
        "name": "ISUZU",
        "car1": "D-MAX 4JK1/4JJ1",
        "car2": "112 CKP + 5 CMP",
        "slots": 60,
        "missing": (56, 57, 58, 59),
        "isuzu_4j": True,
        "idle_high": True,
        # Half-slot falling-edge positions (3 degrees each):
        # main = 171, 351, 531, 711 degrees; reference = 321 degrees.
        "cmp_low_starts": (57, 107, 117, 177, 237),
        "cmp_low_width": 4,
    },
}

RPM_MIN = 100
RPM_MAX = 15000
# RPM button auto-repeat settings.
# A quick tap changes 100 RPM. Holding starts after 500 ms and accelerates
# to 500 RPM per repeat after 2 seconds.
RPM_HOLD_DELAY_MS = 500
RPM_HOLD_FAST_AFTER_MS = 2000
RPM_HOLD_REPEAT_MS = 140

# Touch response settings. The XPT2046 driver already returns the median of
# five raw samples, so two mapped readings within this distance are accepted.
# A short release grace ignores momentary T_IRQ dropouts while a finger is down.
TOUCH_STABLE_TOLERANCE = 36
TOUCH_RELEASE_GRACE_MS = 220
TOUCH_HIT_PAD = 7
# Once +/- is pressed, keep that button captured while the finger moves.
# Resistive XPT2046 panels can briefly jitter or flick T_IRQ during a drag.
TOUCH_HOLD_CAPTURE_PAD = 32
PATTERN_MIN = min(patterns)
PATTERN_MAX = max(patterns)

rpm = 1000
active_pattern_id = 1
browse_pattern_id = 1
running = False
cycle_slot = 0
screen_page = "pattern"


def load_pattern(pattern_id):
    global active_pattern_id, browse_pattern_id, cycle_slot
    active_pattern_id = pattern_id
    browse_pattern_id = pattern_id
    cycle_slot = 0


def set_idle_outputs():
    # The MRE CKP/CMP waveform is normally HIGH between active-low pulses.
    level = 1 if patterns[active_pattern_id].get("idle_high", False) else 0
    Pin(CMP_PIN, Pin.OUT, value=level)
    Pin(CKP_PIN, Pin.OUT, value=level)


# ============================================================
# DISPLAY AND TOUCH - ST7789 2.8" 320 x 240 LANDSCAPE
# ============================================================
SCREEN_W = 320
SCREEN_H = 240

spi = SPI(
    SPI_ID,
    baudrate=40_000_000,
    polarity=0,
    phase=0,
    sck=Pin(SPI_SCK_PIN),
    mosi=Pin(SPI_MOSI_PIN),
    miso=Pin(SPI_MISO_PIN),
)

tft = ST7789(
    spi,
    cs=Pin(TFT_CS_PIN, Pin.OUT, value=1),
    dc=Pin(TFT_DC_PIN, Pin.OUT, value=0),
    reset=Pin(TFT_RESET_PIN, Pin.OUT, value=1),
    rotation=1,
)

# Values below are based on the raw points measured on this 2.8-inch panel:
# LT=(680,427), RT=(560,3635), LB=(3087,551), RB=(3511,3583).
# The touch controller axes are crossed relative to landscape display axes.
touch = XPT2046(
    spi,
    cs=Pin(TOUCH_CS_PIN, Pin.OUT, value=1),
    irq=Pin(TOUCH_IRQ_PIN, Pin.IN, Pin.PULL_UP),
    width=SCREEN_W,
    height=SCREEN_H,
    x_min=489,
    x_max=3609,
    y_min=620,
    y_max=3299,
    swap_xy=True,
    invert_x=False,
    invert_y=False,
)


# ============================================================
# TOUCH CALIBRATION
# ============================================================
# New filename prevents the old 160x128 ST7735 calibration from being reused.
CAL_FILE = "touch_cal_st7789_v13.json"


def apply_touch_config(config):
    touch.x_min = config["x_min"]
    touch.x_max = config["x_max"]
    touch.y_min = config["y_min"]
    touch.y_max = config["y_max"]
    touch.swap_xy = config["swap_xy"]
    touch.invert_x = config["invert_x"]
    touch.invert_y = config["invert_y"]


def load_touch_config():
    try:
        with open(CAL_FILE, "r") as file:
            apply_touch_config(ujson.load(file))
        return True
    except Exception:
        return False


def draw_target(x, y):
    tft.fill(BLACK)
    tft.text("TOUCH CALIBRATION", 88, 55, CYAN)
    tft.text("TAP THE TARGET", 104, 75, WHITE)
    tft.line(x - 12, y, x + 12, y, YELLOW)
    tft.line(x, y - 12, x, y + 12, YELLOW)
    tft.rect(x - 6, y - 6, 13, 13, RED)
    tft.show()


def read_calibration_point(x, y):
    draw_target(x, y)

    # Wait for finger to be fully released before accepting the next target.
    while touch.irq.value() == 0:
        sleep_ms(20)
    # Then wait for a new press.
    while touch.irq.value() == 1:
        sleep_ms(10)

    samples = []
    while touch.irq.value() == 0 and len(samples) < 12:
        point = touch.raw()
        if point is not None:
            samples.append(point)
        sleep_ms(15)

    while touch.irq.value() == 0:
        sleep_ms(10)

    if not samples:
        return read_calibration_point(x, y)

    samples.sort(key=lambda item: item[0])
    raw_x = samples[len(samples) // 2][0]
    samples.sort(key=lambda item: item[1])
    raw_y = samples[len(samples) // 2][1]
    sleep_ms(250)
    return raw_x, raw_y


def axis_limits(first, second, margin, size):
    span = size - 1 - (margin * 2)
    slope = (second - first) / span
    edge_first = first - slope * margin
    edge_second = second + slope * margin
    return (
        int(min(edge_first, edge_second)),
        int(max(edge_first, edge_second)),
        edge_first > edge_second,
    )


def calibrate_touch():
    margin = 24
    targets = (
        (margin, margin),
        (SCREEN_W - 1 - margin, margin),
        (margin, SCREEN_H - 1 - margin),
        (SCREEN_W - 1 - margin, SCREEN_H - 1 - margin),
    )
    raw = [read_calibration_point(x, y) for x, y in targets]

    horizontal_x = abs(
        ((raw[1][0] + raw[3][0]) / 2) -
        ((raw[0][0] + raw[2][0]) / 2)
    )
    horizontal_y = abs(
        ((raw[1][1] + raw[3][1]) / 2) -
        ((raw[0][1] + raw[2][1]) / 2)
    )
    swap_xy = horizontal_y > horizontal_x
    mapped = [(y, x) if swap_xy else (x, y) for x, y in raw]

    left = (mapped[0][0] + mapped[2][0]) / 2
    right = (mapped[1][0] + mapped[3][0]) / 2
    top = (mapped[0][1] + mapped[1][1]) / 2
    bottom = (mapped[2][1] + mapped[3][1]) / 2

    x_min, x_max, invert_x = axis_limits(
        left, right, margin, SCREEN_W
    )
    y_min, y_max, invert_y = axis_limits(
        top, bottom, margin, SCREEN_H
    )

    config = {
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "swap_xy": swap_xy,
        "invert_x": invert_x,
        "invert_y": invert_y,
    }
    apply_touch_config(config)

    try:
        with open(CAL_FILE, "w") as file:
            ujson.dump(config, file)
    except Exception:
        pass

    tft.fill(BLACK)
    tft.text("CALIBRATION OK", 104, 112, GREEN)
    tft.show()
    sleep_ms(700)


# Use the calibration measured today immediately.  A saved V13 calibration,
# if present, takes priority.  To recalibrate later, delete
# touch_cal_st7789_v13.json and set FORCE_TOUCH_CALIBRATION = True once.
FORCE_TOUCH_CALIBRATION = False
if FORCE_TOUCH_CALIBRATION:
    calibrate_touch()
else:
    load_touch_config()


# ============================================================
# 320 x 240 USER INTERFACE
# ============================================================
def button(x, y, w, h, label, color=BLUE, text_scale=2):
    tft.fill_rect(x, y, w, h, color)
    tft.rect(x, y, w, h, WHITE)
    label_w = len(label) * 8 * text_scale
    tx = x + max(3, (w - label_w) // 2)
    ty = y + max(2, (h - 8 * text_scale) // 2)
    big_text(label, tx + label_w // 2, ty, WHITE, text_scale)


def big_text(text, center_x, y, color=WHITE, scale=2):
    width = len(text) * 8
    buffer = bytearray((width * 8 + 7) // 8)
    font = framebuf.FrameBuffer(buffer, width, 8, framebuf.MONO_HLSB)
    font.text(text, 0, 0, 1)
    start_x = center_x - (width * scale) // 2
    for py in range(8):
        for px in range(width):
            if font.pixel(px, py):
                tft.fill_rect(
                    start_x + px * scale,
                    y + py * scale,
                    scale,
                    scale,
                    color,
                )


def draw_pattern_screen():
    tft.fill(BLACK)

    big_text("PATTERN", 160, 12, CYAN, 3)

    name = patterns[browse_pattern_id]["name"]
    name_scale = 5 if len(name) <= 6 else 4
    big_text(name, 160, 55, YELLOW, name_scale)

    car1 = patterns[browse_pattern_id]["car1"]
    car2 = patterns[browse_pattern_id]["car2"]
    big_text(car1, 160, 105, WHITE, 2)
    big_text(car2, 160, 128, GRAY, 2)

    # Bottom navigation uses almost the full 320-pixel width.
    button(8,   174, 92, 56, "<",  BLUE, 3)
    button(114, 174, 92, 56, "OK", GREEN, 2)
    button(220, 174, 92, 56, ">",  BLUE, 3)

    tft.show()


def draw_rpm_screen():
    tft.fill(BLACK)

    name = patterns[active_pattern_id]["name"]
    big_text(name, 160, 10, YELLOW, 3)

    # RPM value is intentionally large on the 2.8-inch screen.
    big_text(str(rpm), 160, 48, WHITE, 5)
    big_text("RPM", 160, 93, GRAY, 2)

    button(8,   122, 146, 50, "-100", RED,   2)
    button(166, 122, 146, 50, "+100", GREEN, 2)

    button(8,   184, 92, 46, "BACK", BLUE,  2)
    if running:
        button(114, 184, 198, 46, "STOP", RED, 2)
    else:
        button(114, 184, 198, 46, "START", GREEN, 2)

    tft.show()


def draw_screen():
    if screen_page == "pattern":
        draw_pattern_screen()
    else:
        draw_rpm_screen()


def inside(x, y, bx, by, bw, bh, pad=0):
    return (bx - pad) <= x < (bx + bw + pad) and (by - pad) <= y < (by + bh + pad)


def rpm_hold_action(x, y, pad=TOUCH_HIT_PAD):
    """Return RPM direction for a coordinate inside a +/- button."""
    if screen_page != "rpm":
        return None
    if inside(x, y, 8, 122, 146, 50, pad):
        return -1
    if inside(x, y, 166, 122, 146, 50, pad):
        return 1
    return None


def hold_still_captured(direction, x, y):
    """Large hysteresis area for an already-pressed +/- button.

    The first press still has to land on the real button. After that, a small
    finger slide or coordinate jitter will not cancel the hold. The two +/-
    capture zones are clamped at the screen centre so a slide cannot silently
    change from - to + or vice versa.
    """
    if screen_page != "rpm":
        return False
    pad = TOUCH_HOLD_CAPTURE_PAD
    if direction < 0:
        return ((8 - pad) <= x < 160 and
                (122 - pad) <= y < (122 + 50 + pad))
    return (160 <= x < (166 + 146 + pad) and
            (122 - pad) <= y < (122 + 50 + pad))


def redraw_rpm_value():
    """V15: update only the RPM strip on the physical TFT.

    V14 still transmitted the complete 320x240 framebuffer after changing
    the number. V15 sends only this 320x72 rectangle (~23% of the screen).
    """
    tft.fill_rect(0, 42, 320, 72, BLACK)
    big_text(str(rpm), 160, 48, WHITE, 5)
    big_text("RPM", 160, 93, GRAY, 2)
    tft.show_rect(0, 42, 320, 72)


def repeat_rpm(direction, held_ms):
    """Change RPM during a held press, with gentle acceleration."""
    global rpm
    step = 500 if held_ms >= RPM_HOLD_FAST_AFTER_MS else 100
    rpm = max(RPM_MIN, min(RPM_MAX, rpm + direction * step))
    redraw_rpm_value()


def redraw_pattern_info():
    """V15: refresh only the changing pattern-name/info area."""
    tft.fill_rect(0, 48, 320, 112, BLACK)
    name = patterns[browse_pattern_id]["name"]
    name_scale = 5 if len(name) <= 6 else 4
    big_text(name, 160, 55, YELLOW, name_scale)
    big_text(patterns[browse_pattern_id]["car1"], 160, 105, WHITE, 2)
    big_text(patterns[browse_pattern_id]["car2"], 160, 128, GRAY, 2)
    tft.show_rect(0, 48, 320, 112)


def redraw_start_stop_button():
    """V15: refresh only START/STOP instead of the whole screen."""
    if running:
        button(114, 184, 198, 46, "STOP", RED, 2)
    else:
        button(114, 184, 198, 46, "START", GREEN, 2)
    tft.show_rect(114, 184, 198, 46)


def handle_touch(x, y):
    global browse_pattern_id, rpm, running, cycle_slot, screen_page

    if screen_page == "pattern":
        if inside(x, y, 8, 174, 92, 56, TOUCH_HIT_PAD):
            browse_pattern_id -= 1
            if browse_pattern_id < PATTERN_MIN:
                browse_pattern_id = PATTERN_MAX
            redraw_pattern_info()
            return True

        if inside(x, y, 220, 174, 92, 56, TOUCH_HIT_PAD):
            browse_pattern_id += 1
            if browse_pattern_id > PATTERN_MAX:
                browse_pattern_id = PATTERN_MIN
            redraw_pattern_info()
            return True

        if inside(x, y, 114, 174, 92, 56, TOUCH_HIT_PAD):
            load_pattern(browse_pattern_id)
            screen_page = "rpm"
            draw_rpm_screen()
            return True
        return False

    if inside(x, y, 8, 122, 146, 50, TOUCH_HIT_PAD):
        rpm = max(RPM_MIN, rpm - 100)
        redraw_rpm_value()
        return True

    if inside(x, y, 166, 122, 146, 50, TOUCH_HIT_PAD):
        rpm = min(RPM_MAX, rpm + 100)
        redraw_rpm_value()
        return True

    if inside(x, y, 8, 184, 92, 46, TOUCH_HIT_PAD):
        if running:
            running = False
            sm.active(0)
            set_idle_outputs()
        screen_page = "pattern"
        draw_pattern_screen()
        return True

    if inside(x, y, 114, 184, 198, 46, TOUCH_HIT_PAD):
        running = not running
        cycle_slot = 0
        if not running:
            sm.active(0)
            set_idle_outputs()
        else:
            sm.active(1)
        redraw_start_stop_button()
        return True

    return False


# ============================================================
# SIGNAL GENERATION
# ============================================================
PIO_FREQUENCY = 1_000_000
PIO_LOOP_CYCLES_PER_COUNT = 1
PIO_FIXED_CYCLES = 6
MAX_DELAY_COUNT = (1 << 28) - 1


def pio_half_count(half_period_us):
    # At 1 MHz, one PIO instruction cycle is 1 us.
    cycles = int(half_period_us * (PIO_FREQUENCY / 1_000_000))
    return max(0, min(MAX_DELAY_COUNT, cycles - PIO_FIXED_CYCLES))


def packed_word(first_level, second_level, half_period_us):
    count = pio_half_count(half_period_us)
    return first_level | (second_level << 2) | (count << 4)


def isuzu_cmp_level(half_slot, p):
    for start in p["cmp_low_starts"]:
        # Modulo handles the main pulse at 711 degrees crossing the 720-degree
        # cycle boundary and ending at 3 degrees of the next cycle.
        if (half_slot - start) % (p["slots"] * 4) < p["cmp_low_width"]:
            return 0
    return 1


def signal_word(slot):
    p = patterns[active_pattern_id]
    position = slot % p["slots"]
    half_us = (60_000_000 / (rpm * p["slots"])) / 2

    if p.get("isuzu_4j", False):
        first_half_slot = slot * 2
        second_half_slot = first_half_slot + 1
        cmp_first = isuzu_cmp_level(first_half_slot, p)
        cmp_second = isuzu_cmp_level(second_half_slot, p)

        if position in p["missing"]:
            ckp_first = 1
            ckp_second = 1
        else:
            # Isuzu manual CH2: active-low tooth pulse, HIGH missing gap.
            ckp_first = 0
            ckp_second = 1

        first_level = cmp_first | (ckp_first << 1)
        second_level = cmp_second | (ckp_second << 1)
        return packed_word(first_level, second_level, half_us)

    if p.get("ckp_only", False):
        cmp_level = 0
    else:
        cmp_level = 1 if p["cmp_start"] <= slot < p["cmp_end"] else 0
    high = cmp_level | 0b10

    if position in p["missing"]:
        return packed_word(cmp_level, cmp_level, half_us)

    # 12+1 is handled by sending this slot twice below.
    return packed_word(high, cmp_level, half_us)


sm = rp2.StateMachine(
    0,
    ckp_cmp_pio,
    freq=PIO_FREQUENCY,
    out_base=Pin(CMP_PIN),
)


draw_screen()
touch_down = False
touch_hold_action = None
touch_hold_started = 0
touch_hold_last_repeat = 0
touch_last_seen = ticks_ms()

try:
    while True:
        point = touch.get_touch()
        now = ticks_ms()

        if point is None:
            # Keep a short release grace because T_IRQ can flicker while a
            # finger is still touching the resistive panel.
            if touch_down and ticks_diff(now, touch_last_seen) >= TOUCH_RELEASE_GRACE_MS:
                touch_down = False
                touch_hold_action = None
        else:
            touch_last_seen = now
            if not touch_down:
                # V15 accepts the first MEDIAN-filtered coordinate immediately.
                # This fixes short taps that V14 could miss while waiting for a
                # second stable coordinate. The XPT driver itself filters 3
                # samples, and button hitboxes have a small edge allowance.
                new_hold_action = rpm_hold_action(point[0], point[1])
                if handle_touch(point[0], point[1]):
                    touch_down = True
                    touch_hold_action = new_hold_action
                    touch_hold_started = now
                    touch_hold_last_repeat = now
            elif touch_hold_action is not None:
                # V16 touch capture: do not cancel a held +/- button just
                # because the finger moves a few pixels. Resistive panels
                # naturally jitter while pressure shifts. Only leave the
                # capture when the coordinate moves well outside its enlarged
                # zone; a brief IRQ dropout is handled by release grace above.
                if hold_still_captured(touch_hold_action, point[0], point[1]):
                    held_ms = ticks_diff(now, touch_hold_started)
                    since_repeat = ticks_diff(now, touch_hold_last_repeat)
                    if (held_ms >= RPM_HOLD_DELAY_MS and
                            since_repeat >= RPM_HOLD_REPEAT_MS):
                        repeat_rpm(touch_hold_action, held_ms)
                        touch_hold_last_repeat = now

        if running:
            p = patterns[active_pattern_id]
            word = signal_word(cycle_slot)
            sm.put(word)
            if p.get("extra_tooth_slot") == (cycle_slot % p["slots"]):
                sm.put(word)
            cycle_slot += 1
            if cycle_slot >= p["slots"] * 2:
                cycle_slot = 0
        else:
            sleep_ms(5)

except KeyboardInterrupt:
    sm.active(0)
    set_idle_outputs()
    # MicroPico sends Ctrl+C when it opens an interactive REPL. Keep the
    # current screen visible instead of replacing it with a STOPPED page.
