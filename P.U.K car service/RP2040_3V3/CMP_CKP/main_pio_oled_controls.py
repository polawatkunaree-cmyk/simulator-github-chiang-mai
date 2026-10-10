import rp2
from machine import Pin, I2C
from time import ticks_diff, ticks_ms

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
# GPIO ASSIGNMENT
# ============================================================
CMP_PIN = 14
CKP_PIN = 15

# KY-040
ENCODER_A_PIN = 10     # CLK
ENCODER_B_PIN = 11     # DT
ENCODER_SW_PIN = 12    # SW (optional: change RPM step)

# 3 push buttons
BUTTON_LEFT_PIN = 6
BUTTON_CENTER_PIN = 7
BUTTON_RIGHT_PIN = 8

# OLED I2C0
OLED_SDA_PIN = 4
OLED_SCL_PIN = 5

# Most 1.3-inch 128x64 OLED modules are SH1106, but verify your module.
# Change to "SSD1306" if your display uses SSD1306.
OLED_DRIVER = "SH1106"
OLED_WIDTH = 128
OLED_HEIGHT = 64
OLED_ADDR = 0x3C


# ============================================================
# RPM SETTINGS
# ============================================================
RPM_MIN = 100
RPM_MAX = 15_000
RPM_STEP_NORMAL = 100
RPM_STEP_FINE = 10

rpm = 1000
rpm_step = RPM_STEP_NORMAL


# ============================================================
# ENGINE PATTERN DATABASE
# ============================================================
patterns = {
    1: {
        "name": "60-2",
        "slots": 60,
        "missing": (58, 59),
        "cmp_start": 10,
        "cmp_end": 20,
    },
    2: {
        "name": "36-2",
        "slots": 36,
        "missing": (34, 35),
        "cmp_start": 6,
        "cmp_end": 12,
    },
    3: {
        "name": "36-1",
        "slots": 36,
        "missing": (35,),
        "cmp_start": 8,
        "cmp_end": 14,
    },
    4: {
        "name": "24-2",
        "slots": 24,
        "missing": (22, 23),
        "cmp_start": 4,
        "cmp_end": 8,
    },
    5: {
        "name": "24-1",
        "slots": 24,
        "missing": (23,),
        "cmp_start": 4,
        "cmp_end": 8,
    },
    6: {
        "name": "12+1",
        "slots": 12,
        "missing": (),
        "extra_tooth_slot": 11,
        "cmp_start": 2,
        "cmp_end": 4,
    },
}

PATTERN_MIN = min(patterns)
PATTERN_MAX = max(patterns)

# Pattern currently being output by CKP/CMP
active_pattern_id = 1

# Pattern currently shown while user browses with LEFT/RIGHT
browse_pattern_id = active_pattern_id

pattern = None
slots_per_rev = 0
missing_slots = ()
extra_tooth_slot = None
cmp_start = 0
cmp_end = 0
cycle_slot = 0


def load_pattern(pattern_id):
    """Apply a selected engine pattern to the CKP/CMP generator."""
    global active_pattern_id, pattern
    global slots_per_rev, missing_slots, extra_tooth_slot
    global cmp_start, cmp_end, cycle_slot

    active_pattern_id = pattern_id
    pattern = patterns[pattern_id]
    slots_per_rev = pattern["slots"]
    missing_slots = pattern["missing"]
    extra_tooth_slot = pattern.get("extra_tooth_slot", None)
    cmp_start = pattern["cmp_start"]
    cmp_end = pattern["cmp_end"]

    # Start the newly selected pattern at the beginning of its 720-degree cycle.
    cycle_slot = 0
    print("Pattern selected:", pattern["name"])


load_pattern(active_pattern_id)


# ============================================================
# OLED
# ============================================================
i2c = I2C(
    0,
    sda=Pin(OLED_SDA_PIN),
    scl=Pin(OLED_SCL_PIN),
    freq=400_000,
)

if OLED_DRIVER == "SH1106":
    import sh1106
    oled = sh1106.SH1106_I2C(
        OLED_WIDTH,
        OLED_HEIGHT,
        i2c,
        addr=OLED_ADDR,
    )
elif OLED_DRIVER == "SSD1306":
    import ssd1306
    oled = ssd1306.SSD1306_I2C(
        OLED_WIDTH,
        OLED_HEIGHT,
        i2c,
        addr=OLED_ADDR,
    )
else:
    raise ValueError("OLED_DRIVER must be SH1106 or SSD1306")

