"""
EDGE NODE — Main pipeline.

Fully self-contained: runs YOLO inference locally, computes severity
locally, stores locally. Requires ZERO internet — sync_worker.py
(separate process) is the only thing that ever talks to the cloud.

Per frame:
  frame (+ capture time t) -> YOLO -> strongest pothole box -> camera severity
  -> Debouncer (one record per pothole, not per frame)
  -> when the pothole event closes: fuse with the jolt (phone or Arduino
     accelerometer) -> log ONE row to local SQLite

Modes (from ecoroads-edge/src):
    python capture_detect.py --phone                  real drive: phone on the windscreen
    python capture_detect.py --replay latest          replay the last recorded drive
    python capture_detect.py --replay ..\\sessions\\X   replay a specific drive
    python capture_detect.py --source road.mp4        any video file, simulated GPS
    python capture_detect.py --source 0               laptop/USB webcam
    python capture_detect.py --source http://PHONE_IP:8080/video   IP Webcam app
Quit with 'q' in the preview window, or Ctrl+C.
"""

import argparse
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from config import load_config
from debouncer import Debouncer
from fusion import fuse
from severity import compute_severity_pct
from storage import get_connection, log_hazard, unsynced_count


def bbox_area_pct(box, frame_shape):
    x1, y1, x2, y2 = box
    box_area = max(0, x2 - x1) * max(0, y2 - y1)
    frame_area = frame_shape[0] * frame_shape[1]
    return round(100 * box_area / frame_area, 3)


def parse_args(cfg):
    p = argparse.ArgumentParser(description="EcoRoads edge node")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--phone", action="store_true", help="use the windscreen phone (camera+GPS+motion)")
    g.add_argument("--replay", metavar="SESSION", help="replay a recorded drive ('latest' or a folder)")
    g.add_argument("--source", help="webcam index, video file, or camera URL")
    p.add_argument("--vehicle-id")
    p.add_argument("--model")
    p.add_argument("--no-window", action="store_true", help="don't open a preview window")
    p.add_argument("--record", dest="record", action="store_true", default=None)
    p.add_argument("--no-record", dest="record", action="store_false")
    p.add_argument("--fast", action="store_true", help="replay/file: process as fast as possible")
    a = p.parse_args()
    if a.phone:
        cfg["source"] = "phone"
    if a.source is not None:
        cfg["source"] = int(a.source) if a.source.isdigit() else a.source
    if a.vehicle_id:
        cfg["vehicle_id"] = a.vehicle_id
    if a.model:
        cfg["model_path"] = a.model
    if a.no_window:
        cfg["show_window"] = False
    if a.record is not None:
        cfg["record_session"] = a.record
    return cfg, a


