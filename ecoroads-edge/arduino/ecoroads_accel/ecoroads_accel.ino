/*
  EcoRoads — MPU6050 accelerometer streamer (Arduino Uno / Nano).

  Wiring (MPU6050 -> Arduino):
    VCC -> 5V      GND -> GND
    SDA -> A4      SCL -> A5        (Uno/Nano)

  Output on USB serial @ 115200 baud, ~100 lines per second:
    ax,ay,az        acceleration in g, e.g.  0.012,-0.034,1.004

  No external library needed: talks to the sensor's registers directly
  over I2C (Wire). Range is set to +/-4 g so a hard pothole hit
  (often 2-3 g) doesn't clip at the +/-2 g default.

  Mounting: screw/zip-tie the board RIGIDLY to the vehicle body (not a
  foam pad) — loose mounting adds its own wobble and hides real jolts.
*/

#include <Wire.h>

const uint8_t MPU_ADDR = 0x68;
const float LSB_PER_G = 8192.0;      // +/-4 g range
const unsigned long PERIOD_MS = 10;  // 100 Hz

void writeReg(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);
  writeReg(0x6B, 0x00);  // PWR_MGMT_1: wake up
  writeReg(0x1C, 0x08);  // ACCEL_CONFIG: +/-4 g
  writeReg(0x1A, 0x03);  // CONFIG: ~44 Hz low-pass, removes engine buzz
  delay(100);
}

void loop() {
  static unsigned long last = 0;
  unsigned long now = millis();
  if (now - last < PERIOD_MS) return;
  last = now;

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);                       // ACCEL_XOUT_H
  if (Wire.endTransmission(false) != 0) { // sensor unplugged?
    Serial.println("ERR");
    return;
  }
  Wire.requestFrom(MPU_ADDR, (uint8_t)6);
  int16_t ax = (Wire.read() << 8) | Wire.read();
  int16_t ay = (Wire.read() << 8) | Wire.read();
  int16_t az = (Wire.read() << 8) | Wire.read();

  Serial.print(ax / LSB_PER_G, 3); Serial.print(',');
  Serial.print(ay / LSB_PER_G, 3); Serial.print(',');
  Serial.println(az / LSB_PER_G, 3);
}
