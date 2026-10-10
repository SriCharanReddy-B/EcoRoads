# EcoRoads — Edge Node

A standalone pothole detection unit that runs on a laptop in the vehicle. Detection and logging need **no network**. Only the sync worker uses the network, and only when it can reach the cloud.

## Pipeline

```
frame ─► YOLOv8n ─► strongest box ─► camera severity % (severity.py)
      ─► Debouncer: one event per pothole, keeps its worst frame (debouncer.py)
      ─► event closes ─► fuse with accelerometer jolt, if connected (fusion.py)
      ─► ONE row in local SQLite (storage.py) ─► sync_worker.py ─► cloud
```

Only `{vehicle_id, timestamp, lat, lon, severity_pct}` ever leaves the device.

## Setup (Windows)

Your current `venv` was created in a different folder (`Desktop\ecoroads-edge`) and later moved. Moved venvs often break, so if anything behaves strangely, recreate it:

```powershell
cd ecoroads-edge
py -m venv venv
venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
python check_env.py          # must show "PyTorch + CUDA ... RTX 4060"
```

Tip: the venv adds several GB under OneDrive. Pausing OneDrive sync, or keeping the venv outside OneDrive, avoids constant syncing.

## 1. Train the pothole model

Pick a pothole dataset on [Roboflow Universe](https://universe.roboflow.com) (search "pothole") and use its "YOLOv8" export. Either:

```powershell
pip install roboflow
$env:ROBOFLOW_API_KEY="your_key"
python training\train.py --roboflow WORKSPACE PROJECT VERSION
```
or download and unzip it yourself, then run:
```powershell
python training\train.py --data datasets\potholes\data.yaml
```

Training takes roughly 20–60 min on an RTX 4060, depending on dataset size. It copies the result to `models/best.pt` and prints precision, recall and mAP. Put those numbers in your report next to the base paper's figures. If you get CUDA out-of-memory, add `--batch 8`.

## 2. Configure this vehicle

Copy `config.example.json` to `config.json` and edit it. Every option and its default is in `src/config.py`. The important ones:

| key | meaning |
|---|---|
| `vehicle_id` | unique per vehicle, e.g. `car_02` |
| `source` | webcam index (`0`) or a video file path |
| `gps_mode` | `simulated`, `nmea_tcp`, `nmea_udp`, `nmea_serial` |
| `gps_host` / `gps_port` | phone's IP and port when using a phone as the GPS |
| `accel_serial_port` | e.g. `"COM3"` for the Arduino; `null` = camera only |
| `cloud_url` | e.g. `http://192.168.1.20:9000` |
| `api_key` | must match the cloud's `ECOROADS_INGEST_KEY`, if one is set |

## 3. Run (two terminals)

```powershell
cd src
python capture_detect.py --phone              # windscreen phone (see ../PHONE_SETUP.md) — records the drive
python capture_detect.py --replay latest      # re-run detection on the last recorded drive
python capture_detect.py --source road.mp4    # any video file, simulated GPS
python capture_detect.py --source 0           # laptop/USB webcam
python sync_worker.py                         # second terminal
```

Or just `REAL_DRIVE.bat` from the repo root, which starts all of them.

## Drive recording and replay

Every live drive is saved to `sessions/<date>_<vehicle>/`:

| File | Contents |
|---|---|
| `video.mp4` | the video |
| `frames.csv` | the time of every frame |
| `gps.csv` | GPS fixes |
| `motion.csv` | accelerometer samples |
| `meta.json` | vehicle, start time and settings |

`--replay` plays the drive back at true speed:

- **GPS** is interpolated to each frame's time.
- **Jolts** come from the recorded motion data.
- **Timestamps** are the original drive's.

So a replay behaves exactly like being in the car again. Use it to compare models or thresholds fairly, or for the classroom demo. Recordings never leave the laptop.

## Phone on the windscreen (recommended)

`source: "phone"` (or `--phone`) starts the **phone bridge** (`phone_bridge.py`):

- **Serving the page.** It's a small HTTPS server that serves `phone/phone.html` to the phone's browser.
- **What the phone sends:**
  - camera frames as JPEG, at ~15 fps
  - GPS fixes
  - accelerometer samples at 60 Hz
- **Back-pressure.** The phone sends a new frame only after the laptop has answered the previous one, so a slow link lowers the frame rate instead of piling up stale video.
- **One clock.** `timesync.py` maps the phone's timestamps onto the laptop's clock, so camera, GPS and jolts line up.
- **Defaults when `source` is `"phone"`:** GPS and the accelerometer default to the phone too (`gps_mode`/`accel_mode` = `auto`).

Full step-by-step instructions are in [`../PHONE_SETUP.md`](../PHONE_SETUP.md).

## Real GPS from a separate NMEA source (alternative)

1. Install an Android app that shares GPS as NMEA over TCP. Search the Play Store for "NMEA TCP server" or "Share GPS".
2. Turn on the phone's hotspot and connect the laptop to it. No mobile data is needed; it's only a local link.
3. In the app, start a TCP server on port 50000.
4. In `config.json`, set `"gps_mode": "nmea_tcp"`, `"gps_host": "<phone IP>"` and `"gps_port": 50000`. Android hotspots usually use `192.168.43.1`; check the app or `ipconfig`.

When there's no GPS fix, detections are skipped and counted on screen, because a pothole without a location can't be routed to a municipality.

## Accelerometer (Arduino + MPU6050)

1. Wiring: VCC→5V, GND→GND, SDA→A4, SCL→A5. Flash `arduino/ecoroads_accel/ecoroads_accel.ino` with the Arduino IDE.
2. Mount the board **rigidly** to the car body.
3. Check it works: `python src\accel_reader.py COM3`, then tap the board and watch the peak jolt.
4. Set `"accel_serial_port": "COM3"` in `config.json`.

How the two streams are matched (worth explaining in interviews):
- **One clock:** each accelerometer sample is stamped with the laptop's clock when it arrives, so the camera and accelerometer share a timeline.
- **Lookahead delay:** the camera sees a pothole about `camera_lookahead_m` ahead, so the wheel hits it about `lookahead / speed` seconds later. `fusion.py` looks for a jolt in that window.
- **Severity rule:** if a jolt is found, final severity = 60% camera + 40% jolt. If no jolt is found, the camera value is kept, since the driver may simply have steered around the pothole.
- **Failures don't stop detection:** if the sensor is unplugged, the node logs a warning and carries on with camera-only severity.

## Tree shadows and other false positives

Shadows, wet patches and dark repairs can look like potholes. Three layers deal with them:

1. **Settings** in `config.json` (defaults shown; checked in `fusion.rejection_reason`):
   - `"confidence_threshold": 0.5`: boxes the model is less sure about are ignored.
   - `"min_event_frames": 3`: something seen in only 1–2 frames is flicker, not a pothole.
   - `"jolt_confirm_below_conf": 0.7`: while the car is moving and the phone's motion
     sensor is working, a detection less sure than 0.7 is kept only if the wheel felt a
     bump. Shadows are flat, so they are dropped. Set to `0` to turn this rule off.
   Dropped detections print `[skipped] …` and are counted in the preview window.
2. **Cloud threshold:** a repair ticket is raised only after 3 detections of the same spot.
3. **Retrain against shadows** (the real fix): double-click `RETRAIN_SHADOWS.bat`. It
   - collects frames where the model fired on your recorded drives (`hard_negatives.py collect --session all`);
   - lets you delete the ones that are real potholes, then adds the rest as **background
     images** (empty label files) to train and validation (`hard_negatives.py add`);
   - adds shadowed copies of ~15% of the training images with the same labels
     (`shadow_augment.py`; `--preview out.jpg` shows an example, `--undo` removes them);
   - fine-tunes `models/best.pt` for 30 epochs into `runs/pothole_shadows/` and installs it,
     keeping the old model as `models/best_previous.pt`.

## Tests (no hardware needed)

```powershell
python -m pytest tests -q
```

## Files

- `src/capture_detect.py`: the main loop and mode selection (`--phone`, `--replay`, `--source`)
- `src/phone_bridge.py`, `src/certs.py`, `src/timesync.py`, `phone/phone.html`: the phone sensor link
- `src/video_source.py`: webcam, camera URL and real-time video file sources
- `src/session.py`: drive recording and replay
- `src/debouncer.py`: turns per-frame detections into one record per pothole
- `src/severity.py`: confidence + box size → 0–100%
- `src/fusion.py`: combines camera severity with the accelerometer jolt
- `src/gps.py`, `src/gps_simulator.py`, `src/gps_nmea.py`: GPS sources
- `src/accel_reader.py`, `arduino/`: accelerometer reader and Arduino firmware
- `src/storage.py`: offline SQLite buffer (WAL mode, so two processes can use it safely)
- `src/sync_worker.py`: the only part that uses the network; retries are safe
- `training/train.py`, `check_env.py`: model training and environment check
