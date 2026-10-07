"""
EDGE NODE — Sync worker. The only piece of this project that touches
the network. Runs as a separate process alongside capture_detect.py.

Every sync_interval_s seconds:
  1. Probe the cloud's /api/health (short timeout). This checks the
     thing we actually need — "can I reach MY server?" — rather than
     "is the internet up?" (internet can be up while the server is down).
  2. If reachable: send unsynced rows in batches, mark them synced only
     after the cloud answers 2xx. If the response is lost mid-way, rows
     stay unsynced and are re-sent; the cloud ignores exact duplicates,
     so retries are safe.
  3. If unreachable: do nothing, retry next interval.

Payload sent per hazard is intentionally minimal:
    { vehicle_id, timestamp, lat, lon, severity_pct }
"""

import time

import requests

from config import load_config
from storage import get_connection, mark_synced, unsynced_rows

HEALTH_TIMEOUT_S = 3


def headers(cfg):
    return {"X-API-Key": cfg["api_key"]} if cfg["api_key"] else {}


def cloud_reachable(cfg):
    try:
        r = requests.get(f"{cfg['cloud_url']}/api/health", timeout=HEALTH_TIMEOUT_S)
        return r.ok
    except requests.RequestException:
        return False


def sync_once(conn, cfg):
    """Send everything pending, batch by batch. Returns rows synced."""
    total = 0
    while True:
        rows = unsynced_rows(conn, limit=cfg["sync_batch_size"])
        if not rows:
            return total

        payload = [{k: r[k] for k in ("vehicle_id", "timestamp", "lat", "lon", "severity_pct")}
                   for r in rows]
        try:
            resp = requests.post(f"{cfg['cloud_url']}/api/ingest", json={"hazards": payload},
                                 headers=headers(cfg), timeout=cfg["sync_timeout_s"])
        except requests.RequestException as e:
            print(f"  sync failed ({e}), will retry next interval")
            return total

        if resp.status_code == 401:
            print("  cloud rejected our API key — check api_key in config.json")
            return total
        if not resp.ok:
            print(f"  cloud returned {resp.status_code}: {resp.text[:200]} — will retry")
            return total

        mark_synced(conn, [r["id"] for r in rows])
        total += len(rows)
        body = resp.json()
        print(f"  batch of {len(rows)}: accepted {body.get('accepted')}, "
              f"outside every municipality {body.get('rejected_no_municipality')}, "
              f"non-public road {body.get('rejected_unregistered_road')}, "
              f"duplicates {body.get('duplicates', 0)}")


def main():
    import argparse
    p = argparse.ArgumentParser(description="EcoRoads edge -> cloud sync worker")
    p.add_argument("--cloud-url")
    p.add_argument("--interval", type=float, help="seconds between sync attempts")
    a = p.parse_args()
    cfg = load_config()
    if a.cloud_url:
        cfg["cloud_url"] = a.cloud_url
    if a.interval:
        cfg["sync_interval_s"] = a.interval
    conn = get_connection()
    print(f"Sync worker -> {cfg['cloud_url']} every {cfg['sync_interval_s']}s.\n")
    while True:
        if cloud_reachable(cfg):
            n = sync_once(conn, cfg)
            print(f"[online] synced {n} hazard(s)" if n else "[online] nothing to sync")
        else:
            print("[offline] cloud unreachable — buffering locally")
        time.sleep(cfg["sync_interval_s"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSync worker stopped.")
