import rp2
import framebuf
import ujson
from machine import Pin, SPI
from time import ticks_diff, ticks_ms, sleep_ms

from st7735_pico import ST7735, BLACK, WHITE, RED, GREEN, BLUE, CYAN, YELLOW, GRAY
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
    # 4JK1/4JJ1: 56 CKP pulses per crank revolution plus a 30-degree
    # reference gap. Four missing positions on a 60 x 6-degree grid produce
    # the specified 30-degree interval from the last pulse to the next pulse.
    # CMP stays LOW in this entry until its exact 720-degree phase and pulse
    # widths have been verified from the target engine/ECU waveform.
    7: {"name": "ISUZU", "car1": "4JK1 / 4JJ1", "car2": "CKP TEST ONLY", "slots": 60, "missing": (56, 57, 58, 59), "ckp_only": True},
    # EXPERIMENTAL user-requested variant. This keeps the verified Isuzu CKP
    # structure but substitutes one arbitrary CMP window per 720-degree cycle.
    # CMP is HIGH from crank slots 10..19 (60 crank degrees), beginning 60
    # degrees after slot zero, and remains LOW throughout the second crank
    # revolution. It is NOT the production 4JK1/4JJ1 five-pulse CMP pattern.
    8: {"name": "ISU-1C", "car1": "4JK1 / 4JJ1 TEST", "car2": "1CMP EXPERIMENT", "slots": 60, "missing": (56, 57, 58, 59), "cmp_start": 10, "cmp_end": 20},
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
TOUCH_STABLE_TOLERANCE = 20
TOUCH_RELEASE_GRACE_MS = 80
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


# ============================================================
# DISPLAY AND TOUCH
# ============================================================
spi = SPI(
    SPI_ID,
    baudrate=20_000_000,
    polarity=0,
    phase=0,
    sck=Pin(SPI_SCK_PIN),
    mosi=Pin(SPI_MOSI_PIN),
    miso=Pin(SPI_MISO_PIN),
)

tft = ST7735(
    spi,
    cs=Pin(TFT_CS_PIN, Pin.OUT, value=1),
    dc=Pin(TFT_DC_PIN, Pin.OUT, value=0),
    reset=Pin(TFT_RESET_PIN, Pin.OUT, value=1),
    rotation=1,
)

touch = XPT2046(
    spi,
    cs=Pin(TOUCH_CS_PIN, Pin.OUT, value=1),
    irq=Pin(TOUCH_IRQ_PIN, Pin.IN, Pin.PULL_UP),
    width=160,
    height=128,
    # These are safe starting values. Run touch_calibrate.py for exact values.
    x_min=200,
    x_max=3900,
    y_min=200,
    y_max=3900,
    swap_xy=False,
    invert_x=False,
    invert_y=True,
)


# ============================================================
# ON-SCREEN TOUCH CALIBRATION
# ============================================================
CAL_FILE = "touch_cal_v2.json"


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
    tft.text("TOUCH CALIBRATION", 12, 8, CYAN)
    tft.text("TAP THE TARGET", 24, 22, WHITE)
    tft.line(x - 9, y, x + 9, y, YELLOW)
    tft.line(x, y - 9, x, y + 9, YELLOW)
    tft.rect(x - 5, y - 5, 11, 11, RED)
    tft.show()


def read_calibration_point(x, y):
    draw_target(x, y)
    while touch.irq.value() == 0:
        sleep_ms(20)
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
    return int(min(edge_first, edge_second)), int(max(edge_first, edge_second)), edge_first > edge_second


