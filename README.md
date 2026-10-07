# EcoRoads

Offline-first civic road monitoring. Ordinary vehicles carry an **edge node** that detects potholes with YOLOv8, scores them, and logs them locally. A **cloud service** routes each pothole to the municipality responsible for that road. A **dashboard** shows each municipality its own hazards, and keeps a record of when each spot was repaired.

```
 phone on windscreen ─(hotspot)─► vehicle laptop                     server                        municipal office
┌──────────────────────────────┐   HTTP POST   ┌─────────────────────────┐   HTTP GET   ┌──────────────┐
│ camera → YOLOv8n → severity  │  (when online)│ ① inside a municipality?│◄────────────│  dashboard   │
│ debouncer (1 row / pothole)  │──────────────►│ ② on a public road? OSM │             │  Leaflet map │
│ + phone GPS                  │  5 fields     │ ③ store (SQLite)        │────────────►│  repairs     │
│ + phone/Arduino jolt         │  per pothole  │ ④ DBSCAN + confirmation │             └──────────────┘
│ → local SQLite (offline)     │               │ ⑤ repaired / reopened   │
└──────────────────────────────┘               └─────────────────────────┘
```

| Folder | Role | Docs |
|---|---|---|
| `ecoroads-edge/` | Detection, severity, GPS, accelerometer fusion, offline buffer, sync | [README](ecoroads-edge/README.md) |
| `ecoroads-cloud/` | FastAPI: geofencing, road filter, clustering, repairs, SQLite | [README](ecoroads-cloud/README.md) |
| `ecoroads-dashboard/` | Static HTML + Leaflet, no build step | [README](ecoroads-dashboard/README.md) |
| `ecoroads-edge/phone/` | Web page that turns the windscreen phone into camera + GPS + accelerometer | [PHONE_SETUP](PHONE_SETUP.md) |
| `demo/` | One-command classroom demo (replay a real drive, video, live phone, or simulation) | [DEMO_GUIDE](DEMO_GUIDE.md) |
| `tools/` | Fleet simulator, drive report (recall / GPS error), offline map assets | — |
| `TEST_DRIVE_CHECKLIST.md` | Step-by-step for the real drives | — |

## Quick start (Windows)

| Do this | To |
|---|---|
| `SETUP.bat` | install everything once (one venv for edge + cloud + demo) |
| `REAL_DRIVE.bat` | real-world drive: phone on the windscreen streams to the laptop ([PHONE_SETUP.md](PHONE_SETUP.md)) |
| `DEMO.bat` | classroom demo: replays your last drive with live map ([DEMO_GUIDE.md](DEMO_GUIDE.md)) |
| `DEMO.bat --simulate` | demo with no model or camera at all |
| `HOST.bat` + `DEMO.bat --remote-cloud …` | **three laptops:** 1 detector + 2 municipalities each seeing only their area ([MULTI_LAPTOP.md](MULTI_LAPTOP.md)) |
| `DETECTOR.bat` | real drive on the car laptop when the server runs on another laptop |
| [DEPLOY.md](DEPLOY.md) | **put the server + dashboards online for free** (Render + Neon) and publish the **EcoRoads-Edge.zip** download for vehicle laptops |

## 5-minute demo (no camera, GPU or car needed)

Windows PowerShell, from the `EcoRoads` folder:

```powershell
# 1. cloud
cd ecoroads-cloud
py -m venv venv; venv\Scripts\activate
pip install -r requirements.txt
cd app; uvicorn main:app --port 9000          # leave running

# 2. dashboard (new terminal)
cd ecoroads-dashboard; python -m http.server 8080   # open http://localhost:8080

# 3. simulated fleet (new terminal, any venv with `requests`)
python tools\simulate_fleet.py --repair-demo
```

Pick **Ward A** in the dashboard. You'll see clustered potholes confirmed by several vehicles, and one marked **REOPENED** because a bus detected it a week after it was "repaired".

## Running everything for real

1. `ecoroads-edge`: `python check_env.py`, then train the model (`training/train.py`, see the edge README).
2. Start the cloud and the dashboard as above, or run `docker compose up --build` for both.
3. On each vehicle laptop, copy `config.example.json` to `config.json` and set `vehicle_id`, `source: "phone"` and `cloud_url`. Then run `REAL_DRIVE.bat` (or `capture_detect.py --phone` + `sync_worker.py`).

## Tests

```
cd ecoroads-edge  && python -m pytest tests -q    # debouncer, fusion, phone bridge, clock sync, record/replay, report
cd ecoroads-cloud && python -m pytest tests -q    # gates, cache, breaker, clustering, repairs, API
```
