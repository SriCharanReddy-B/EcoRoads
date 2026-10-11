"""
Edge-node unit tests — no webcam, model, GPS or Arduino needed.
Run from ecoroads-edge:   python -m pytest tests -q
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from debouncer import Debouncer, haversine_m           # noqa: E402
from fusion import fuse, jolt_to_severity_pct, rejection_reason  # noqa: E402
from gps_nmea import parse_nmea                         # noqa: E402
from accel_reader import parse_sample                   # noqa: E402
from severity import compute_severity_pct               # noqa: E402
import storage                                          # noqa: E402

LAT, LON = 17.4075, 78.4775


def nmea(body):
    """Build a sentence with a correct checksum."""
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"${body}*{cs:02X}"


# ---------------- severity ----------------
def test_severity_range_and_cap():
    assert compute_severity_pct(0.95, 15.0) <= 100.0
    assert 0 <= compute_severity_pct(0.4, 1.0) < 30
    assert compute_severity_pct(0.85, 6.0) > compute_severity_pct(0.4, 1.0)


# ---------------- debouncer ----------------
def test_one_pothole_over_many_frames_is_logged_once():
    d = Debouncer(gap_s=1.5, max_span_m=15)
    closed = []
    # 20 frames, 0.07 s apart, severity peaks in the middle
    for i in range(20):
        sev = 40 + (10 - abs(10 - i)) * 3
        closed += d.add(i * 0.07, LAT, LON + i * 1e-6, sev, f"t{i}", 8.3)
    assert closed == []                           # still open
    closed += d.tick(1.33 + 1.6)                  # silence > gap
    assert len(closed) == 1
    ev = closed[0]
    assert ev.frames == 20
    assert ev.severity_pct == 70                  # the worst frame kept
    assert ev.wall_time_iso == "t10"


def test_two_potholes_separated_in_time_are_two_events():
    d = Debouncer(gap_s=1.5)
    out = d.add(0.0, LAT, LON, 50, "a")
    out += d.add(0.1, LAT, LON, 55, "a2")
    out += d.add(5.0, LAT + 0.0003, LON, 60, "b")   # 5 s later
    out += d.flush()
    assert [e.severity_pct for e in out] == [55, 60]


def test_long_stretch_is_split_by_distance():
    d = Debouncer(gap_s=1.5, max_span_m=15)
    out = []
    for i in range(30):                              # ~1.1 m per step, continuous detections
        out += d.add(i * 0.1, LAT + i * 1e-5, LON, 50, str(i))
    out += d.flush()
    assert len(out) >= 2
    assert abs(haversine_m(LAT, LON, LAT + 1e-4, LON) - 11.1) < 0.2


# ---------------- fusion ----------------
class FakeAccel:
    def __init__(self, samples):
        self.samples = samples

    def peak_jolt(self, a, b):
        vals = [d for t, d in self.samples if a <= t <= b]
        return max(vals) if vals else None


def _event(first, last, sev=60.0, speed=8.3):
    return SimpleNamespace(first_t=first, last_t=last, severity_pct=sev, speed_mps=speed)


def test_fusion_without_sensor_keeps_camera_severity():
    assert fuse(_event(0, 1), None, 4.0, 1.5) == (60.0, None)


def test_fusion_blends_when_wheel_hits_after_camera():
    # camera saw it 0..1 s; wheel hits at 1.4 s (4 m / 8.3 m/s ≈ 0.48 s later)
    accel = FakeAccel([(0.5, 0.05), (1.4, 1.5), (3.5, 2.0)])   # 3.5 s jolt is a different bump
    sev, jolt = fuse(_event(0, 1), accel, 4.0, 1.5)
    assert jolt == 1.5
    assert sev == round(0.6 * 60 + 0.4 * 100, 1)


def test_fusion_ignores_small_vibration():
    accel = FakeAccel([(1.2, 0.1)])
    assert fuse(_event(0, 1), accel, 4.0, 1.5)[0] == 60.0


def test_jolt_mapping_clamped():
    assert jolt_to_severity_pct(0.1) == 0
    assert jolt_to_severity_pct(5) == 100


# ---------------- GPS / accel parsing ----------------
def test_parse_rmc():
    fix = parse_nmea(nmea("GPRMC,123519,A,1724.4500,N,07828.6500,E,016.2,084.4,071026,,,A"))
    assert abs(fix["lat"] - 17.4075) < 1e-6
    assert abs(fix["lon"] - 78.4775) < 1e-6
    assert abs(fix["speed_mps"] - 16.2 * 0.514444) < 1e-6


def test_parse_rejects_void_fix_and_bad_checksum():
    assert parse_nmea(nmea("GPRMC,123519,V,,,,,,,071026,,,N")) is None
    good = nmea("GNGGA,123519,1724.4500,N,07828.6500,E,1,08,0.9,545.4,M,46.9,M,,")
    assert parse_nmea(good)["lat"] > 17
    assert parse_nmea(good[:-2] + "00") is None


def test_parse_southern_western_hemisphere():
    fix = parse_nmea(nmea("GPRMC,0,A,3352.0000,S,15112.0000,W,0,0,071026,,,A"))
    assert fix["lat"] < 0 and fix["lon"] < 0


def test_accel_sample_parsing():
    assert parse_sample("0,0,1.0") == 0
    assert abs(parse_sample("0,0,2.5") - 1.5) < 1e-9
    assert parse_sample("ERR") is None


# ---------------- storage ----------------
def test_storage_roundtrip(tmp_path):
    conn = storage.get_connection(tmp_path / "t.db")
    storage.log_hazard(conn, "car_01", LAT, LON, 55.5)
    storage.log_hazard(conn, "car_01", LAT, LON, 60.0)
    rows = storage.unsynced_rows(conn)
    assert len(rows) == 2 and storage.unsynced_count(conn) == 2
    storage.mark_synced(conn, [rows[0]["id"]])
    assert storage.unsynced_count(conn) == 1


# ---- false-positive filters (tree shadows, stains) ----

def _ev(frames=20, conf=0.6, speed=8.0):
    return SimpleNamespace(frames=frames, max_conf=conf, speed_mps=speed)


def test_flicker_is_rejected():
    assert "frame" in rejection_reason(_ev(frames=2), None)


def test_unsure_detection_without_bump_while_moving_is_rejected():
    assert "shadow" in rejection_reason(_ev(conf=0.55), jolt_g=0.05)


def test_unsure_detection_with_bump_is_kept():
    assert rejection_reason(_ev(conf=0.55), jolt_g=0.9) is None


def test_confident_detection_kept_without_bump():
    # driver may have steered around a real pothole
    assert rejection_reason(_ev(conf=0.85), jolt_g=0.05) is None


def test_no_motion_data_or_standing_still_skips_jolt_rule():
    assert rejection_reason(_ev(conf=0.55), jolt_g=None) is None          # sensor off
    assert rejection_reason(_ev(conf=0.55, speed=0.0), jolt_g=0.0) is None  # desk test


def test_jolt_rule_can_be_turned_off():
    assert rejection_reason(_ev(conf=0.55), jolt_g=0.0, confirm_below_conf=0) is None


def test_debouncer_tracks_max_confidence():
    d = Debouncer(gap_s=1.0)
    d.add(0.0, 17.0, 78.0, 50, "t0", 8.0, conf=0.6)
    d.add(0.1, 17.0, 78.0, 40, "t1", 8.0, conf=0.8)
    ev = d.flush()[0]
    assert ev.max_conf == 0.8 and ev.frames == 2


def test_detection_saver_writes_pictures_and_index(tmp_path):
    import numpy as np
    from debouncer import Debouncer
    from detection_frames import DetectionSaver, draw_boxes
    frame = np.zeros((120, 160, 3), np.uint8)
    d = Debouncer(gap_s=1.0)
    d.add(0.0, 17.4, 78.4, 40.0, "2026-10-11T10:00:00Z", conf=0.6,
          snapshot=draw_boxes(frame, [((10, 10, 60, 60), 0.6)]))
    d.add(0.1, 17.4, 78.4, 55.0, "2026-10-11T10:00:01Z", conf=0.7,
          snapshot=draw_boxes(frame, [((20, 20, 90, 90), 0.7)]))
    ev = d.flush()[0]
    assert ev.snapshot is not None and ev.snapshot[20, 20, 2] == 255   # worst frame kept, box drawn
    saver = DetectionSaver(tmp_path / "detections")
    p1 = saver.save(ev, 55.0, "logged")
    p2 = saver.save(ev, 55.0, "skipped", "likely a shadow")
    assert p1.exists() and p1.parent == tmp_path / "detections"
    assert p2.exists() and p2.parent.name == "skipped"
    rows = (tmp_path / "detections" / "index.csv").read_text().strip().splitlines()
    assert len(rows) == 3 and "likely a shadow" in rows[2]
