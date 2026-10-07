# EcoRoads: project guide for Claude

Offline-first civic road-monitoring platform. Vehicles carry an edge node that detects potholes, scores their severity, and logs them locally. A cloud service routes each hazard to the municipality responsible for that road, and a dashboard shows each municipality its own hazards.

## Repo layout (3 independent projects that talk over HTTP)

| Folder | What it is | Run |
|---|---|---|
| `ecoroads-edge/` | Phone/webcam/video → YOLOv8-nano → severity → debouncer → (+ phone or MPU6050 jolt fusion, phone/NMEA GPS) → local SQLite → sync worker; settings in `config.json` | `cd src && python capture_detect.py --phone` + `python sync_worker.py` |
| `ecoroads-cloud/` | FastAPI + SQLite: municipality circles, OSM road filter (cached, fail-open), haversine DBSCAN, repairs/reopened | `cd app && uvicorn main:app --port 9000` |
| `ecoroads-dashboard/` | Single static `index.html`, Leaflet + OSM tiles, vanilla JS | `python -m http.server 8080` (`?api=` overrides the cloud URL) |
| `ecoroads-edge/phone/` + `src/phone_bridge.py` | Windscreen phone → laptop over HTTPS (camera JPEG POSTs, GPS, 60 Hz motion), clock-synced | `capture_detect.py --phone` / `REAL_DRIVE.bat` |
| `demo/run_demo.py` | One-command classroom demo (replay drive / video / live phone / simulate, `--cloud-delay`) | `DEMO.bat` |
| `demo/host_cloud.py` + `demo/zones.py` | Multi-laptop host: cloud + dashboard on the LAN, optional `--zones N` split of a recorded route, prints detector URL + per-municipality locked dashboard links (`&lock=1`) | `HOST.bat` (detector: `DEMO.bat --remote-cloud URL` or `DETECTOR.bat`) |
| `tools/` | `simulate_fleet.py`, `drive_report.py` (recall, GPS error), `fetch_offline_assets.py` | |

## Non-negotiable design decisions (don't undo these without asking)

- **Offline-first edge:** detection and storage never depend on the network. Only `sync_worker.py` touches the network.
- **Minimal payload:** only `{vehicle_id, timestamp, lat, lon, severity_pct}` leaves the device. No images, raw confidences or bounding boxes.
- **Severity is computed on the edge** (`severity.py`: 0.55·conf + 0.45·size, capped).
- **Municipalities self-register circles** through the dashboard. Boundaries are not hardcoded.
- **Road filter is fail-open:** if Overpass is down, accept the hazard.
- **Single-stack Python MVP first.** The polyglot split (Spring Boot / MERN) is a later phase (Week 3).
- **Leaflet, not Mapbox:** no API keys.

## Environment

- Windows laptop with an RTX 4060. The edge venv uses Python 3.14 with `torch 2.11.0+cu128`.
- The project lives in OneDrive. Keep `venv/`, `data/*.db`, `runs/` and `*.pt` out of git, and preferably out of OneDrive sync.

## Status (Oct 2026)

- All software for Weeks 1–3 is built and tested:
  - edge: debouncer, NMEA GPS, MPU6050 fusion, training script
  - cloud: SQLite, haversine DBSCAN, road cache and circuit breaker, repairs/reopened, API key
  - dashboard: repairs and status tags
  - fleet simulator and Docker Compose
- Phone-on-windscreen pipeline built and tested (headless Chromium with fake camera/GPS/motion against the bridge). Every live drive is recorded to `ecoroads-edge/sessions/` and can be replayed (`--replay`) with GPS and jolts.
- Classroom demo: `DEMO.bat` (see `DEMO_GUIDE.md`). Real drive: `REAL_DRIVE.bat` (see `PHONE_SETUP.md`).
- Deployment: `render.yaml` (Render free web service, Docker, region singapore) + Neon Postgres via `DATABASE_URL` (db.py supports SQLite and Postgres with shared "?"/ON CONFLICT SQL; cloud tests pass on both). Cloud serves the dashboard at `/`. Secure mode via `ECOROADS_ADMIN_KEY` (admin registers wards; per-ward tokens, sha256-hashed, for repairs; links carry `#token=`), `ECOROADS_INGEST_KEY` for vehicles. Guide: `DEPLOY.md` (click-by-click); verify with `tools/deploy_check.py URL --api-key KEY` (read-only). Render health check uses DB-free `/api/ping`.
- Edge download: `tools/build_edge_package.py --cloud-url URL` -> `ecoroads-dashboard/downloads/EcoRoads-Edge.zip` (INSTALL.bat with GPU auto-detect + `setup_config.py`, START_DRIVE.bat). Dashboard shows "⬇ Edge node" when the zip exists.
- Three-laptop setup (1 detector + 2 municipal laptops, each locked to its own area) built and tested: see `MULTI_LAPTOP.md`.
- Remaining tasks need the hardware: train `models/best.pt` on the RTX 4060, first phone drive, calibrate `jolt_min_g`/`jolt_max_g`, Drive 1 and Drive 2 (`TEST_DRIVE_CHECKLIST.md`).
- Optional Phase 2: polyglot split (Spring Boot / MERN). `service.py` holds the business rules to port.
- Tests: `python -m pytest tests -q` in `ecoroads-edge` and `ecoroads-cloud`.

## Working style

The developer is a fresher who wants to **understand** every change well enough to explain it in an interview. Explain the *why* briefly with each change, keep code simple, and avoid unnecessary abstractions.
