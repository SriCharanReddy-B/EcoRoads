# EcoRoads — Cloud Service

Receives pothole events from every vehicle and routes each one to the municipality responsible for that road.

## What happens to each incoming hazard

1. **Geofence:** is it inside a registered municipality's circle? If several circles contain it, the nearest centre wins. If none do, it's rejected.
2. **Road check:** is it on a public road, according to OpenStreetMap via Overpass?
   - Private, unpaved or footpath-only locations are rejected.
   - If Overpass is unreachable, the hazard is accepted anyway (fail-open) and flagged `road_status = unverified`.
   - Results are cached in SQLite per ~11 m cell.
   - A circuit breaker stops calling Overpass for 60 s after a failure, so an outage can't stall a sync.
3. **Store:** saved in SQLite. A `UNIQUE(vehicle_id, timestamp, lat, lon)` constraint means an edge node that re-sends a batch can't create duplicates.

When a municipality's hazards are requested:

4. **Cluster:** DBSCAN with the haversine metric (ε = 15 m) merges detections of the same pothole. The cluster's severity is the average, plus 3 points per extra confirming vehicle (at most +10).
5. **Office (Haversine):** each municipality has exactly one office (`offices.py`; the circle centre until staff set it). Each pothole cluster shows its great-circle distance to that office.
6. **Automatic repair tickets (Gemini):** after every accepted sync batch, `service.auto_tickets` raises a ticket for each pothole that has reached `ECOROADS_TICKET_MIN_DETECTIONS` detections (default 3) and has no ticket yet. It runs as a background task, so the vehicle doesn't wait. `ticketing.py` sends only system-computed facts (location, severity, detections, vehicles, office and distance, failed-repair note) to Gemini; without a key, or on any error, a deterministic template is used. A reopened pothole gets a new ticket after the threshold is reached again.
7. **Repairs:** when a municipality marks a spot repaired, earlier detections there are retired. If vehicles detect the pothole there again after the repair date, it comes back as **reopened**. That gives objective evidence that a contractor's repair failed or never happened.

## Setup and run (Windows)

```powershell
cd ecoroads-cloud
py -m venv venv; venv\Scripts\activate
pip install -r requirements.txt
cd app; uvicorn main:app --host 0.0.0.0 --port 9000      # or just: run.bat
```

- Interactive API docs: http://localhost:9000/docs
- Data is kept in `data/ecoroads.db`. To use a different file, set `ECOROADS_DB`.
- Optional: set `ECOROADS_INGEST_KEY=some-secret` so only edge nodes that know the key can post hazards.
- Use `--host 0.0.0.0` so vehicle laptops on the same Wi-Fi or hotspot can reach this machine.

Docker alternative (cloud + dashboard together): run `docker compose up --build` from the repo root.

## Deploying online

See [`../DEPLOY.md`](../DEPLOY.md): Render (free) + Neon PostgreSQL. With `DATABASE_URL` set, `db.py` uses PostgreSQL instead of SQLite, with the same queries. The API also serves the dashboard at `/`. `ECOROADS_ADMIN_KEY` turns on public-deployment security:
- registering a municipality needs the admin key
- each municipality gets its own access token for marking repairs
- vehicles still need `ECOROADS_INGEST_KEY` to upload

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/municipalities` | register or update a circle `{municipality_id, name, center_lat, center_lon, radius_m}` |
| GET | `/api/municipalities` | list municipalities |
| POST | `/api/ingest` | `{hazards: [{vehicle_id, timestamp, lat, lon, severity_pct}]}` |
| GET | `/api/municipalities/{id}/hazards` | `{hazards: [open + reopened], repaired: [...]}` |
| POST | `/api/municipalities/{id}/repairs` | `{lat, lon, note?, repaired_at?}` |
| GET | `/api/health` | liveness check (the edge sync worker probes this) |
| GET | `/api/config` | `{secure, edge_download_url, ticket_generator, ticket_min_detections}` for the dashboard |
| GET/POST | `/api/municipalities/{id}/office` | the municipality's one office `{name, lat, lon, contact?}` (POST sets/moves it) |
| GET | `/api/municipalities/{id}/tickets` | tickets received, newest first (raised automatically) |
| POST | `/api/municipalities/{id}/tickets` | staff: `{lat, lon}` regenerates the ticket of a pothole that reached the threshold (409 if not yet) |

## Tests

```powershell
python -m pytest tests -q
```
These cover the geofence, the private-road rejection, `service` roads, idempotent re-sends, the road cache, the Overpass circuit breaker, metre-based clustering, the confirmation boost, the repaired/reopened flow, input validation and the API key. Overpass is faked, so the tests don't need internet.

## Files

- `app/main.py`: HTTP layer only (validation and status codes)
- `app/service.py`: business rules (ingest gates, queries, repairs)
- `app/db.py`: SQLite schema and connections; the only file to change for PostgreSQL
- `app/municipality_registry.py`: circles and haversine lookup
- `app/road_registry.py`: OpenStreetMap road classification, cache and circuit breaker
- `app/clustering.py`: DBSCAN, severity aggregation and repair logic

## Known limitations

- Municipalities are circles, not polygons. To support real ward shapes, change `locate_municipality()`.
- There are no user accounts on the dashboard: anyone who can open it can register a municipality or mark a repair. Add authentication before any public deployment.