# ------------------------------------------------------------------ wiring
class Rig:
    """Everything the loop needs, chosen from config: video, GPS, accelerometer, recorder."""

    def __init__(self, cfg, replay=None, fast=False):
        self.cfg = cfg
        self.bridge = self.recorder = None
        self.wall_time = lambda t: datetime.now(timezone.utc).isoformat()
        src = cfg["source"]

        if replay:
            from session import ReplayAccel, ReplayGPS, ReplaySource, latest_session, recorded_wall_time
            sdir = latest_session() if replay == "latest" else Path(replay)
            if sdir is None or not (Path(sdir) / "video.mp4").exists():
                raise SystemExit(f"No recorded drive found at {replay!r} (looked for video.mp4).")
            print(f"Replaying drive {sdir}")
            self.video = ReplaySource(sdir, realtime=not fast)
            self.gps = ReplayGPS(sdir, clock=self.video.media_time)
            accel = ReplayAccel(sdir)
            self.accel = accel if accel.has_data() and cfg["accel_mode"] != "none" else None
            self.wall_time = recorded_wall_time(sdir) or self.wall_time
            self.mode = "replay"
            return

        if src == "phone":
            from phone_bridge import PhoneAccel, PhoneBridge, PhoneFrameSource, PhoneGPS
            self.bridge = PhoneBridge(
                port=cfg["phone_port"],
                max_gps_accuracy_m=cfg["max_gps_accuracy_m"],
                max_fix_age_s=cfg["gps_max_fix_age_s"],
                phone_settings={"width": cfg["phone_width"], "jpeg_quality": cfg["phone_jpeg_quality"],
                                "max_fps": cfg["phone_max_fps"], "vehicle_id": cfg["vehicle_id"]},
            ).start()
            print("\n  On the phone (same hotspot/Wi-Fi), open in Chrome/Safari:")
            for u in self.bridge.urls():
                print(f"     {u}")
            print("  First time: tap 'Advanced' -> 'Proceed' on the certificate warning,")
            print("  then 'Start streaming' and allow camera + location + motion.\n")
            self.video = PhoneFrameSource(self.bridge, timeout_s=3600)   # wait for the phone
            self.mode = "phone"
        else:
            from video_source import FileSource, open_source
            self.video = open_source(src) if not isinstance(src, str) or "://" in src or src.isdigit() \
                else FileSource(src, realtime=not fast)
            if not self.video.isOpened():
                raise SystemExit(f"Could not open video source {src!r}.")
            self.mode = "live" if self.video.is_live else "file"

        self.gps = self._make_gps()
        self.accel = self._make_accel()

        record = cfg["record_session"]
        if record == "auto":
            record = self.mode in ("phone", "live")
        if record:
            from session import SessionRecorder
            self.recorder = SessionRecorder(cfg["vehicle_id"], settings={
                k: cfg[k] for k in ("source", "camera_lookahead_m", "confidence_threshold")})
            if self.bridge:
                self.bridge.listeners.append(self.recorder.on_bridge_event)
            print(f"Recording this drive to {self.recorder.dir}")

    def _make_gps(self):
        mode = self.cfg["gps_mode"]
        if mode == "auto":
            mode = "phone" if self.mode == "phone" else "simulated"
        if mode == "phone":
            if not self.bridge:
                raise SystemExit("gps_mode 'phone' needs source 'phone'")
            from phone_bridge import PhoneGPS
            return PhoneGPS(self.bridge)
        from gps import make_gps
        return make_gps({**self.cfg, "gps_mode": mode})

    def _make_accel(self):
        mode = self.cfg["accel_mode"]
        if mode == "auto":
            mode = "phone" if self.mode == "phone" else ("arduino" if self.cfg["accel_serial_port"] else "none")
        if mode == "phone":
            from phone_bridge import PhoneAccel
            return PhoneAccel(self.bridge)
        if mode == "arduino":
            try:
                from accel_reader import AccelReader
                return AccelReader(self.cfg["accel_serial_port"], self.cfg["accel_baud"])
            except Exception as e:  # offline-first: a missing sensor never stops detection
                print(f"[accel] Arduino not available ({e}) — camera-only severity")
        return None

    def close(self):
        self.video.release()
        self.gps.close()
        if self.accel:
            self.accel.close()
        if self.recorder:
            print(f"Drive recorded: {self.recorder.close()}")
        if self.bridge:
            self.bridge.stop()


# ------------------------------------------------------------------ main loop
def _stop_on_sigterm(*_):
    raise KeyboardInterrupt   # lets the demo launcher stop us cleanly (recording saved)