DISPLAY_PATTERN = 0
DISPLAY_RPM = 1

display_mode = DISPLAY_PATTERN
display_dirty = True
last_display_ms = 0
DISPLAY_MIN_INTERVAL_MS = 80


def request_pattern_screen():
    global display_mode, display_dirty
    display_mode = DISPLAY_PATTERN
    display_dirty = True


def request_rpm_screen():
    global display_mode, display_dirty
    display_mode = DISPLAY_RPM
    display_dirty = True


def draw_pattern_screen():
    oled.fill(0)
    oled.text("ENGINE PATTERN", 8, 4)
    oled.text("<", 8, 28)
    oled.text(patterns[browse_pattern_id]["name"], 48, 28)
    oled.text(">", 112, 28)

    if browse_pattern_id == active_pattern_id:
        oled.text("SELECTED", 32, 50)
    else:
        oled.text("CENTER = SET", 16, 50)

    oled.show()


def draw_rpm_screen():
    oled.fill(0)
    oled.text("RPM", 52, 4)
    oled.text(str(rpm), 40, 28)
    oled.text("STEP: " + str(rpm_step), 24, 50)
    oled.show()


def service_display(force=False):
    global display_dirty, last_display_ms

    if not display_dirty:
        return

    now = ticks_ms()
    if not force and ticks_diff(now, last_display_ms) < DISPLAY_MIN_INTERVAL_MS:
        return

    if display_mode == DISPLAY_PATTERN:
        draw_pattern_screen()
    else:
        draw_rpm_screen()

    display_dirty = False
    last_display_ms = now


# Show initial pattern before waveform starts.
service_display(force=True)


# ============================================================
# PUSH BUTTONS
# Active LOW, using RP2040 internal pull-up
# ============================================================
button_left = Pin(BUTTON_LEFT_PIN, Pin.IN, Pin.PULL_UP)
button_center = Pin(BUTTON_CENTER_PIN, Pin.IN, Pin.PULL_UP)
button_right = Pin(BUTTON_RIGHT_PIN, Pin.IN, Pin.PULL_UP)

BUTTON_DEBOUNCE_MS = 30

button_state = {
    "left": {
        "pin": button_left,
        "last_raw": button_left.value(),
        "stable": button_left.value(),
        "changed_ms": ticks_ms(),
    },
    "center": {
        "pin": button_center,
        "last_raw": button_center.value(),
        "stable": button_center.value(),
        "changed_ms": ticks_ms(),
    },
    "right": {
        "pin": button_right,
        "last_raw": button_right.value(),
        "stable": button_right.value(),
        "changed_ms": ticks_ms(),
    },
}


def button_pressed(name, now):
    state = button_state[name]
    raw = state["pin"].value()

    if raw != state["last_raw"]:
        state["last_raw"] = raw
        state["changed_ms"] = now
        return False

    if raw != state["stable"] and ticks_diff(now, state["changed_ms"]) >= BUTTON_DEBOUNCE_MS:
        state["stable"] = raw
        if raw == 0:
            return True

    return False


def update_pattern_buttons():
    global browse_pattern_id

    now = ticks_ms()

    if button_pressed("left", now):
        browse_pattern_id -= 1
        if browse_pattern_id < PATTERN_MIN:
            browse_pattern_id = PATTERN_MAX

        request_pattern_screen()
        print("Browse pattern:", patterns[browse_pattern_id]["name"])

    if button_pressed("right", now):
        browse_pattern_id += 1
        if browse_pattern_id > PATTERN_MAX:
            browse_pattern_id = PATTERN_MIN

        request_pattern_screen()
        print("Browse pattern:", patterns[browse_pattern_id]["name"])

    if button_pressed("center", now):
        load_pattern(browse_pattern_id)
        request_pattern_screen()


# ============================================================
# ROTARY ENCODER KY-040
# ============================================================
encoder_a = Pin(ENCODER_A_PIN, Pin.IN, Pin.PULL_UP)
encoder_b = Pin(ENCODER_B_PIN, Pin.IN, Pin.PULL_UP)
encoder_sw = Pin(ENCODER_SW_PIN, Pin.IN, Pin.PULL_UP)

QUADRATURE = (
    0, -1, 1, 0,
    1, 0, 0, -1,
    -1, 0, 0, 1,
    0, 1, -1, 0,
)

encoder_last_state = (encoder_a.value() << 1) | encoder_b.value()
encoder_edge_count = 0
encoder_delta = 0


