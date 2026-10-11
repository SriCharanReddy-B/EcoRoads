"""
Turns a stream of per-frame detections into one record per pothole.

The problem: at ~15 processed frames per second, a pothole stays in view
for 1-2 seconds, so the raw loop would log the SAME pothole 15-30 times.
That floods the local DB and the sync payload, and it makes the cloud's
"how many vehicles confirmed this" logic meaningless.

The fix is an "event": detections that keep arriving with short gaps
belong to one pothole. While the event is open we only remember its
worst (max-severity) frame. When no detection has arrived for
`gap_s` seconds, the event closes and is logged exactly once.

A very long stretch of broken road would otherwise become one giant
event, so an event is also closed once the vehicle has moved more than
`max_span_m` from where it started.
"""

import math
from dataclasses import dataclass, field


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@dataclass
class HazardEvent:
    first_t: float            # monotonic seconds when first seen
    last_t: float             # monotonic seconds when last seen
    start_lat: float
    start_lon: float
    lat: float                # position of the worst frame
    lon: float
    severity_pct: float       # worst (max) camera severity seen
    wall_time_iso: str        # UTC ISO timestamp of the worst frame (what gets stored)
    speed_mps: float = 0.0
    frames: int = 1
    max_conf: float = 0.0     # highest YOLO confidence seen (used to filter false positives)
    # picture of the worst frame (with boxes); kept on this laptop only, never uploaded
    snapshot: object = field(default=None, repr=False, compare=False)


class Debouncer:
    def __init__(self, gap_s=1.5, max_span_m=30.0):
        self.gap_s = gap_s
        self.max_span_m = max_span_m
        self.current = None

    def add(self, t, lat, lon, severity_pct, wall_time_iso, speed_mps=0.0, conf=0.0, snapshot=None):
        """
        Feed ONE detection (the strongest box of a frame). Returns a list of
        events that closed because of it (usually empty).
        """
        closed = []
        ev = self.current
        if ev is not None:
            too_late = t - ev.last_t > self.gap_s
            too_far = haversine_m(ev.start_lat, ev.start_lon, lat, lon) > self.max_span_m
            if too_late or too_far:
                closed.append(ev)
                ev = self.current = None

        if ev is None:
            self.current = HazardEvent(t, t, lat, lon, lat, lon, severity_pct,
                                       wall_time_iso, speed_mps, max_conf=conf, snapshot=snapshot)
        else:
            ev.last_t = t
            ev.frames += 1
            ev.speed_mps = speed_mps
            ev.max_conf = max(ev.max_conf, conf)
            if severity_pct > ev.severity_pct:
                ev.severity_pct = severity_pct
                ev.lat, ev.lon = lat, lon
                ev.wall_time_iso = wall_time_iso
                if snapshot is not None:
                    ev.snapshot = snapshot
        return closed

    def tick(self, t):
        """Call every frame (detection or not). Returns the event if it just closed."""
        if self.current is not None and t - self.current.last_t > self.gap_s:
            ev, self.current = self.current, None
            return [ev]
        return []

    def flush(self):
        """Close whatever is open (e.g. on shutdown) so nothing is lost."""
        if self.current is None:
            return []
        ev, self.current = self.current, None
        return [ev]
