"""
Real GPS for the edge node, from any source that speaks NMEA 0183 — the
plain-text sentence format every GPS chip and GPS-sharing phone app uses:

    $GPRMC,123519,A,1724.4500,N,07828.6500,E,016.2,084.4,071026,,,A*75

Supported transports:
  - nmea_tcp    : phone app acting as an NMEA TCP server
                  (Android "Share GPS", "GPS 2 Bluetooth/NMEA" style apps)
  - nmea_udp    : phone app pushing NMEA over UDP to this laptop
  - nmea_serial : USB / UART GPS module (e.g. u-blox NEO-6M) on a COM port

None of these need internet — the phone's hotspot (or a USB cable) is a
local link, so this keeps the edge node offline-first.

A background thread reads sentences and keeps the latest fix; the main
loop just asks for it, so a slow GPS never stalls video processing.
"""

import socket
import threading
import time


def _checksum_ok(sentence):
    if "*" not in sentence:
        return True  # some apps omit checksums
    body, _, given = sentence[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(given[:2], 16)
    except ValueError:
        return False


def _to_decimal(value, hemisphere):
    """NMEA ddmm.mmmm / dddmm.mmmm -> signed decimal degrees."""
    if not value:
        return None
    dot = value.index(".") if "." in value else len(value)
    degrees = float(value[:dot - 2])
    minutes = float(value[dot - 2:])
    dec = degrees + minutes / 60.0
    return -dec if hemisphere in ("S", "W") else dec


def parse_nmea(sentence):
    """
    Returns dict(lat, lon, speed_mps) for a valid RMC/GGA fix, else None.
    RMC has speed; GGA doesn't (speed_mps is None then).
    """
    sentence = sentence.strip()
    if not sentence.startswith("$") or not _checksum_ok(sentence):
        return None
    fields = sentence.split("*")[0].split(",")
    kind = fields[0][3:]  # GPRMC / GNRMC / GLRMC -> RMC

    try:
        if kind == "RMC" and len(fields) >= 8:
            if fields[2] != "A":          # V = void, no fix
                return None
            lat = _to_decimal(fields[3], fields[4])
            lon = _to_decimal(fields[5], fields[6])
            speed = float(fields[7]) * 0.514444 if fields[7] else None  # knots -> m/s
            return {"lat": lat, "lon": lon, "speed_mps": speed} if lat is not None else None
        if kind == "GGA" and len(fields) >= 7:
            if fields[6] in ("", "0"):    # fix quality 0 = invalid
                return None
            lat = _to_decimal(fields[2], fields[3])
            lon = _to_decimal(fields[4], fields[5])
            return {"lat": lat, "lon": lon, "speed_mps": None} if lat is not None else None
    except (ValueError, IndexError):
        return None
    return None


class NMEAGPS:
    def __init__(self, mode, host=None, port=None, serial_port=None, baud=9600, max_fix_age_s=10):
        self.mode = mode
        self.host, self.port = host, port
        self.serial_port, self.baud = serial_port, baud
        self.max_fix_age_s = max_fix_age_s
        self._lat = self._lon = None
        self._speed = 0.0
        self._fix_time = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---------- public API (same shape as GPSSimulator) ----------
    def get_current_position(self):
        """Latest fix, or None if there is no fix younger than max_fix_age_s."""
        with self._lock:
            if self._lat is None or time.monotonic() - self._fix_time > self.max_fix_age_s:
                return None
            return (self._lat, self._lon)

    def get_speed_mps(self):
        with self._lock:
            return self._speed

    def close(self):
        self._stop.set()

    # ---------- background reader ----------
    def _handle_line(self, line):
        fix = parse_nmea(line)
        if fix:
            with self._lock:
                self._lat, self._lon = fix["lat"], fix["lon"]
                if fix["speed_mps"] is not None:
                    self._speed = fix["speed_mps"]
                self._fix_time = time.monotonic()

    def _run(self):
        while not self._stop.is_set():
            try:
                if self.mode == "nmea_tcp":
                    self._read_tcp()
                elif self.mode == "nmea_udp":
                    self._read_udp()
                elif self.mode == "nmea_serial":
                    self._read_serial()
                else:
                    raise ValueError(f"unknown gps_mode {self.mode}")
            except ValueError:
                raise
            except Exception as e:  # source dropped: phone locked, cable pulled...
                print(f"[gps] {self.mode} source error: {e} — retrying in 3s")
                time.sleep(3)

    def _read_tcp(self):
        with socket.create_connection((self.host, self.port), timeout=10) as s:
            print(f"[gps] connected to {self.host}:{self.port}")
            buf = b""
            while not self._stop.is_set():
                chunk = s.recv(4096)
                if not chunk:
                    raise ConnectionError("phone closed the connection")
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    self._handle_line(line.decode("ascii", "ignore"))

    def _read_udp(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(("0.0.0.0", self.port))
            s.settimeout(10)
            print(f"[gps] listening for NMEA on UDP :{self.port}")
            while not self._stop.is_set():
                data, _ = s.recvfrom(4096)
                for line in data.decode("ascii", "ignore").splitlines():
                    self._handle_line(line)

    def _read_serial(self):
        import serial
        with serial.Serial(self.serial_port, self.baud, timeout=2) as ser:
            print(f"[gps] reading {self.serial_port} @ {self.baud}")
            while not self._stop.is_set():
                self._handle_line(ser.readline().decode("ascii", "ignore"))


if __name__ == "__main__":
    # Quick parser check — no hardware needed.
    print(parse_nmea("$GPRMC,123519,A,1724.4500,N,07828.6500,E,016.2,084.4,071026,,,A*75"))
    print(parse_nmea("$GPGGA,123519,1724.4500,N,07828.6500,E,1,08,0.9,545.4,M,46.9,M,,*42"))