def encoder_irq(pin):
    global encoder_last_state, encoder_edge_count, encoder_delta

    new_state = (encoder_a.value() << 1) | encoder_b.value()
    encoder_edge_count += QUADRATURE[(encoder_last_state << 2) | new_state]
    encoder_last_state = new_state

    if encoder_edge_count >= 4:
        encoder_delta += 1
        encoder_edge_count = 0
    elif encoder_edge_count <= -4:
        encoder_delta -= 1
        encoder_edge_count = 0


encoder_a.irq(
    trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
    handler=encoder_irq,
)
encoder_b.irq(
    trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
    handler=encoder_irq,
)

switch_last_raw = encoder_sw.value()
switch_stable = switch_last_raw
switch_changed_ms = ticks_ms()


def update_encoder():
    global rpm, rpm_step, encoder_delta
    global switch_last_raw, switch_stable, switch_changed_ms

    delta = encoder_delta
    encoder_delta = 0

    if delta:
        rpm += delta * rpm_step
        rpm = max(RPM_MIN, min(RPM_MAX, rpm))
        request_rpm_screen()
        print("RPM:", rpm)

    # Encoder push switch remains available for 100 / 10 RPM step selection.
    now = ticks_ms()
    raw = encoder_sw.value()

    if raw != switch_last_raw:
        switch_last_raw = raw
        switch_changed_ms = now

    elif raw != switch_stable and ticks_diff(now, switch_changed_ms) >= 30:
        switch_stable = raw

        if switch_stable == 0:
            if rpm_step == RPM_STEP_NORMAL:
                rpm_step = RPM_STEP_FINE
            else:
                rpm_step = RPM_STEP_NORMAL

            request_rpm_screen()
            print("RPM step:", rpm_step)


# ============================================================
# PIO TIMING
# ============================================================
PIO_FREQUENCY = 1_000_000
PIO_PATH_OVERHEAD = 6
MAX_DELAY_COUNT = (1 << 28) - 1


def calculate_slot_time(target_rpm):
    if target_rpm <= 0:
        raise ValueError("rpm must be greater than zero")

    return int(60_000_000 / (target_rpm * slots_per_rev))


def make_word(first_state, second_state, half_time_us):
    delay_count = half_time_us - PIO_PATH_OVERHEAD

    if delay_count < 0:
        delay_count = 0
    if delay_count > MAX_DELAY_COUNT:
        delay_count = MAX_DELAY_COUNT

    return first_state | (second_state << 2) | (delay_count << 4)


def slot_word(cycle_slot_value, slot_time_us):
    tooth_position = cycle_slot_value % slots_per_rev

    cmp_level = 1 if cmp_start <= cycle_slot_value < cmp_end else 0
    cmp_state = cmp_level
    ckp_high_state = cmp_level | 0b10

    half_time_us = slot_time_us // 2

    if tooth_position in missing_slots:
        return make_word(cmp_state, cmp_state, half_time_us)

    if tooth_position == extra_tooth_slot:
        quarter_time_us = slot_time_us // 4
        return make_word(ckp_high_state, cmp_state, quarter_time_us)

    return make_word(ckp_high_state, cmp_state, half_time_us)


# ============================================================
# START PIO
# ============================================================
sm = rp2.StateMachine(
    0,
    ckp_cmp_pio,
    freq=PIO_FREQUENCY,
    out_base=Pin(CMP_PIN),
)

print("Pattern:", pattern["name"])
print("RPM:", rpm, "Step:", rpm_step)
sm.active(1)


# ============================================================
# MAIN LOOP
# ============================================================
try:
    while True:
        update_pattern_buttons()
        update_encoder()

        slot_time_us = calculate_slot_time(rpm)
        word = slot_word(cycle_slot, slot_time_us)

        # Feed one slot to PIO FIFO.
        sm.put(word)

        # 12+1: two pulses inside the special slot.
        if extra_tooth_slot is not None:
            if cycle_slot % slots_per_rev == extra_tooth_slot:
                sm.put(word)

        cycle_slot += 1
        if cycle_slot >= slots_per_rev * 2:
            cycle_slot = 0

        # OLED is refreshed only when an input changes something.
        service_display()

except KeyboardInterrupt:
    sm.active(0)
    Pin(CKP_PIN, Pin.OUT, value=0)
    Pin(CMP_PIN, Pin.OUT, value=0)
    oled.fill(0)
    oled.text("STOPPED", 36, 28)
    oled.show()
    print("Stopped")
