"""
Camera + accelerometer severity fusion.

Two independent signals describe the same pothole:
  - camera   : how big / how confidently it LOOKS   (severity.py)
  - jolt     : how hard the vehicle actually HIT it (accel_reader.py)

They happen at different moments. The camera sees the pothole a few
metres ahead; the wheel reaches it  lookahead_m / speed  seconds later
(e.g. 4 m at 30 km/h = 8.3 m/s -> ~0.5 s). So for a camera event we
search for a jolt in a window that starts when the pothole was first
seen and ends shortly after the expected wheel-hit time.

Outcomes:
  - jolt found     -> blend: 60% camera + 40% jolt-based severity
  - no jolt found  -> keep the camera severity unchanged. The driver may
                      have steered around it — that's not evidence the
                      pothole is small.
  - no sensor      -> camera severity unchanged (Week 1 behaviour).

Only the final number leaves the device, so the cloud payload and API
are unchanged by this feature.
"""

JOLT_MIN_G = 0.3     # below this is normal road vibration -> 0 %
JOLT_MAX_G = 1.5     # at or above this is a severe hit     -> 100 %
CAMERA_WEIGHT = 0.6
WINDOW_SLACK_S = 0.5


def jolt_to_severity_pct(jolt_g, min_g=JOLT_MIN_G, max_g=JOLT_MAX_G):
    pct = (jolt_g - min_g) / (max_g - min_g) * 100
    return max(0.0, min(100.0, pct))


def jolt_window(event, lookahead_m, max_wait_s):
    """(start, end) monotonic window in which the wheel should hit this pothole."""
    speed = max(event.speed_mps, 1.0)                 # avoid /0 when stopped
    delay = min(lookahead_m / speed + WINDOW_SLACK_S, max_wait_s)
    return event.first_t, event.last_t + delay


def fuse(event, accel, lookahead_m, max_wait_s, min_g=JOLT_MIN_G, max_g=JOLT_MAX_G):
    """Returns (final_severity_pct, jolt_g_or_None).

    min_g / max_g let you calibrate per mounting: an Arduino bolted to the
    body feels jolts sharply; a phone in a windscreen holder feels them
    damped (or exaggerated by a wobbly arm) — see TEST_DRIVE_CHECKLIST.md.
    """
    if accel is None:
        return event.severity_pct, None
    start, end = jolt_window(event, lookahead_m, max_wait_s)
    jolt = accel.peak_jolt(start, end)
    if jolt is None or jolt < min_g:
        return event.severity_pct, jolt
    fused = CAMERA_WEIGHT * event.severity_pct + (1 - CAMERA_WEIGHT) * jolt_to_severity_pct(jolt, min_g, max_g)
    return round(min(fused, 100.0), 1), jolt
