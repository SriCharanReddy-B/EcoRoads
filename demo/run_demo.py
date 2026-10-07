"""
EcoRoads one-command demo launcher.

Starts the whole system on ONE laptop — cloud API, municipality dashboard,
edge sync worker and the detector — registers a municipality zone that
covers the route, and opens the dashboard so potholes appear on the map
live while the video plays.

    python demo\\run_demo.py                       classroom: replay your latest recorded drive
    python demo\\run_demo.py --session PATH        replay a specific drive
    python demo\\run_demo.py --video clip.mp4      any video (+ simulated GPS route)
    python demo\\run_demo.py --phone               live: phone camera/GPS/motion -> laptop
    python demo\\run_demo.py --simulate            no model/camera at all: simulated fleet
    add --remote-cloud http://HOST_IP:9000          multi-laptop: this laptop is ONLY the detector;
                                                    the cloud + municipal dashboards run on other
                                                    laptops (see MULTI_LAPTOP.md, demo/host_cloud.py)
    add --cloud-delay 30                           show OFFLINE-FIRST: the cloud only comes
                                                    up after 30 s; watch "pending sync" grow,
                                                    then everything flushes onto the map

Each run uses a fresh demo database in demo/runtime/, so your real drive
data is never touched. Ctrl+C stops everything.
"""

import argparse
import csv
import json
import math
import os
import shutil
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDGE = ROOT / "ecoroads-edge"
CLOUD_APP = ROOT / "ecoroads-cloud" / "app"
DASHBOARD = ROOT / "ecoroads-dashboard"
RUNTIME = ROOT / "demo" / "runtime"
PY = sys.executable

children = []


def log(msg):
    print(f"[demo] {msg}", flush=True)


# ------------------------------------------------------------------ helpers
def spawn(args, cwd, env=None, quiet=True):
    out = open(RUNTIME / f"{Path(args[1] if args[1] != '-m' else args[2]).stem}.log", "w") if quiet else None
    p = subprocess.Popen(args, cwd=cwd, env={**os.environ, **(env or {})},
                         stdout=out, stderr=subprocess.STDOUT if quiet else None)
    children.append(p)
    return p


