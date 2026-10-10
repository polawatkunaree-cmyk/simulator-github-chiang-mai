# RP2040-Zero / ST7789 240x320 TFT diagnostic, landscape 320x240.
# Uses the unchanged driver supplied in the user's V16 archive.
from machine import Pin, SPI
from time import sleep_ms
import sys
import rp2

TEST_BAUDRATE = 1_000_000  # Try 1_000_000 if the image is corrupted.


def run_test():
    print('\nTFT TEST START - 320x240 - SPI', TEST_BAUDRATE)
    # Stop existing PIO generators before taking GPIO14/15 low.
    for index in range(8):
        rp2.StateMachine(index).active(0)
    Pin(14, Pin.OUT, value=0)
    Pin(15, Pin.OUT, value=0)
    # Deselect touch BEFORE configuring the shared SPI bus.
    touch_cs = Pin(6, Pin.OUT, value=1)
    cs = Pin(1, Pin.OUT, value=1)
    from st7789_pico import ST7789, BLACK, WHITE, RED, GREEN, BLUE

    class TestDisplay(ST7789):
        def _spi_tft(self):
            # The original driver otherwise forces 40 MHz on every write.
            self.spi.init(baudrate=TEST_BAUDRATE, polarity=0, phase=0)

    spi = SPI(0, baudrate=TEST_BAUDRATE, polarity=0, phase=0,
              sck=Pin(2), mosi=Pin(3), miso=Pin(0))
    print('Initializing display...')
    tft = TestDisplay(spi, cs=cs, dc=Pin(4, Pin.OUT, value=0),
                      reset=Pin(5, Pin.OUT, value=1), rotation=1)
    print('Init commands sent. Visual inspection is required.')
    colors = [('RED', RED), ('GREEN', GREEN), ('BLUE', BLUE),
              ('WHITE', WHITE), ('BLACK', BLACK)]
    cycle = 0
    while True:
        cycle += 1
        print('CYCLE', cycle)
        for name, color in colors:
            print('FULL SCREEN:', name)
            tft.fill(color)
            tft.show()
            sleep_ms(2000)
        print('COLOR BARS + TEXT + BORDER')
        tft.fill(BLACK)
        for i, (_, color) in enumerate(colors):
            tft.fill_rect(i * 64, 32, 64, 160, color)
        tft.rect(0, 0, 320, 240, WHITE)
        tft.rect(2, 2, 316, 236, WHITE)
        tft.text('ST7789 TFT TEST 320x240', 24, 12, WHITE)
        tft.text('R', 28, 200, WHITE)
        tft.text('G', 92, 200, WHITE)
        tft.text('B', 156, 200, WHITE)
        tft.text('W', 220, 200, WHITE)
        tft.text('K', 284, 200, WHITE)
        tft.text('TL', 6, 24, WHITE)
        tft.text('TR', 296, 24, WHITE)
        tft.text('BL', 6, 222, WHITE)
        tft.text('BR', 296, 222, WHITE)
        tft.show()
        sleep_ms(5000)
        print('CHECKERBOARD + DIAGONALS')
        tft.fill(BLACK)
        for y in range(0, 240, 20):
            for x in range(0, 320, 20):
                if ((x // 20) + (y // 20)) % 2 == 0:
                    tft.fill_rect(x, y, 20, 20, WHITE)
        tft.line(0, 0, 319, 239, RED)
        tft.line(319, 0, 0, 239, GREEN)
        tft.rect(0, 0, 320, 240, BLUE)
        tft.show()
        sleep_ms(5000)
        print('MOVING BOX - look for continuous movement')
        for x in range(0, 289, 8):
            tft.fill(BLACK)
            tft.text('MOVING BOX / CYCLE ' + str(cycle), 16, 16, WHITE)
            tft.rect(0, 0, 320, 240, WHITE)
            tft.fill_rect(x, 104, 32, 32, GREEN)
            tft.show()
            sleep_ms(60)


try:
    run_test()
except KeyboardInterrupt:
    print('TFT TEST STOPPED')
except Exception as exc:
    print('TFT TEST ERROR:')
    sys.print_exception(exc)
    raise
