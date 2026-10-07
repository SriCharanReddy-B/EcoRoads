"""
Simulated GPS for laptop-only testing (no live GNSS hardware).
Replace DEFAULT_ROUTE with real coordinates near wherever you test,
or point GPX_FILE at a real recorded route.

For real GPS (phone or USB module) see gps_nmea.py; gps.py picks one
based on config.json's "gps_mode".
"""

import time

DEFAULT_ROUTE = [
    (17.4065, 78.4772),
    (17.4070, 78.4778),
    (17.4076, 78.4785),
    (17.4082, 78.4791),
    (17.4088, 78.4798),
    (17.4094, 78.4804),
]

GPX_FILE = None  # set to a path string to use a real GPX track instead


class GPSSimulator:
    def __init__(self, speed_kmh=30, route=None):
        self.route = route or (self._load_gpx(GPX_FILE) if GPX_FILE else DEFAULT_ROUTE)
        self.speed_kmh = speed_kmh
        self.start_time = time.time()
        self.seconds_per_point = 3600 / max(speed_kmh, 1) * 0.05

    def _load_gpx(self, path):
        import gpxpy
        with open(path, "r") as f:
            gpx = gpxpy.parse(f)
        points = []
        for track in gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    points.append((point.latitude, point.longitude))
        return points or DEFAULT_ROUTE

    def get_current_position(self):
        elapsed = time.time() - self.start_time
        idx = int(elapsed / self.seconds_per_point) % len(self.route)
        return self.route[idx]

    def get_speed_mps(self):
        return self.speed_kmh / 3.6

    def close(self):
        pass


if __name__ == "__main__":
    gps = GPSSimulator(speed_kmh=30)
    for _ in range(5):
        print(gps.get_current_position())
        time.sleep(1)
