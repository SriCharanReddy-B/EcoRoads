"""
Every way the edge node can get video, behind one interface:

    ok, frame, t = source.read()

`t` is the capture time in seconds on the timeline the rest of the
pipeline uses (debouncer, GPS, accelerometer fusion):
  - live sources (webcam, IP camera URL, phone bridge): laptop monotonic clock
  - recorded video / replayed drive: position inside the recording

Sources:
  WebcamSource  — USB/built-in webcam, or a phone exposed as a webcam (DroidCam etc.)
  StreamSource  — network camera URL, e.g. IP Webcam app: http://PHONE_IP:8080/video
  FileSource    — a video file, played back at real speed (classroom demo)
  (PhoneFrameSource lives in phone_bridge.py; ReplaySource in session.py)
"""

import threading
import time

import cv2


class WebcamSource:
    is_live = True

    def __init__(self, index):
        self.cap = cv2.VideoCapture(index)

    def isOpened(self):
        return self.cap.isOpened()

    def read(self):
        ok, frame = self.cap.read()
        return ok, frame, time.monotonic()

    def release(self):
        self.cap.release()


class StreamSource:
    """
    Network video (MJPEG/RTSP). OpenCV buffers network frames internally;
    if detection is slower than the stream, that buffer makes the video
    you process seconds old — useless when GPS says where you are NOW.
    So a background thread keeps reading and we only ever hand out the
    newest frame. It also reconnects if the phone drops off the Wi-Fi.
    """
    is_live = True

    def __init__(self, url, reconnect_s=2.0):
        self.url = url
        self.reconnect_s = reconnect_s
        self._cond = threading.Condition()
        self._latest = None          # (frame, t, seq)
        self._seq_out = 0
        self._stop = False
        self._opened = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()
        self._opened.wait(10)

    def _run(self):
        seq = 0
        while not self._stop:
            cap = cv2.VideoCapture(self.url)
            if not cap.isOpened():
                print(f"[video] cannot open {self.url} — retrying")
                time.sleep(self.reconnect_s)
                continue
            self._opened.set()
            while not self._stop:
                ok, frame = cap.read()
                if not ok:
                    print("[video] stream dropped — reconnecting")
                    break
                seq += 1
                with self._cond:
                    self._latest = (frame, time.monotonic(), seq)
                    self._cond.notify_all()
            cap.release()
            time.sleep(self.reconnect_s)

    def isOpened(self):
        return self._opened.is_set()

    def read(self, timeout=10):
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._latest is None or self._latest[2] <= self._seq_out:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False, None, None
                self._cond.wait(min(left, 0.5))   # short slices keep Ctrl+C working on Windows
            frame, t, self._seq_out = self._latest
            return True, frame, t

    def release(self):
        self._stop = True


class FileSource:
    """
    Plays a video file at its real speed, like a live camera would deliver
    it. If detection can't keep up, frames are skipped to stay in sync
    (otherwise a 60 s clip could take 3 minutes and simulated GPS would
    drift away from what's on screen).
    """
    is_live = False

    def __init__(self, path, timestamps=None, realtime=True):
        self.cap = cv2.VideoCapture(str(path))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.timestamps = timestamps        # optional per-frame times (recorded drives)
        self.realtime = realtime
        self.idx = -1
        self._t0 = None
        self._media_t = 0.0

    def isOpened(self):
        return self.cap.isOpened()

    def _time_of(self, i):
        if self.timestamps is not None and i < len(self.timestamps):
            return self.timestamps[i]
        return i / self.fps

    def media_time(self):
        """Current position in the recording (seconds) — the clock replayed GPS follows."""
        return self._media_t

    def read(self):
        while True:
            ok, frame = self.cap.read()
            if not ok:
                return False, None, None
            self.idx += 1
            t = self._time_of(self.idx)
            if not self.realtime:
                break
            if self._t0 is None:
                self._t0 = time.monotonic() - t
            lag = (time.monotonic() - self._t0) - t
            if lag > 0.25:          # behind real time: drop this frame, take the next
                continue
            if lag < 0:
                time.sleep(-lag)    # ahead: wait so playback runs at true speed
            break
        self._media_t = t
        return True, frame, t

    def release(self):
        self.cap.release()


def open_source(spec):
    """'0' / 0 -> webcam, 'http(s)://' or 'rtsp://' -> stream, anything else -> file."""
    if isinstance(spec, int) or (isinstance(spec, str) and spec.isdigit()):
        return WebcamSource(int(spec))
    if isinstance(spec, str) and spec.lower().startswith(("http://", "https://", "rtsp://")):
        return StreamSource(spec)
    return FileSource(spec)
