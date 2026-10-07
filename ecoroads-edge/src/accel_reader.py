"""
Reads the Arduino + MPU6050 accelerometer over USB serial.

The Arduino (firmware in ../arduino/ecoroads_accel/) prints one line per
sample at ~100 Hz:

    ax,ay,az        (in g, e.g.  0.02,-0.01,1.03)

TIME SYNC — the important design choice: the Arduino's millis() clock
and the laptop's clock are unrelated, so we don't trust the Arduino's
timestamps at all. Each line is stamped with the LAPTOP's monotonic
clock the moment it arrives. USB serial latency is a few milliseconds,
far smaller than the ~0.5 s it takes a car to travel from "camera sees
pothole" to "wheel hits pothole", so this is accurate enough and keeps
both data streams (camera + accelerometer) on ONE clock.

A jolt is measured as how far the total acceleration deviates from
1 g (gravity at rest). Driving smoothly stays near 0; a pothole hit
produces a sharp spike of 0.5-2 g.
"""

import collections
import math
import threading
import time

BUFFER_SECONDS = 15


class AccelReader:
    def __init__(self, port, baud=115200):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=1)
        self.samples = collections.deque()  # (monotonic_t, deviation_g)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        print(f"[accel] reading MPU6050 on {port}")

    def _run(self):
        while not self._stop.is_set():
            try:
                line = self.ser.readline().decode("ascii", "ignore").strip()
            except Exception as e:
                print(f"[accel] serial error: {e}")
                time.sleep(1)
                continue
            dev = parse_sample(line)
            if dev is None:
                continue
            now = time.monotonic()
            with self._lock:
                self.samples.append((now, dev))
                while self.samples and now - self.samples[0][0] > BUFFER_SECONDS:
                    self.samples.popleft()

    def peak_jolt(self, t_start, t_end):
        """Largest deviation from 1 g between two monotonic timestamps, or None."""
        with self._lock:
            vals = [d for t, d in self.samples if t_start <= t <= t_end]
        return max(vals) if vals else None

    def close(self):
        self._stop.set()
        self.ser.close()


def parse_sample(line):
    """'ax,ay,az' in g -> |a| deviation from 1 g, or None for junk lines."""
    parts = line.split(",")
    if len(parts) != 3:
        return None
    try:
        ax, ay, az = (float(p) for p in parts)
    except ValueError:
        return None
    return abs(math.sqrt(ax * ax + ay * ay + az * az) - 1.0)


if __name__ == "__main__":
    import sys
    port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
    r = AccelReader(port)
    print("Tap/shake the sensor. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
            now = time.monotonic()
            print(f"peak jolt last 1s: {r.peak_jolt(now - 1, now)}")
    except KeyboardInterrupt:
        r.close()
