"""Picks the GPS source named in config.json ("gps_mode")."""

from gps_simulator import GPSSimulator


def make_gps(cfg):
    mode = cfg["gps_mode"]
    if mode == "simulated":
        return GPSSimulator(speed_kmh=30)
    from gps_nmea import NMEAGPS
    return NMEAGPS(mode,
                   host=cfg["gps_host"], port=cfg["gps_port"],
                   serial_port=cfg["gps_serial_port"], baud=cfg["gps_baud"],
                   max_fix_age_s=cfg["gps_max_fix_age_s"])
