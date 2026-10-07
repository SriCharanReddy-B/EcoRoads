"""
Asks the few questions a new vehicle needs and writes config.json.
Run by INSTALL.bat (packaged edge node); safe to re-run any time to change answers.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
PACKAGE_DEFAULTS = ROOT / "package_defaults.json"   # written by tools/build_edge_package.py


def ask(question, default):
    shown = f" [{default}]" if default else ""
    answer = input(f"{question}{shown}: ").strip()
    return answer or default


def main():
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    defaults = json.loads(PACKAGE_DEFAULTS.read_text()) if PACKAGE_DEFAULTS.exists() else {}

    print("\n--- Configure this vehicle (press Enter to keep the value in [brackets]) ---")
    cfg["vehicle_id"] = ask("Vehicle ID (unique per vehicle, e.g. bus_12)", cfg.get("vehicle_id", "car_01"))
    cfg["cloud_url"] = ask("EcoRoads server address",
                           cfg.get("cloud_url") or defaults.get("cloud_url", "http://localhost:9000")).rstrip("/")
    key = ask("Vehicle API key (from the server admin; Enter if none)", cfg.get("api_key", ""))
    cfg["api_key"] = key
    cfg.setdefault("source", "phone")
    cfg.setdefault("camera_lookahead_m", 6.0)

    CONFIG.write_text(json.dumps(cfg, indent=2))
    print(f"Saved {CONFIG}")


if __name__ == "__main__":
    main()
