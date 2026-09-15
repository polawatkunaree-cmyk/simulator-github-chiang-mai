CKP/CMP Simulator V12 - Isuzu D-Max 4JK1-TC / 4JJ1-TC

Pattern 7: ISUZU / 112 CKP + 5 CMP
- Complete signal cycle: 720 crank degrees
- CKP: 56 active-low pulses per crank revolution (112 per 720 degrees)
- Base grid: 60 slots x 6 crank degrees
- Missing positions: 56, 57, 58, 59
- CKP reference interval: 30 crank degrees from one falling edge to the next
- Missing-tooth region: HIGH, matching CH2 in the service-training waveform
- CMP: five active-low pulses per 720 degrees
- Four main CMP falling edges: 171, 351, 531, 711 crank degrees
- Reference CMP falling edge: 321 crank degrees
- Reference-to-adjacent-main falling-edge spacing: 30 crank degrees
- Reference CMP rising edge: 333 degrees, aligned with the last CKP rising
  edge before the missing-tooth interval
- Adjacent main CMP rising edge: 363 degrees, aligned with the first CKP rising
  edge after the missing-tooth interval
- CMP pulse width used by this 3-degree-resolution generator: 12 crank degrees
- Stopped/idle output level for this pattern: HIGH

IMPORTANT
The Isuzu training manual specifies the CKP count/grid/gap, CMP count and their
relationship graphically. It does not publish a numeric edge table. V12 corrects
the earlier V11 error that placed CMP at an arbitrary cycle zero without locking
it to the CKP missing-tooth edges. The placement above is digitised from the
drawing at the simulator's nearest 3-degree half-slot. Verify polarity, phase
and voltage at the ECU connector with an oscilloscope before relying on sync.

Upload main.py, st7735_pico.py and xpt2046_pico.py. Keep the touch_cal_v2.json
already stored on your RP2040-Zero; it contains the calibration for your screen.

Do not connect RP2040 GPIO directly to the ECU. Use the protected open-collector
5 V interface, common signal ground, current limiting and automotive transient
protection. Bench-test the ECU with injectors/actuators disconnected or suitable
dummy loads. Never combine this free-running signal with a physically cranking
engine.
