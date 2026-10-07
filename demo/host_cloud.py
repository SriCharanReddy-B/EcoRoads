"""
Run on the laptop that HOSTS the server side in a multi-laptop setup.

Starts the cloud API (port 9000) and serves the dashboard (port 8080) to
the whole network, optionally registers municipality zones, and prints
the exact address each other laptop should use:

  - the detector laptop     -> cloud_url for its config.json / DEMO.bat --remote-cloud
  - each municipal laptop   -> a dashboard link locked to that municipality
                               (just a browser — nothing to install there)

    python demo\\host_cloud.py                         municipalities register themselves on their laptops
    python demo\\host_cloud.py --zones 2               split your latest drive's route into Ward A + Ward B
    python demo\\host_cloud.py --zones 2 --session PATH
    python demo\\host_cloud.py --zones 2 --fresh       start from an empty database (demo)

The host can be one of the municipal laptops (it runs the server AND
shows its own dashboard) or a separate machine.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "ecoroads-edge" / "src"))
sys.path.insert(0, str(HERE))

from zones import route_from_session, split_route   # noqa: E402

PY = sys.executable


def http_json(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def main():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    ap = argparse.ArgumentParser(description="Host EcoRoads cloud + dashboard for other laptops")
    ap.add_argument("--zones", type=int, default=0, help="split a recorded route into N municipalities")
    ap.add_argument("--session", default="latest", help="recorded drive to take the route from")
    ap.add_argument("--fresh", action="store_true", help="use an empty demo database")
    ap.add_argument("--cloud-port", type=int, default=9000)
    ap.add_argument("--dash-port", type=int, default=8080)
    ap.add_argument("--api-key", help="require this key from detectors (X-API-Key)")
    a = ap.parse_args()

    env = dict(os.environ)
    if a.fresh:
        rt = HERE / "runtime_host"
        shutil.rmtree(rt, ignore_errors=True)
        rt.mkdir()
        env["ECOROADS_DB"] = str(rt / "cloud.db")
    if a.api_key:
        env["ECOROADS_INGEST_KEY"] = a.api_key

    procs = [
        subprocess.Popen([PY, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(a.cloud_port), "--log-level", "warning"],
                         cwd=ROOT / "ecoroads-cloud" / "app", env=env),
        subprocess.Popen([PY, "-m", "http.server", str(a.dash_port), "--bind", "0.0.0.0",
                          "--directory", str(ROOT / "ecoroads-dashboard")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    local = f"http://localhost:{a.cloud_port}"
    try:
        for _ in range(60):
            try:
                http_json(f"{local}/api/health")
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit("cloud did not start — see the messages above")

        if a.zones:
            from session import latest_session
            sdir = latest_session() if a.session == "latest" else Path(a.session)
            if sdir is None:
                sys.exit("No recorded drive to split. Do a drive first, or leave out --zones "
                         "and let each municipality register on its own laptop.")
            for z in split_route(route_from_session(sdir), a.zones):
                http_json(f"{local}/api/municipalities", z)
                print(f"registered {z['name']}: {z['radius_m']} m around "
                      f"{z['center_lat']:.5f},{z['center_lon']:.5f}")

        from certs import local_ipv4_addresses
        ips = local_ipv4_addresses()
        print("\n" + "=" * 72)
        print(" EcoRoads server is running on this laptop. On the OTHER laptops use:")
        print("=" * 72)
        for ip in ips:
            print(f"\n  [network {ip}]")
            print(f"  Detector laptop  ->  cloud_url = http://{ip}:{a.cloud_port}")
            print(f"                       (or: DEMO.bat --remote-cloud http://{ip}:{a.cloud_port})")
            print(f"  Register a new municipality (any laptop):")
            print(f"     http://{ip}:{a.dash_port}/index.html?api=http://{ip}:{a.cloud_port}")
        print("\n  Municipal laptops (one link each, locked to that municipality):")

        shown = set()
        while True:      # keep printing links as municipalities register themselves
            try:
                for m in http_json(f"{local}/api/municipalities")["municipalities"]:
                    if m["municipality_id"] in shown:
                        continue
                    shown.add(m["municipality_id"])
                    for ip in ips:
                        print(f"   {m['name']:<28} http://{ip}:{a.dash_port}/index.html?"
                              f"api=http://{ip}:{a.cloud_port}&muni={m['municipality_id']}&lock=1&refresh=3")
            except Exception:
                pass
            time.sleep(3)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
        print("\nserver stopped.")


if __name__ == "__main__":
    main()
