CKP/CMP Simulator - RP2040-Zero V7

Upload these three files to the board:
  main.py
  st7735_pico.py
  xpt2046_pico.py

V7 adds RPM button auto-repeat:
  - Tap -100 or +100: change 100 RPM once.
  - Hold for 0.5 seconds: repeat automatically.
  - Hold for 2 seconds: accelerate to 500 RPM per repeat.
  - Release or slide outside the button: stop immediately.

Signal generation, pins, pattern selection, and touch calibration are unchanged.

Vehicle names are examples only. Trigger patterns can differ by engine, model
year, market, ECU, and aftermarket trigger wheel. Verify the actual CKP and CMP
waveforms before connecting the simulator to an ECU.

Mitsubishi and Isuzu are not assigned to a pattern because the six generic
patterns in this program do not reliably identify their OEM trigger systems.