def calibrate_touch():
    margin = 15
    targets = (
        (margin, margin),
        (159 - margin, margin),
        (margin, 127 - margin),
        (159 - margin, 127 - margin),
    )
    raw = [read_calibration_point(x, y) for x, y in targets]

    horizontal_x = abs(((raw[1][0] + raw[3][0]) / 2) - ((raw[0][0] + raw[2][0]) / 2))
    horizontal_y = abs(((raw[1][1] + raw[3][1]) / 2) - ((raw[0][1] + raw[2][1]) / 2))
    swap_xy = horizontal_y > horizontal_x
    mapped = [(y, x) if swap_xy else (x, y) for x, y in raw]

    left = (mapped[0][0] + mapped[2][0]) / 2
    right = (mapped[1][0] + mapped[3][0]) / 2
    top = (mapped[0][1] + mapped[1][1]) / 2
    bottom = (mapped[2][1] + mapped[3][1]) / 2
    x_min, x_max, invert_x = axis_limits(left, right, margin, 160)
    y_min, y_max, invert_y = axis_limits(top, bottom, margin, 128)

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
    tft.text("CALIBRATION OK", 24, 56, GREEN)
    tft.show()
    sleep_ms(700)


if not load_touch_config():
    calibrate_touch()


def button(x, y, w, h, label, color=BLUE):
    tft.fill_rect(x, y, w, h, color)
    tft.rect(x, y, w, h, WHITE)
    tx = x + max(3, (w - len(label) * 8) // 2)
    ty = y + (h - 8) // 2
    tft.text(label, tx, ty, WHITE)


def big_text(text, center_x, y, color=WHITE, scale=2):
    width = len(text) * 8
    buffer = bytearray((width * 8 + 7) // 8)
    font = framebuf.FrameBuffer(buffer, width, 8, framebuf.MONO_HLSB)
    font.text(text, 0, 0, 1)
    start_x = center_x - (width * scale) // 2
    for py in range(8):
        for px in range(width):
            if font.pixel(px, py):
                tft.fill_rect(start_x + px * scale, y + py * scale, scale, scale, color)


def draw_pattern_screen():
    tft.fill(BLACK)
    big_text("PATTERN", 80, 5, CYAN, 2)
    name = patterns[browse_pattern_id]["name"]
    big_text(name, 80, 35, YELLOW, 3)
    car1 = patterns[browse_pattern_id]["car1"]
    car2 = patterns[browse_pattern_id]["car2"]
    tft.text(car1, max(0, 80 - len(car1) * 4), 63, WHITE)
    tft.text(car2, max(0, 80 - len(car2) * 4), 74, GRAY)
    button(4, 88, 48, 36, "<", BLUE)
    button(56, 88, 48, 36, "OK", GREEN)
    button(108, 88, 48, 36, ">", BLUE)
    tft.show()


def draw_rpm_screen():
    tft.fill(BLACK)
    name = patterns[active_pattern_id]["name"]
    big_text(name, 80, 3, YELLOW, 2)
    big_text(str(rpm), 80, 25, WHITE, 3)
    tft.text("RPM", 68, 52, GRAY)
    button(4, 66, 74, 27, "-100", RED)
    button(82, 66, 74, 27, "+100", GREEN)
    button(4, 98, 48, 26, "BACK", BLUE)
    if running:
        button(56, 98, 100, 26, "STOP", RED)
    else:
        button(56, 98, 100, 26, "START", GREEN)
    tft.show()


def draw_screen():
    if screen_page == "pattern":
        draw_pattern_screen()
    else:
        draw_rpm_screen()


def inside(x, y, bx, by, bw, bh):
    return bx <= x < bx + bw and by <= y < by + bh


def rpm_hold_action(x, y):
    """Return the RPM hold action only while the finger is inside its button."""
    if screen_page != "rpm" or not (58 <= y < 96):
        return None
    if x < 80:
        return -1
    return 1


def repeat_rpm(direction, held_ms):
    """Change RPM during a held press, with gentle acceleration."""
    global rpm
    step = 500 if held_ms >= RPM_HOLD_FAST_AFTER_MS else 100
    rpm = max(RPM_MIN, min(RPM_MAX, rpm + direction * step))
    draw_rpm_screen()


def handle_touch(x, y):
    global browse_pattern_id, rpm, running, cycle_slot, screen_page

    if screen_page == "pattern":
        if y >= 80 and x < 54:
            browse_pattern_id -= 1
            if browse_pattern_id < PATTERN_MIN:
                browse_pattern_id = PATTERN_MAX
        elif y >= 80 and x >= 106:
            browse_pattern_id += 1
            if browse_pattern_id > PATTERN_MAX:
                browse_pattern_id = PATTERN_MIN
        elif y >= 80:
            load_pattern(browse_pattern_id)
            screen_page = "rpm"
        else:
            return False
    elif 58 <= y < 96 and x < 80:
        rpm = max(RPM_MIN, rpm - 100)
    elif 58 <= y < 96 and x >= 80:
        rpm = min(RPM_MAX, rpm + 100)
    elif y >= 94 and x < 54:
        if running:
            running = False
            sm.active(0)
            Pin(CMP_PIN, Pin.OUT, value=0)
            Pin(CKP_PIN, Pin.OUT, value=0)
        screen_page = "pattern"
    elif y >= 94 and x >= 54:
        running = not running
        cycle_slot = 0
        if not running:
            sm.active(0)
            Pin(CMP_PIN, Pin.OUT, value=0)
            Pin(CKP_PIN, Pin.OUT, value=0)
        else:
            sm.active(1)
    else:
        return False

    draw_screen()
    return True


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


def signal_word(slot):
    p = patterns[active_pattern_id]
    position = slot % p["slots"]
    half_us = (60_000_000 / (rpm * p["slots"])) / 2
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
touch_candidate = None
touch_stable_count = 0
touch_hold_action = None
touch_hold_started = 0
touch_hold_last_repeat = 0
touch_last_seen = ticks_ms()

try:
    while True:
        point = touch.get_touch()
        if point is None:
            # Do not treat a single missing sample as a release. Resistive
            # touch IRQ can briefly flicker when finger pressure changes.
            if ticks_diff(ticks_ms(), touch_last_seen) >= TOUCH_RELEASE_GRACE_MS:
                touch_down = False
                touch_candidate = None
                touch_stable_count = 0
                touch_hold_action = None
        elif not touch_down:
            touch_last_seen = ticks_ms()
            if (touch_candidate is not None and
                    abs(point[0] - touch_candidate[0]) <= TOUCH_STABLE_TOLERANCE and
                    abs(point[1] - touch_candidate[1]) <= TOUCH_STABLE_TOLERANCE):
                touch_stable_count += 1
                touch_candidate = ((touch_candidate[0] + point[0]) // 2,
                                   (touch_candidate[1] + point[1]) // 2)
            else:
                touch_candidate = point
                touch_stable_count = 1

            # Accept a press only after two nearby readings. If the first
            # reading lands in a gap, keep trying until the finger is stable.
            if touch_stable_count >= 2:
                # Remember whether this press began on an RPM +/- button.
                # This is checked again on every repeat so sliding the finger
                # outside the original button stops auto-repeat immediately.
                new_hold_action = rpm_hold_action(
                    touch_candidate[0], touch_candidate[1]
                )
                if handle_touch(touch_candidate[0], touch_candidate[1]):
                    touch_down = True
                    touch_hold_action = new_hold_action
                    touch_hold_started = ticks_ms()
                    touch_hold_last_repeat = touch_hold_started
                touch_candidate = None
                touch_stable_count = 0
        else:
            touch_last_seen = ticks_ms()
            if touch_hold_action is not None:
                # Keep repeating only while the finger remains on the same button.
                if rpm_hold_action(point[0], point[1]) != touch_hold_action:
                    touch_hold_action = None
                else:
                    now = ticks_ms()
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
    Pin(CMP_PIN, Pin.OUT, value=0)
    Pin(CKP_PIN, Pin.OUT, value=0)
    # MicroPico sends Ctrl+C when it opens an interactive REPL. Keep the
    # current screen visible instead of replacing it with a STOPPED page.
