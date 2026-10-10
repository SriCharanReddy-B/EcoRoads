"""
Per-vehicle configuration for the edge node.

Defaults live here. To set up a specific vehicle, copy
config.example.json -> config.json (in the ecoroads-edge folder) and edit
only the keys you need. Each laptop/vehicle gets its own config.json, so
the code itself never changes between vehicles.
"""

import json
import os
from pathlib import Path

EDGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("ECOROADS_EDGE_CONFIG", EDGE_ROOT / "config.json"))

DEFAULTS = {
    # identity
    "vehicle_id": "car_01",

    # detection
    "model_path": str(EDGE_ROOT / "models" / "best.pt"),
    # video source:
    #   "phone"                         -> phone on the windscreen via the phone bridge (recommended)
    #   0, 1, ...                       -> webcam index (also DroidCam/Camo virtual webcams)
    #   "http://PHONE_IP:8080/video"    -> IP Webcam app or any MJPEG/RTSP camera URL
    #   "path/to/video.mp4"             -> recorded video (classroom demo)
    "source": 0,
    "confidence_threshold": 0.5,    # boxes below this are ignored (raised from 0.4: fewer shadows)
    "hazard_classes": ["pothole"],  # model classes that count as hazards (case-insensitive);
                                    # others (e.g. "Drain Hole", "Sewer Cover") are ignored
    "frame_skip": 1,                # run YOLO on every Nth frame (1 = all; phone sends ~15 fps)
    "show_window": True,

    # de-duplication of the same pothole across consecutive frames
    "event_gap_s": 1.5,             # pothole unseen for this long -> event closes and is logged once
    "event_max_span_m": 30.0,
    # false-positive filters (fusion.rejection_reason) against tree shadows, stains, patches
    "min_event_frames": 3,          # must be seen in at least this many frames
    "jolt_confirm_below_conf": 0.7, # while moving, a detection less sure than this needs a bump
                                    # on the accelerometer to count (0 = turn this rule off)
    "jolt_confirm_min_speed_mps": 3.0,       # a long continuous bad stretch is split into ~30 m records
                                    # (a single pothole stays in view ~10-15 m at 30 km/h)

    # phone bridge (source = "phone")
    "phone_port": 8443,
    "phone_width": 960,             # JPEG width the phone sends (YOLO runs at 640 anyway)
    "phone_jpeg_quality": 0.7,
    "phone_max_fps": 15,

    # GPS: "auto" | "simulated" | "phone" | "nmea_tcp" | "nmea_udp" | "nmea_serial"
    #   auto = phone GPS when source is "phone", the recorded GPS when replaying, else simulated
    "gps_mode": "auto",
    "gps_host": "192.168.43.1",
    "gps_port": 50000,
    "gps_serial_port": "COM4",
    "gps_baud": 9600,
    "gps_max_fix_age_s": 10,        # older fixes are treated as "no position"
    "max_gps_accuracy_m": 30,       # phone fixes worse than this are ignored

    # accelerometer: "auto" | "none" | "phone" | "arduino"
    #   auto = phone motion when source is "phone", Arduino if accel_serial_port is set
    "accel_mode": "auto",
    "accel_serial_port": None,      # e.g. "COM3"
    "accel_baud": 115200,
    "camera_lookahead_m": 6.0,      # distance from the bonnet to where the camera sees the pothole
    "jolt_min_g": 0.3,              # calibrate per mounting (see TEST_DRIVE_CHECKLIST.md)
    "jolt_max_g": 1.5,

    # recording of real drives (video + GPS + motion) into sessions/
    "record_session": "auto",       # auto = record live sources, not recorded videos

    # sync
    "cloud_url": "http://localhost:9000",
    "api_key": "",                  # must match ECOROADS_INGEST_KEY on the cloud, if set there
    "sync_interval_s": 15,
    "sync_batch_size": 25,
    "sync_timeout_s": 120,          # cloud does road checks per hazard, so allow time
}


def load_config(path=None):
    path = Path(path) if path else CONFIG_PATH
    cfg = dict(DEFAULTS)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            print(f"WARNING: unknown keys in {path.name} ignored: {sorted(unknown)}")
        cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    return cfg
