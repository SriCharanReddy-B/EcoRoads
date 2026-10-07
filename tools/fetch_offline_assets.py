"""
Run ONCE at home (with internet) before a classroom demo:
copies Leaflet into ecoroads-dashboard/vendor/ so the dashboard loads
even if the classroom Wi-Fi blocks CDNs.

(The background map tiles still come from OpenStreetMap; if the room
has no internet at all, share your phone's hotspot with the laptop.
Without tiles the potholes, zones and list still work on a blank map.)

    python tools\\fetch_offline_assets.py
"""

import urllib.request
from pathlib import Path

BASE = "https://unpkg.com/leaflet@1.9.4/dist/"
FILES = ["leaflet.js", "leaflet.css", "images/layers.png", "images/layers-2x.png",
         "images/marker-icon.png", "images/marker-icon-2x.png", "images/marker-shadow.png"]
VENDOR = Path(__file__).resolve().parent.parent / "ecoroads-dashboard" / "vendor"

for name in FILES:
    dest = VENDOR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(BASE + name, timeout=30) as r:
        dest.write_bytes(r.read())
    print(f"saved {dest.relative_to(VENDOR.parent.parent)}")
print("Done — the dashboard no longer needs the CDN.")
