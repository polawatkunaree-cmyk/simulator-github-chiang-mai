CKP/CMP Simulator - RP2040-Zero V8

Upload these three files to the board:
  main.py
  st7735_pico.py
  xpt2046_pico.py

V7/V8 RPM button auto-repeat:
  - Tap -100 or +100: change 100 RPM once.
  - Hold for 0.5 seconds: repeat automatically.
  - Hold for 2 seconds: accelerate to 500 RPM per repeat.
  - Release or slide outside the button: stop immediately.

Signal generation, pins, pattern selection, and touch calibration are unchanged.

V8 touch response improvements:
  - Touch SPI reduced from 2 MHz to 1 MHz for reliable jumper-wire operation.
  - Stable-point tolerance increased from 12 to 20 screen pixels.
  - An 80 ms release grace ignores brief T_IRQ dropouts.
  - Existing touch_cal_v2.json calibration remains valid; do not delete it.

Vehicle names are examples only. Trigger patterns can differ by engine, model
year, market, ECU, and aftermarket trigger wheel. Verify the actual CKP and CMP
waveforms before connecting the simulator to an ECU.

Mitsubishi and Isuzu are not assigned to a pattern because the six generic
patterns in this program do not reliably identify their OEM trigger systems.
