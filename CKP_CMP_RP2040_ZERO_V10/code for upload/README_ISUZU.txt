CKP/CMP Simulator V10 - Isuzu test patterns

Pattern 7: ISUZU / CKP TEST ONLY
- CKP: 56 pulses per crank revolution
- Base grid: 60 slots x 6 crank degrees
- Missing positions: 56, 57, 58, 59
- Reference interval: 30 crank degrees from the last rising edge to the next
- CMP: held LOW

Pattern 8: ISU-1C / 1CMP EXPERIMENT
- Same CKP as Pattern 7
- CMP: one HIGH window per 720-degree engine cycle
- CMP HIGH: slots 10 through 19 of the first crank revolution
- CMP width: 10 slots = 60 crank degrees
- CMP begins: 60 crank degrees after slot zero
- CMP remains LOW throughout the second crank revolution

IMPORTANT
The production 4JK1/4JJ1 system uses five CMP pulses per 720 degrees. Pattern 8
is an arbitrary one-pulse diagnostic experiment and is not a verified Isuzu
full-sync waveform. It may show engine RPM but is not expected to establish
correct CKP/CMP synchronization. Do not feed this free-running signal to an
engine while it is physically cranking. Use a protected ECU-compatible output
interface rather than connecting RP2040 GPIO directly to an ECU input.
