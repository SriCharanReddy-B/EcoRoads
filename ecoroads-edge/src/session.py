"""
Drive sessions: record every real drive, replay it later.

A session folder (ecoroads-edge/sessions/2026-10-12_0815_car_01/):
    video.mp4    what the camera saw
    frames.csv   t (s since start) of every video frame
    gps.csv      t, lat, lon, speed_mps, accuracy_m
    motion.csv   t, ax, ay, az   (g)
    meta.json    vehicle, start time, settings

Why record:
  1. Re-run detection later with a better model or new thresholds on
     EXACTLY the same drive — a fair before/after comparison for your report.
  2. Classroom demo = replay of a real drive: real road, real GPS, real
     jolts, with zero risk of a live demo failing.
  3. New training data from your own roads.

Recordings never leave the laptop — the cloud still only ever receives
the 5-field payload. (They are large: keep sessions/ out of git/OneDrive.)
"""

import bisect
import csv
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2

from video_source import FileSource

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"


class SessionRecorder:
    def __init__(self, vehicle_id, settings=None, root=SESSIONS_DIR, clock=time.monotonic, fps=15):
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.dir = Path(root) / f"{stamp}_{vehicle_id}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.t0 = None
        self.fps = fps
        self.size = None
        self.writer = None
        self.frames_written = 0
        self._frames = self._open("frames.csv", ["frame", "t"])
        self._gps = self._open("gps.csv", ["t", "lat", "lon", "speed_mps", "accuracy_m"])
        self._motion = self._open("motion.csv", ["t", "ax", "ay", "az"])
        self._last_gps = None
        (self.dir / "meta.json").write_text(json.dumps({
            "vehicle_id": vehicle_id,
            "started_local": datetime.now().isoformat(timespec="seconds"),
            "started_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "settings": settings or {},
        }, indent=2))

    def _open(self, name, header):
        f = open(self.dir / name, "w", newline="")
        w = csv.writer(f)
        w.writerow(header)
        return f, w

    def _rel(self, t):
        if self.t0 is None:
            self.t0 = t
        return round(t - self.t0, 4)

    def frame(self, frame, t):
        if self.size is None:
            self.size = (frame.shape[1], frame.shape[0])
            self.writer = cv2.VideoWriter(str(self.dir / "video.mp4"),
                                          cv2.VideoWriter_fourcc(*"mp4v"), self.fps, self.size)
        if (frame.shape[1], frame.shape[0]) != self.size:
            frame = cv2.resize(frame, self.size)
        self.writer.write(frame)
        self._frames[1].writerow([self.frames_written, self._rel(t)])
        self.frames_written += 1
        if self.frames_written % 30 == 0:   # flush ~every 2 s so a crash loses little
            for f, _ in (self._frames, self._gps, self._motion):
                f.flush()

    def gps(self, t, lat, lon, speed=None, accuracy=None):
        if (lat, lon) == self._last_gps:
            return
        self._last_gps = (lat, lon)
        self._gps[1].writerow([self._rel(t), lat, lon, speed, accuracy])

    def motion(self, rows):
        for t, _dev, ax, ay, az in rows:
            self._motion[1].writerow([self._rel(t), round(ax, 4), round(ay, 4), round(az, 4)])

    def on_bridge_event(self, kind, payload):
        """Listener for PhoneBridge: records phone GPS + motion as they arrive."""
        if kind == "gps":
            t, lat, lon, speed, acc = payload
            self.gps(t, lat, lon, speed, acc)
        elif kind == "motion":
            self.motion(payload)

    def close(self):
        if self.writer:
            self.writer.release()
        for f, _ in (self._frames, self._gps, self._motion):
            f.close()
        return self.dir


# ---------------------------------------------------------------- replay

def _read_csv(path):
    if not Path(path).exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class ReplaySource(FileSource):
    def __init__(self, session_dir, realtime=True):
        session_dir = Path(session_dir)
        times = [float(r["t"]) for r in _read_csv(session_dir / "frames.csv")] or None
        super().__init__(session_dir / "video.mp4", timestamps=times, realtime=realtime)


class ReplayGPS:
    """GPS positions from a recording, interpolated at the video's current time."""

    def __init__(self, session_dir, clock):
        rows = _read_csv(Path(session_dir) / "gps.csv")
        self.t = [float(r["t"]) for r in rows]
        self.lat = [float(r["lat"]) for r in rows]
        self.lon = [float(r["lon"]) for r in rows]
        self.speed = [float(r["speed_mps"]) if r["speed_mps"] not in ("", "None") else None
                      for r in rows]
        self.clock = clock

    def position_at(self, t):
        if not self.t:
            return None
        i = bisect.bisect_left(self.t, t)
        if i <= 0:
            return self.lat[0], self.lon[0]
        if i >= len(self.t):
            return self.lat[-1], self.lon[-1]
        t0, t1 = self.t[i - 1], self.t[i]
        a = (t - t0) / (t1 - t0) if t1 > t0 else 0
        return (self.lat[i - 1] + a * (self.lat[i] - self.lat[i - 1]),
                self.lon[i - 1] + a * (self.lon[i] - self.lon[i - 1]))

    def get_current_position(self):
        return self.position_at(self.clock())

    def get_speed_mps(self):
        if not self.t:
            return 0.0
        i = min(max(bisect.bisect_left(self.t, self.clock()), 0), len(self.t) - 1)
        return self.speed[i] or 0.0

    def close(self):
        pass


class ReplayAccel:
    def __init__(self, session_dir):
        rows = _read_csv(Path(session_dir) / "motion.csv")
        self.t = [float(r["t"]) for r in rows]
        self.dev = [abs(math.sqrt(float(r["ax"]) ** 2 + float(r["ay"]) ** 2 + float(r["az"]) ** 2) - 1)
                    for r in rows]

    def peak_jolt(self, t0, t1):
        i, j = bisect.bisect_left(self.t, t0), bisect.bisect_right(self.t, t1)
        return max(self.dev[i:j]) if j > i else None

    def has_data(self):
        return bool(self.t)

    def close(self):
        pass


def recorded_wall_time(session_dir):
    """Function t -> ISO UTC time at which that moment of the drive happened (None if unknown)."""
    meta_path = Path(session_dir) / "meta.json"
    try:
        start = datetime.fromisoformat(json.loads(meta_path.read_text())["started_utc"])
    except (OSError, KeyError, ValueError):
        return None
    return lambda t: (start + timedelta(seconds=t)).isoformat()


def latest_session(root=SESSIONS_DIR):
    root = Path(root)
    dirs = sorted(d for d in root.glob("*") if (d / "video.mp4").exists()) if root.exists() else []
    return dirs[-1] if dirs else None
