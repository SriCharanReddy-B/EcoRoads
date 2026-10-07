"""
Phone bridge — turns a phone mounted on the windscreen into the edge
node's camera, GPS and accelerometer, with NO app install.

    phone browser (phone/phone.html)                laptop (this file)
    ───────────────────────────────                ──────────────────────────
    rear camera → JPEG ── POST /frame ───────────►  latest frame → YOLO
    GPS fix     ┐
    motion 60Hz ┴──────── POST /sensors ─────────►  GPS history, jolt buffer
                ◄──────── GET  /status ──────────── "12 fps, 3 potholes logged"

Why HTTPS: browsers only allow camera + GPS on "secure" pages. The
laptop generates a self-signed certificate once (certs.py); the phone
shows a warning the first time ("Advanced -> Proceed"), then works.

Why plain HTTP POSTs instead of WebSockets: the phone sends the next
frame only after the laptop answered the previous one. That gives
natural back-pressure — if the laptop or Wi-Fi is slow, the phone simply
sends fewer frames instead of building a growing backlog of stale video.

Everything is Python standard library (+ OpenCV to decode JPEGs), and
it only needs the local link between phone and laptop (phone hotspot),
not the internet — so the edge node stays offline-first.
"""

import collections
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from timesync import ClockSync

PHONE_PAGE = Path(__file__).resolve().parent.parent / "phone" / "phone.html"
MAX_FRAME_BYTES = 4 * 1024 * 1024
MOTION_BUFFER_S = 20
GPS_HISTORY = 600