def main():
    signal.signal(signal.SIGTERM, _stop_on_sigterm)
    cfg, args = parse_args(load_config())
    from ultralytics import YOLO

    rig = Rig(cfg, replay=args.replay, fast=args.fast)
    print(f"Vehicle {cfg['vehicle_id']} | mode {rig.mode} | model {cfg['model_path']} | "
          f"accel {'on' if rig.accel else 'off'}")
    model = YOLO(cfg["model_path"])
    conn = get_connection()
    debouncer = Debouncer(cfg["event_gap_s"], cfg["event_max_span_m"])
    hazard_classes = {c.lower() for c in cfg["hazard_classes"]}

    frame_count = logged_count = no_fix_count = 0
    fps_t, fps_n, fps = time.monotonic(), 0, 0.0

    def save(events):
        nonlocal logged_count
        for ev in events:
            severity, jolt = fuse(ev, rig.accel, cfg["camera_lookahead_m"], cfg["event_gap_s"],
                                  cfg["jolt_min_g"], cfg["jolt_max_g"])
            log_hazard(conn, cfg["vehicle_id"], ev.lat, ev.lon, severity, ev.wall_time_iso)
            logged_count += 1
            jolt_txt = f", jolt {jolt:.2f} g" if jolt is not None else ""
            print(f"[logged] pothole {severity}% (camera {ev.severity_pct}%{jolt_txt}, "
                  f"{ev.frames} frames) at {ev.lat:.6f},{ev.lon:.6f}")

    if rig.mode == "phone":
        print("Waiting for the phone to start streaming…")
    print("Edge node running — fully offline capable. Press 'q' or Ctrl+C to quit.\n")
    try:
        while True:
            ok, frame, t = rig.video.read()
            if not ok:
                print("End of video." if rig.mode in ("file", "replay") else "Video source stopped.")
                break

            frame_count += 1
            fps_n += 1
            if time.monotonic() - fps_t >= 1.0:
                fps, fps_t, fps_n = fps_n / (time.monotonic() - fps_t), time.monotonic(), 0

            pos = rig.gps.get_current_position()
            if rig.recorder:
                rig.recorder.frame(frame, t)
                if pos and not rig.bridge:          # phone GPS is recorded by the bridge listener
                    rig.recorder.gps(t, pos[0], pos[1], rig.gps.get_speed_mps())

            save(debouncer.tick(t))

            if frame_count % cfg["frame_skip"] == 0:
                result = model.predict(frame, conf=cfg["confidence_threshold"], verbose=False)[0]
                best = None  # strongest box in this frame
                names = getattr(result, "names", None) or {}
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    cls_name = str(names.get(int(box.cls[0]), "")) if names and hasattr(box, "cls") else ""
                    # Multi-class models (e.g. Pothole / Drain Hole / Sewer Cover): only the
                    # hazard classes are logged; manholes etc. are shown in grey and ignored.
                    is_hazard = not cls_name or cls_name.lower() in hazard_classes
                    if not is_hazard:
                        if cfg["show_window"]:
                            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (160, 160, 160), 1)
                            cv2.putText(frame, cls_name, (int(x1), int(y1) - 6),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 160, 160), 1)
                        continue
                    sev = compute_severity_pct(float(box.conf[0]),
                                               bbox_area_pct((x1, y1, x2, y2), frame.shape))
                    if best is None or sev > best:
                        best = sev
                    if cfg["show_window"]:
                        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
                        cv2.putText(frame, f"{sev}%", (int(x1), int(y1) - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

                if best is not None:
                    if pos is None:
                        no_fix_count += 1   # a hazard without a location can't be routed
                    else:
                        save(debouncer.add(t, pos[0], pos[1], best, rig.wall_time(t),
                                           rig.gps.get_speed_mps()))

            pending = unsynced_count(conn)
            if rig.bridge:
                rig.bridge.status_text = f"{logged_count} potholes logged, {pending} waiting to sync"

            if cfg["show_window"]:
                gps_txt = f"GPS {pos[0]:.5f},{pos[1]:.5f}" if pos else "GPS: no fix"
                lines = [f"{rig.mode} | {fps:.0f} fps | {gps_txt}",
                         f"logged: {logged_count}  pending sync: {pending}"
                         + (f"  no-GPS skips: {no_fix_count}" if no_fix_count else "")]
                if rig.recorder:
                    lines.append("REC")
                for i, line in enumerate(lines):
                    color = (0, 0, 255) if line == "REC" else (0, 255, 0)
                    cv2.putText(frame, line, (10, 25 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                cv2.imshow("EcoRoads Edge Node (q to quit)", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        save(debouncer.flush())   # never drop the pothole we were in the middle of
        rig.close()
        cv2.destroyAllWindows()
        conn.close()
        print(f"\nDone. {logged_count} potholes logged locally"
              f"{f', {no_fix_count} detections skipped (no GPS fix)' if no_fix_count else ''}.")


if __name__ == "__main__":
    main()
