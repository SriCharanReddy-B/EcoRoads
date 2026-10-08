"""
Hardware-free demo / load test: simulates several vehicles driving
through 2-3 municipality zones and syncing pothole events to the cloud,
exactly as real edge nodes would (same /api/ingest payload).

Use it to:
  - demo the whole system without a car, webcam or trained model
  - test the cloud + dashboard before a real multi-vehicle drive
  - show the "repaired -> reopened" contractor-accountability flow

Run (cloud must be running):
    python tools/simulate_fleet.py
    python tools/simulate_fleet.py --cloud http://localhost:9000 --vehicles 3 --passes 4
    python tools/simulate_fleet.py --repair-demo

Only needs `requests`.
"""

import argparse
import random
from datetime import datetime, timedelta, timezone

import requests

# Three ~300 m test zones around Hyderabad (matching the edge GPS simulator's area).
# Change these to your real test zones before a live drive.
ZONES = [
    {"municipality_id": "ward_a", "name": "Ward A Municipality", "center_lat": 17.4075, "center_lon": 78.4775, "radius_m": 300},
    {"municipality_id": "ward_b", "name": "Ward B Municipality", "center_lat": 17.4130, "center_lon": 78.4830, "radius_m": 250},
    {"municipality_id": "ward_c", "name": "Ward C Municipality", "center_lat": 17.4020, "center_lon": 78.4720, "radius_m": 250},
]

# "Real" potholes: (lat, lon, true severity %)
POTHOLES = [
    (17.40690, 78.47720, 82), (17.40765, 78.47790, 64), (17.40840, 78.47850, 38),
    (17.41290, 78.48280, 71), (17.41350, 78.48340, 22),
    (17.40180, 78.47180, 55), (17.40250, 78.47260, 90),
]

GPS_NOISE_DEG = 0.00004      # ~4 m of GPS error
DETECTION_RATE = 0.8         # a vehicle doesn't catch every pothole on every pass


HEADERS = {}   # filled from --admin-key / --api-key for a secured (deployed) server


def post(cloud, path, body):
    r = requests.post(f"{cloud}{path}", json=body, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json()


def register_zones(cloud):
    """Registers the wards and sets each ward's one municipal office (just north of
    the centre), so tickets have an addressee and a Haversine distance."""
    for z in ZONES:
        token = post(cloud, "/api/municipalities", z).get("access_token")
        hdr = {"X-Muni-Token": token} if token else {}
        office = requests.get(f"{cloud}/api/municipalities/{z['municipality_id']}/office",
                              timeout=60).json().get("office", {})
        if office.get("is_default", True):
            requests.post(f"{cloud}/api/municipalities/{z['municipality_id']}/office",
                          json={"name": f"{z['name'].split(' Municipality')[0]} Municipal Office",
                                "lat": z["center_lat"] + 0.0015, "lon": z["center_lon"]},
                          headers={**HEADERS, **hdr}, timeout=60).raise_for_status()
        print(f"registered {z['name']} (office ready)  private link token: {token}")


def drive(cloud, vehicles, passes, start, rng):
    events = []
    for p in range(passes):
        for v in range(1, vehicles + 1):
            t = start + timedelta(hours=p * 6 + v)
            for i, (lat, lon, sev) in enumerate(POTHOLES):
                if rng.random() > DETECTION_RATE:
                    continue
                events.append({
                    "vehicle_id": f"car_{v:02d}",
                    "timestamp": (t + timedelta(seconds=20 * i)).isoformat(),
                    "lat": round(lat + rng.gauss(0, GPS_NOISE_DEG), 7),
                    "lon": round(lon + rng.gauss(0, GPS_NOISE_DEG), 7),
                    "severity_pct": round(max(0, min(100, sev + rng.gauss(0, 6))), 1),
                })
    # one detection outside every zone (should be rejected)
    events.append({"vehicle_id": "car_01", "timestamp": start.isoformat(),
                   "lat": 17.45, "lon": 78.55, "severity_pct": 50.0})

    totals = {}
    for i in range(0, len(events), 25):          # same batch size as the edge sync worker
        res = post(cloud, "/api/ingest", {"hazards": events[i:i + 25]})
        for k, v in res.items():
            if isinstance(v, int) and k != "total_stored":
                totals[k] = totals.get(k, 0) + v
    print(f"sent {len(events)} events from {vehicles} vehicles x {passes} passes -> {totals}")


def repair_demo(cloud, start, rng):
    lat, lon, _ = POTHOLES[1]
    repaired_at = start + timedelta(days=3)
    post(cloud, "/api/municipalities/ward_a/repairs",
         {"lat": lat, "lon": lon, "note": "Contractor XYZ, work order 1042",
          "repaired_at": repaired_at.isoformat()})
    print(f"marked pothole at {lat},{lon} repaired on {repaired_at.date()}")
    # a week later, a bus still hits it
    post(cloud, "/api/ingest", {"hazards": [{
        "vehicle_id": "bus_07", "timestamp": (repaired_at + timedelta(days=7)).isoformat(),
        "lat": lat + 0.00002, "lon": lon, "severity_pct": 66.0}]})
    print("bus_07 detected it again 7 days after the 'repair' -> shows as REOPENED")


def summary(cloud):
    for z in ZONES:
        r = requests.get(f"{cloud}/api/municipalities/{z['municipality_id']}/hazards", timeout=30).json()
        print(f"\n{z['name']}: {r['count']} open hazard(s), {len(r['repaired'])} repaired")
        for h in r["hazards"]:
            flag = "  [REOPENED]" if h["status"] == "reopened" else ""
            ticket = "ticket raised" if h.get("ticket") else \
                f"no ticket yet ({h['detection_count']}/{h.get('detections_needed', '?')})"
            print(f"  #{h['cluster_id']:<2} {h['severity_tier']:<8} {h['severity_pct']:5.1f}%  "
                  f"{h['detection_count']} detections, vehicles {','.join(h['confirmed_by_vehicles'])}"
                  f"  -> {ticket}{flag}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cloud", default="http://localhost:9000")
    p.add_argument("--vehicles", type=int, default=3)
    p.add_argument("--passes", type=int, default=3)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--repair-demo", action="store_true")
    p.add_argument("--admin-key", help="deployed server: ECOROADS_ADMIN_KEY (to register wards)")
    p.add_argument("--api-key", help="deployed server: ECOROADS_INGEST_KEY (to upload)")
    a = p.parse_args()
    if a.admin_key:
        HEADERS["X-Admin-Key"] = a.admin_key     # also authorises the repair in --repair-demo
    if a.api_key:
        HEADERS["X-API-Key"] = a.api_key

    rng = random.Random(a.seed)
    start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=14)
    register_zones(a.cloud)
    drive(a.cloud, a.vehicles, a.passes, start, rng)
    if a.repair_demo:
        repair_demo(a.cloud, start, rng)
    summary(a.cloud)
    print("\nOpen the dashboard and pick a ward to see this on the map.")


if __name__ == "__main__":
    main()