class PhoneBridge:
    def __init__(self, port=8443, use_tls=True, phone_settings=None, clock=time.monotonic,
                 max_gps_accuracy_m=30.0, max_fix_age_s=10.0):
        self.port = port
        self.use_tls = use_tls
        self.clock = clock
        self.sync = ClockSync(clock)
        self.phone_settings = phone_settings or {}
        self.max_gps_accuracy_m = max_gps_accuracy_m
        self.max_fix_age_s = max_fix_age_s

        self._cond = threading.Condition()
        self._frame = None            # (jpeg_bytes, laptop_t, seq)
        self._seq = 0
        self._lock = threading.Lock()
        self._gps = collections.deque(maxlen=GPS_HISTORY)  # (t, lat, lon, speed, accuracy)
        self._motion = collections.deque()                 # (t, deviation_g)
        self.listeners = []           # callables(kind, payload) e.g. the session recorder
        self.status_text = "waiting for detector…"
        self.stats = {"frames": 0, "gps_fixes": 0, "gps_rejected": 0, "motion_samples": 0,
                      "last_frame_at": None, "fps": 0.0}
        self._fps_window = collections.deque(maxlen=30)
        self._server = None

    # ------------------------------------------------------------ server
    def start(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"   # keep-alive: one TCP/TLS connection per stream

            def log_message(self, *a):      # keep the console quiet
                pass

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _body(self):
                n = int(self.headers.get("Content-Length", 0))
                if n > MAX_FRAME_BYTES:
                    raise ValueError("payload too large")
                return self.rfile.read(n)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self._send(200, PHONE_PAGE.read_bytes(), "text/html; charset=utf-8")
                elif self.path == "/config.json":
                    self._send(200, json.dumps(bridge.phone_settings).encode())
                elif self.path == "/status":
                    self._send(200, json.dumps(bridge.status()).encode())
                else:
                    self._send(404, b'{"error":"not found"}')

            def do_POST(self):
                try:
                    body = self._body()
                    if self.path == "/frame":
                        ts = float(self.headers.get("X-Capture-Ts", "0")) / 1000.0
                        bridge.push_frame(body, ts)
                        self._send(204)
                    elif self.path == "/sensors":
                        bridge.push_sensors(json.loads(body or b"{}"))
                        self._send(204)
                    else:
                        self._send(404, b'{"error":"not found"}')
                except (ValueError, KeyError, TypeError) as e:
                    self._send(400, json.dumps({"error": str(e)}).encode())

        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        self._server.daemon_threads = True
        if self.use_tls:
            from certs import ensure_certificate
            cert, key = ensure_certificate()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def urls(self):
        from certs import local_ipv4_addresses
        scheme = "https" if self.use_tls else "http"
        return [f"{scheme}://{ip}:{self.port}" for ip in local_ipv4_addresses()]

    # ------------------------------------------------------------ ingest
    def push_frame(self, jpeg, phone_ts_s):
        if not jpeg:
            raise ValueError("empty frame")
        t = self.sync.observe(phone_ts_s) if phone_ts_s else self.clock()
        with self._cond:
            self._seq += 1
            self._frame = (jpeg, t, self._seq)
            self.stats["frames"] += 1
            self.stats["last_frame_at"] = self.clock()
            self._fps_window.append(self.clock())
            self._cond.notify_all()
        for fn in self.listeners:
            fn("frame", (jpeg, t))

    def push_sensors(self, msg):
        for g in msg.get("gps", []):
            t = self.sync.observe(float(g["t"]) / 1000.0)
            acc = g.get("accuracy")
            if acc is not None and acc > self.max_gps_accuracy_m:
                self.stats["gps_rejected"] += 1   # e.g. indoors / tall buildings
                continue
            fix = (t, float(g["lat"]), float(g["lon"]),
                   float(g["speed"]) if g.get("speed") is not None else None, acc)
            with self._lock:
                self._gps.append(fix)
            self.stats["gps_fixes"] += 1
            for fn in self.listeners:
                fn("gps", fix)

        samples = msg.get("motion", [])
        if samples:
            rows = []
            for s in samples:
                t = self.sync.observe(float(s[0]) / 1000.0)
                ax, ay, az = float(s[1]), float(s[2]), float(s[3])   # in g
                dev = abs((ax * ax + ay * ay + az * az) ** 0.5 - 1.0)
                rows.append((t, dev, ax, ay, az))
            now = self.clock()
            with self._lock:
                self._motion.extend((t, dev) for t, dev, *_ in rows)
                while self._motion and now - self._motion[0][0] > MOTION_BUFFER_S:
                    self._motion.popleft()
            self.stats["motion_samples"] += len(rows)
            for fn in self.listeners:
                fn("motion", rows)

    # ------------------------------------------------------------ readers
    def wait_frame(self, after_seq, timeout):
        """Block until a frame newer than after_seq arrives. Returns (jpeg, t, seq) or None."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._frame is None or self._frame[2] <= after_seq:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cond.wait(remaining)
            return self._frame

    def latest_fix(self):
        with self._lock:
            return self._gps[-1] if self._gps else None

    def previous_fix(self):
        with self._lock:
            return self._gps[-2] if len(self._gps) > 1 else None

    def peak_jolt(self, t0, t1):
        with self._lock:
            vals = [d for t, d in self._motion if t0 <= t <= t1]
        return max(vals) if vals else None

    def status(self):
        w = self._fps_window
        fps = (len(w) - 1) / (w[-1] - w[0]) if len(w) > 1 and w[-1] > w[0] else 0.0
        fix = self.latest_fix()
        return {**self.stats, "fps": round(fps, 1), "status": self.status_text,
                "gps_age_s": round(self.clock() - fix[0], 1) if fix else None,
                "last_fix": [fix[1], fix[2]] if fix else None}


# ---------------------------------------------------------------- adapters
# Same interfaces the rest of the edge node already uses, so
# capture_detect.py treats "phone" exactly like webcam / NMEA GPS / Arduino.

class PhoneFrameSource:
    def __init__(self, bridge, timeout_s=5.0):
        self.bridge = bridge
        self.timeout_s = timeout_s
        self._seq = 0
        self.is_live = True

    def isOpened(self):
        return True

    def read(self):
        """(ok, frame_bgr, laptop_t). Waits for the phone; ok=False after timeout_s of silence."""
        import cv2
        # wait in short slices: on Windows a long blocking wait ignores Ctrl+C
        deadline = time.monotonic() + self.timeout_s
        got = None
        while got is None and time.monotonic() < deadline:
            got = self.bridge.wait_frame(self._seq, 0.5)
        if got is None:
            return False, None, None
        jpeg, t, self._seq = got
        frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return self.read()
        return True, frame, t

    def release(self):
        pass


class PhoneGPS:
    def __init__(self, bridge):
        self.bridge = bridge

    def get_current_position(self):
        fix = self.bridge.latest_fix()
        if fix is None or self.bridge.clock() - fix[0] > self.bridge.max_fix_age_s:
            return None
        return fix[1], fix[2]

    def get_speed_mps(self):
        fix = self.bridge.latest_fix()
        if fix is None:
            return 0.0
        if fix[3] is not None:
            return fix[3]
        # some phones/browsers don't report speed: derive it from the last two fixes
        prev = self.bridge.previous_fix()
        if prev is None or fix[0] - prev[0] <= 0:
            return 0.0
        from debouncer import haversine_m
        return haversine_m(prev[1], prev[2], fix[1], fix[2]) / (fix[0] - prev[0])

    def close(self):
        pass


class PhoneAccel:
    def __init__(self, bridge):
        self.bridge = bridge

    def peak_jolt(self, t0, t1):
        return self.bridge.peak_jolt(t0, t1)

    def close(self):
        pass


if __name__ == "__main__":
    # Standalone check: run this, open the printed URL on the phone, watch the counters.
    b = PhoneBridge().start()
    print("Open on the phone:", *b.urls(), sep="\n  ")
    try:
        while True:
            time.sleep(2)
            print(b.status())
    except KeyboardInterrupt:
        b.stop()
