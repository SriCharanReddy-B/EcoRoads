"""
Phone bridge, clock sync, drive recording/replay and the drive report.
No phone, camera or model needed.   Run:  python -m pytest tests -q
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "tools"))

from timesync import ClockSync                                         # noqa: E402
from phone_bridge import PhoneAccel, PhoneBridge, PhoneFrameSource, PhoneGPS  # noqa: E402
from session import ReplayAccel, ReplayGPS, ReplaySource, SessionRecorder    # noqa: E402
from video_source import FileSource                                   # noqa: E402


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


# ---------------- clock sync ----------------
def test_clock_sync_takes_fastest_message():
    clk = FakeClock()
    sync = ClockSync(clk)
    # true offset: laptop = phone + 500; network delays 0.08, 0.02, 0.15 s
    for phone_t, delay in [(10.0, 0.08), (11.0, 0.02), (12.0, 0.15)]:
        clk.t = phone_t + 500 + delay
        sync.observe(phone_t)
    assert abs(sync.to_laptop(20.0) - 520.02) < 1e-9


# ---------------- phone bridge over real HTTP ----------------
def _post(url, data, headers):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def test_bridge_end_to_end_http():
    b = PhoneBridge(port=18443, use_tls=False, max_gps_accuracy_m=30,
                    phone_settings={"width": 640}).start()
    try:
        base = "http://127.0.0.1:18443"
        page = urllib.request.urlopen(base + "/").read()
        assert b"EcoRoads phone sensor" in page
        assert json.loads(urllib.request.urlopen(base + "/config.json").read())["width"] == 640

        phone_now_ms = 5_000_000.0
        img = np.zeros((360, 640, 3), np.uint8)
        img[:, :, 2] = 200
        jpeg = cv2.imencode(".jpg", img)[1].tobytes()
        assert _post(base + "/frame", jpeg, {"X-Capture-Ts": str(phone_now_ms)}) == 204

        sensors = {"gps": [{"t": phone_now_ms, "lat": 17.4, "lon": 78.4, "speed": 8.0, "accuracy": 6},
                           {"t": phone_now_ms + 1, "lat": 0.0, "lon": 0.0, "speed": None, "accuracy": 120}],
                   "motion": [[phone_now_ms, 0, 1.0, 0], [phone_now_ms + 10, 0, 2.2, 0]]}
        assert _post(base + "/sensors", json.dumps(sensors).encode(),
                     {"Content-Type": "application/json"}) == 204

        ok, frame, t = PhoneFrameSource(b, timeout_s=2).read()
        assert ok and frame.shape == (360, 640, 3) and frame[:, :, 2].mean() > 150

        gps = PhoneGPS(b)
        assert gps.get_current_position() == (17.4, 78.4)      # the ±120 m fix was rejected
        assert gps.get_speed_mps() == 8.0
        assert b.stats["gps_rejected"] == 1

        jolt = PhoneAccel(b).peak_jolt(t - 5, t + 5)
        assert abs(jolt - 1.2) < 1e-6                           # 2.2 g -> 1.2 g above gravity

        status = json.loads(urllib.request.urlopen(base + "/status").read())
        assert status["frames"] == 1 and status["last_fix"] == [17.4, 78.4]
    finally:
        b.stop()


def test_bridge_rejects_bad_payload():
    b = PhoneBridge(port=18444, use_tls=False).start()
    try:
        try:
            _post("http://127.0.0.1:18444/sensors", b"not json", {})
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        b.stop()


# ---------------- record -> replay ----------------
def test_record_and_replay_roundtrip(tmp_path):
    clk = FakeClock(100.0)
    rec = SessionRecorder("car_09", root=tmp_path, clock=clk, fps=10)
    for i in range(20):                                   # 2 s of video at 10 fps
        t = 100.0 + i * 0.1
        f = np.full((120, 160, 3), i * 10, np.uint8)
        rec.frame(f, t)
        if i % 5 == 0:
            rec.gps(t, 17.40 + i * 1e-4, 78.40, 8.0, 5)
    rec.motion([(100.95, 0.9, 0, 1.9, 0), (101.5, 0.0, 0, 1.0, 0)])
    sdir = rec.close()

    src = ReplaySource(sdir, realtime=False)
    times = []
    while True:
        ok, frame, t = src.read()
        if not ok:
            break
        times.append(t)
    assert len(times) == 20 and abs(times[-1] - 1.9) < 1e-6

    gps = ReplayGPS(sdir, clock=lambda: 0.75)             # halfway between fixes at 0.5 and 1.0
    lat, lon = gps.get_current_position()
    assert abs(lat - 17.40075) < 1e-9 and lon == 78.40

    acc = ReplayAccel(sdir)
    assert abs(acc.peak_jolt(0.9, 1.0) - 0.9) < 1e-6
    assert acc.peak_jolt(1.6, 1.9) is None


def test_file_source_plays_in_real_time(tmp_path):
    path = str(tmp_path / "c.avi")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 20, (64, 48))
    for _ in range(10):
        w.write(np.zeros((48, 64, 3), np.uint8))
    w.release()
    src = FileSource(path, realtime=True)
    start = time.monotonic()
    n = 0
    while src.read()[0]:
        n += 1
    elapsed = time.monotonic() - start
    assert n >= 9 and 0.35 <= elapsed <= 1.0          # 10 frames @ 20 fps ≈ 0.45 s


# ---------------- drive report ----------------
def test_drive_report_scoring():
    try:
        import drive_report          # lives in the repo's tools/ (not in the edge download)
    except ImportError:
        return
    truth = [{"name": "P1", "lat": 17.40000, "lon": 78.40000, "size": "L"},
             {"name": "P2", "lat": 17.40100, "lon": 78.40000, "size": "S"}]
    dets = [{"vehicle_id": "c", "timestamp": "x", "lat": 17.40005, "lon": 78.40000, "severity_pct": 70},
            {"vehicle_id": "c", "timestamp": "y", "lat": 17.40300, "lon": 78.40000, "severity_pct": 40}]
    results, unmatched, summary = drive_report.score(truth, dets)
    assert summary["detected"] == 1 and summary["recall_pct"] == 50.0
    assert results[0]["gps_error_m"] == 5.6 and not results[1]["detected"]
    assert len(unmatched) == 1
    assert "recall **50.0%**" in drive_report.to_markdown(results, unmatched, summary)
