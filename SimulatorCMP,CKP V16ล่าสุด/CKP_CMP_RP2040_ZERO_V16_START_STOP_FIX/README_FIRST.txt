CKP/CMP RP2040 ZERO - V16 ULTRA FAST + TOUCH LOCK

Changes from V15:
- Keeps V15 partial-screen updates and fast display.
- Touch hit padding increased slightly.
- +/- buttons now use touch capture / hysteresis after the initial press.
  Small finger movement no longer cancels a held button.
- T_IRQ dropout grace increased to 220 ms for resistive-panel movement jitter.
- CKP/CMP generation logic is unchanged.
- Existing touch_cal_st7789_v13.json can be kept.

Upload/overwrite:
  main.py
  st7789_pico.py
  xpt2046_pico.py
Then Hard Reset.
