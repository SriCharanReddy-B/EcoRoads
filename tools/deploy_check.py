"""
Checks a deployed EcoRoads server end to end — without changing any data.

    python tools\\deploy_check.py https://ecoroads-xxxx.onrender.com
    python tools\\deploy_check.py https://ecoroads-xxxx.onrender.com --api-key VEHICLE_KEY

Standard library only, so it runs with any Python. The first request may
take ~1 minute if the free server is asleep.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

results = []


def call(url, method="GET", body=None, headers=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def check(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")


def warn(name, detail):
    print(f"[WARN] {name} — {detail}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--api-key", help="the vehicle key (ECOROADS_INGEST_KEY) to verify")
    a = ap.parse_args()
    base = a.url.rstrip("/")

    print(f"Checking {base} (waking it up if it's asleep)…")
    start = time.time()
    status, path = None, "/api/ping"
    while time.time() - start < 120:
        try:
            status, _ = call(f"{base}{path}", timeout=60)
            if status == 200:
                break
            if status == 404 and path == "/api/ping":
                # older server version without /api/ping: it is awake, just not up to date
                warn("server version", "no /api/ping — your latest code isn't deployed yet "
                                       "(commit + push in GitHub Desktop, then wait for Render to redeploy)")
                path = "/api/health"
                continue
        except Exception as e:
            print(f"  still waiting ({type(e).__name__})…")
        time.sleep(3)
    check(f"server is up ({path})", status == 200, f"{time.time() - start:.0f} s")
    if status != 200:
        sys.exit("Server not reachable — check the Render logs.")

    status, body = call(f"{base}/api/health", timeout=60)
    ok = status == 200
    check("database connected (/api/health)", ok,
          body.decode()[:120] if ok else f"HTTP {status}: {body.decode()[:200]} — check DATABASE_URL")

    status, body = call(f"{base}/api/config")
    cfg = json.loads(body) if status == 200 else {}
    check("secure mode on (ECOROADS_ADMIN_KEY set)", cfg.get("secure") is True,
          "" if cfg.get("secure") else "anyone could register municipalities — set ECOROADS_ADMIN_KEY")

    status, body = call(f"{base}/")
    check("dashboard served at /", status == 200 and b"EcoRoads" in body)

    status, _ = call(f"{base}/api/municipalities", "POST",
                     {"municipality_id": "x", "name": "x", "center_lat": 0, "center_lon": 0, "radius_m": 1},
                     {"X-Admin-Key": "definitely-wrong"})
    check("registering without the admin key is refused", status == 401, f"HTTP {status}")

    status, _ = call(f"{base}/api/ingest", "POST", {"hazards": []}, {"X-API-Key": "definitely-wrong"})
    check("uploads with a wrong vehicle key are refused", status == 401,
          "" if status == 401 else f"HTTP {status} — set ECOROADS_INGEST_KEY")

    if a.api_key:
        status, _ = call(f"{base}/api/ingest", "POST", {"hazards": []}, {"X-API-Key": a.api_key})
        check("your vehicle key is accepted", status == 200, f"HTTP {status}")

    status, _ = call(f"{base}/downloads/EcoRoads-Edge.zip", "HEAD")
    if status == 200 or cfg.get("edge_download_url"):
        check("edge node download available", True)
    else:
        warn("edge node download", "not published yet (DEPLOY.md step 6)")

    status, body = call(f"{base}/api/municipalities")
    munis = json.loads(body).get("municipalities", []) if status == 200 else []
    print(f"\nMunicipalities registered: {len(munis)} "
          f"({', '.join(m['name'] for m in munis) or 'none yet — DEPLOY.md step 5'})")
    print("\nALL CHECKS PASSED" if all(results) else "\nSOME CHECKS FAILED — see above")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
