"""
Scores a real test drive against ground truth — the numbers for your report.

Before the drive, walk/scout the route and note each real pothole in a
CSV (Google Maps: long-press -> copy coordinates):

    name,lat,lon,size
    P1 near bus stop,17.40690,78.47720,L
    P2 school gate,17.40765,78.47790,M

After the drive:

    python tools\\drive_report.py --ground-truth my_route.csv
    python tools\\drive_report.py --ground-truth my_route.csv --db ecoroads-edge\\data\\local_hazards.db --since 2026-10-12

Prints (and saves as drive_report.md next to the CSV):
  - per pothole: detected?, severity, how far the logged GPS point was from the real one
  - recall (share of real potholes detected)
  - logged points that match no real pothole (false positives, or potholes you didn't scout)
"""

import argparse
import csv
import math
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "ecoroads-edge" / "data" / "local_hazards.db"
MATCH_RADIUS_M = 25.0   # phone GPS error is typically 5-15 m


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def load_detections(db, since=None, vehicle=None):
    conn = sqlite3.connect(db)
    q, params = "SELECT vehicle_id, timestamp, lat, lon, severity_pct FROM hazards WHERE 1=1", []
    if since:
        q += " AND timestamp >= ?"
        params.append(since)
    if vehicle:
        q += " AND vehicle_id = ?"
        params.append(vehicle)
    rows = [dict(zip(("vehicle_id", "timestamp", "lat", "lon", "severity_pct"), r))
            for r in conn.execute(q, params)]
    conn.close()
    return rows


def score(truth, detections, radius=MATCH_RADIUS_M):
    used = set()
    results = []
    for gt in truth:
        near = [(haversine_m(gt["lat"], gt["lon"], d["lat"], d["lon"]), i)
                for i, d in enumerate(detections)]
        near = [(dist, i) for dist, i in near if dist <= radius]
        used.update(i for _, i in near)
        if near:
            dist, i = min(near)
            sev = max(detections[j]["severity_pct"] for _, j in near)
            results.append({**gt, "detected": True, "hits": len(near),
                            "severity_pct": sev, "gps_error_m": round(dist, 1)})
        else:
            results.append({**gt, "detected": False, "hits": 0, "severity_pct": None, "gps_error_m": None})
    unmatched = [d for i, d in enumerate(detections) if i not in used]
    found = sum(r["detected"] for r in results)
    errors = [r["gps_error_m"] for r in results if r["detected"]]
    summary = {
        "real_potholes": len(truth),
        "detected": found,
        "recall_pct": round(100 * found / len(truth), 1) if truth else 0.0,
        "unmatched_detections": len(unmatched),
        "mean_gps_error_m": round(sum(errors) / len(errors), 1) if errors else None,
    }
    return results, unmatched, summary


def to_markdown(results, unmatched, summary):
    lines = ["# Drive report", "",
             f"- Real potholes on route: **{summary['real_potholes']}**",
             f"- Detected: **{summary['detected']}**  (recall **{summary['recall_pct']}%**)",
             f"- Mean GPS error of detections: **{summary['mean_gps_error_m']} m**",
             f"- Logged points matching no scouted pothole: **{summary['unmatched_detections']}**",
             "", "| Pothole | Size | Detected | Times logged | Max severity % | GPS error (m) |",
             "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['name']} | {r.get('size', '')} | {'yes' if r['detected'] else '**no**'} | "
                     f"{r['hits']} | {r['severity_pct'] if r['severity_pct'] is not None else '–'} | "
                     f"{r['gps_error_m'] if r['gps_error_m'] is not None else '–'} |")
    if unmatched:
        lines += ["", "## Unmatched detections (check: false positive or unscouted pothole?)", "",
                  "| Time | Lat | Lon | Severity % |", "|---|---|---|---|"]
        lines += [f"| {d['timestamp']} | {d['lat']:.6f} | {d['lon']:.6f} | {d['severity_pct']} |"
                  for d in unmatched]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ground-truth", required=True)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--since", help="only detections at/after this ISO date-time (UTC)")
    ap.add_argument("--vehicle")
    ap.add_argument("--radius", type=float, default=MATCH_RADIUS_M)
    a = ap.parse_args()

    with open(a.ground_truth, newline="", encoding="utf-8-sig") as f:
        truth = [{"name": r["name"], "lat": float(r["lat"]), "lon": float(r["lon"]),
                  "size": r.get("size", "")} for r in csv.DictReader(f)]
    dets = load_detections(a.db, a.since, a.vehicle)
    results, unmatched, summary = score(truth, dets, a.radius)
    md = to_markdown(results, unmatched, summary)
    print(md)
    out = Path(a.ground_truth).with_name("drive_report.md")
    out.write_text(md, encoding="utf-8")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