def http_json(url, body=None, timeout=5, insecure=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    ctx = ssl._create_unverified_context() if insecure else None   # our own self-signed bridge
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return json.loads(r.read() or b"{}")


def wait_for(url, seconds=30, insecure=False):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            return http_json(url, insecure=insecure)
        except Exception:
            time.sleep(0.5)
    return None


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def zone_covering(points, margin_m=150, min_radius=300):
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    r = max(haversine_m(lat, lon, *p) for p in points) + margin_m
    return lat, lon, max(r, min_radius)


def route_points(args):
    if args.session_dir:
        with open(args.session_dir / "gps.csv", newline="") as f:
            pts = [(float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)]
        if pts:
            return pts
        log("this recording has no GPS fixes — using the simulated route instead")
    sys.path.insert(0, str(EDGE / "src"))
    from gps_simulator import DEFAULT_ROUTE
    return list(DEFAULT_ROUTE)


def register_zone(cloud, muni_id, name, lat, lon, radius):
    http_json(f"{cloud}/api/municipalities", {"municipality_id": muni_id, "name": name,
                                              "center_lat": lat, "center_lon": lon, "radius_m": radius})
    log(f"registered municipality '{name}' ({radius:.0f} m around {lat:.5f},{lon:.5f})")


# ------------------------------------------------------------------ main
def main():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    ap = argparse.ArgumentParser(description="EcoRoads one-command demo")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--session", help="recorded drive folder, or 'latest' (default)")
    g.add_argument("--video", help="any video file (GPS is simulated)")
    g.add_argument("--phone", action="store_true", help="live phone camera + GPS + motion")
    g.add_argument("--simulate", action="store_true", help="no camera/model: simulated fleet")
    ap.add_argument("--cloud-delay", type=float, default=0, help="start the cloud N seconds late")
    ap.add_argument("--remote-cloud", help="cloud on another laptop, e.g. http://192.168.43.20:9000")
    ap.add_argument("--cloud-port", type=int, default=9000)
    ap.add_argument("--dash-port", type=int, default=8080)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-window", action="store_true", help="hide the detector preview window")
    args = ap.parse_args()

    # -------- decide what we're demoing
    args.session_dir = None
    if not (args.video or args.phone or args.simulate):
        sys.path.insert(0, str(EDGE / "src"))
        from session import latest_session
        s = latest_session() if args.session in (None, "latest") else Path(args.session)
        if s is None or not (Path(s) / "video.mp4").exists():
            if args.session:
                sys.exit(f"No recorded drive at {args.session}")
            sys.exit("No recorded drive yet. Use one of:\n"
                     "  --video your_clip.mp4   (e.g. made with demo\\make_demo_video.py)\n"
                     "  --phone                 (live phone)\n"
                     "  --simulate              (no camera or model needed)")
        args.session_dir = Path(s)

    if not args.simulate and not (EDGE / "models" / "best.pt").exists():
        sys.exit("No trained model at ecoroads-edge/models/best.pt — train it first "
                 "(ecoroads-edge/training/train.py) or run with --simulate.")

    # -------- fresh demo databases
    shutil.rmtree(RUNTIME, ignore_errors=True)
    RUNTIME.mkdir(parents=True)
    env = {"ECOROADS_DB": str(RUNTIME / "cloud.db"), "ECOROADS_EDGE_DB": str(RUNTIME / "edge.db")}
    cloud = f"http://localhost:{args.cloud_port}"
    muni_id = "demo_ward"

    def start_cloud():
        spawn([PY, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(args.cloud_port)],
              CLOUD_APP, env)
        if wait_for(f"{cloud}/api/health") is None:
            log(f"cloud failed to start — see {RUNTIME / 'uvicorn.log'}")
            return False
        log(f"cloud API up: {cloud}/docs")
        return True

    if args.remote_cloud:
        if args.simulate:
            sys.exit("--simulate runs everything locally; drop --remote-cloud, or run "
                     "tools\\simulate_fleet.py --cloud URL")
        return run_detector_only(args, env)

    try:
        # The zone must exist before hazards arrive, so with --cloud-delay we register
        # it on a temporary cloud first (same DB file), then stop that cloud.
        if not start_cloud():
            sys.exit(1)

        spawn([PY, "-m", "http.server", str(args.dash_port), "--directory", str(DASHBOARD)], DASHBOARD)

        if args.simulate:
            subprocess.run([PY, str(ROOT / "tools" / "simulate_fleet.py"), "--cloud", cloud, "--repair-demo"],
                           check=False)
            muni_id = "ward_a"
        elif not args.phone:
            lat, lon, r = zone_covering(route_points(args))
            register_zone(cloud, muni_id, "Demo Ward (route)", lat, lon, r)

        dash = (f"http://localhost:{args.dash_port}/index.html?api={cloud}"
                f"&muni={muni_id}&refresh=3")
        log(f"dashboard: {dash}")
        if not args.no_browser:
            webbrowser.open(dash)

        if args.simulate:
            log("simulated fleet loaded. Press Ctrl+C to stop.")
            while True:
                time.sleep(1)

        if args.cloud_delay:
            children.pop(0).terminate()     # take the cloud "offline"
            log(f"cloud is OFFLINE for {args.cloud_delay:.0f} s — detections will queue on the edge")

            def late_start():
                time.sleep(args.cloud_delay)
                log("cloud coming back ONLINE — watch the queued potholes sync to the map")
                start_cloud()
            threading.Thread(target=late_start, daemon=True).start()

        spawn([PY, "sync_worker.py", "--cloud-url", cloud, "--interval", "3"], EDGE / "src", env)

        det = detector_command(args)

        if args.phone:
            threading.Thread(target=register_zone_from_phone, args=(cloud, muni_id), daemon=True).start()

        log("starting detector — the preview window shows what the model sees")
        detector = subprocess.Popen(det, cwd=EDGE / "src", env={**os.environ, **env})
        children.append(detector)
        detector.wait()

        log("detector finished. Dashboard stays live — press Ctrl+C to stop the demo.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(children):
            if p.poll() is None:
                p.terminate()
        for p in children:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        log("stopped.")


def detector_command(args):
    det = [PY, "capture_detect.py"]
    if args.phone:
        det += ["--phone"]
    elif args.video:
        det += ["--source", str(Path(args.video).resolve()), "--no-record"]
    else:
        det += ["--replay", str(args.session_dir.resolve())]
    if args.no_window:
        det += ["--no-window"]
    return det


def run_detector_only(args, env):
    """Multi-laptop mode: detector + sync worker here; cloud and dashboards elsewhere."""
    cloud = args.remote_cloud.rstrip("/")
    health = wait_for(f"{cloud}/api/health", seconds=5)
    if health is None:
        log(f"cloud at {cloud} is not reachable right now — detections will be buffered "
            f"locally and synced when it is (offline-first). Check same Wi-Fi + firewall.")
    else:
        munis = http_json(f"{cloud}/api/municipalities")["municipalities"]
        log(f"connected to {cloud}: {len(munis)} municipalities registered "
            f"({', '.join(m['name'] for m in munis) or 'none yet — register them on the municipal laptops'})")
    try:
        spawn([PY, "sync_worker.py", "--cloud-url", cloud, "--interval", "3"], EDGE / "src", env)
        log("starting detector — potholes will appear on the municipal laptops that own each area")
        detector = subprocess.Popen(detector_command(args), cwd=EDGE / "src", env={**os.environ, **env})
        children.append(detector)
        detector.wait()
        log("detector finished; letting the last potholes sync…")
        time.sleep(8)
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(children):
            if p.poll() is None:
                p.terminate()
        log("stopped.")


def register_zone_from_phone(cloud, muni_id):
    """Live phone demo: as soon as the phone reports a GPS fix, register a zone around it."""
    log("waiting for the phone's first GPS fix to register a 600 m zone around it…")
    while True:
        st = wait_for("https://127.0.0.1:8443/status", seconds=5, insecure=True)
        if st and st.get("last_fix"):
            lat, lon = st["last_fix"]
            try:
                register_zone(cloud, muni_id, "Demo Ward (around phone)", lat, lon, 600)
                return
            except Exception:
                pass
        time.sleep(2)


if __name__ == "__main__":
    main()
