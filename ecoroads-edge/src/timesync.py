"""
Maps the phone's clock onto the laptop's clock.

Every message from the phone (video frame, GPS fix, accelerometer batch)
carries the PHONE's timestamp of when it was captured. The two clocks
are unrelated, so we estimate the offset between them:

    offset ≈ laptop_time_when_received - phone_time_when_captured

That difference = true clock offset + network delay. Network delay is
always >= 0 and varies, so the SMALLEST difference seen is the best
estimate (it's the message that happened to travel fastest). This is
the same idea NTP uses, simplified to one direction.

After that, phone_time + offset gives "laptop monotonic time when this
was captured", so camera frames, GPS fixes and jolts all share ONE
timeline — which is what fusion.py needs to match a jolt to a pothole.
"""

import threading
import time

WINDOW_S = 60.0   # forget old minima slowly so clock drift is tracked


class ClockSync:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._best = None        # smallest (arrival - phone) seen in window
        self._best_at = 0.0

    def observe(self, phone_ts_s, arrival=None):
        """Feed one (phone timestamp, arrival time). Returns the mapped laptop time."""
        arrival = self.clock() if arrival is None else arrival
        diff = arrival - phone_ts_s
        with self._lock:
            stale = self._best is not None and arrival - self._best_at > WINDOW_S
            if self._best is None or diff < self._best or stale:
                self._best, self._best_at = diff, arrival
            return phone_ts_s + self._best

    def to_laptop(self, phone_ts_s):
        with self._lock:
            if self._best is None:
                return self.clock()
            return phone_ts_s + self._best
