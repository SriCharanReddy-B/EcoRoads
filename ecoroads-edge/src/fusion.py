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


def rejection_reason(event, jolt_g, min_frames=3, confirm_below_conf=0.7,
                     jolt_min_g=JOLT_MIN_G, min_speed_mps=3.0):
    """
    Decide whether a closed camera event is too weak to log. Returns None to keep it,
    or a short reason string to drop it. Two cheap checks against look-alikes such
    as tree shadows, wet patches and dark repairs:

    1. FLICKER: a real pothole stays in view for a second or more (15+ frames at
       15 fps). Something detected in only 1-2 frames is usually noise.

    2. NO BUMP: shadows and stains are flat. If the vehicle was MOVING, the
       accelerometer was WORKING (it returned a reading), the camera was NOT very
       sure (confidence below `confirm_below_conf`) and the wheel felt nothing
       (jolt below jolt_min_g), we drop it. A confident detection is kept even
       without a jolt, because the driver may have steered around a real pothole.
       Standing still (desk tests) or with no motion data, rule 2 is skipped.
    """
    if event.frames < min_frames:
        return f"seen in only {event.frames} frame(s)"
    moving = event.speed_mps >= min_speed_mps
    sensor_reading = jolt_g is not None
    if (confirm_below_conf > 0 and moving and sensor_reading
            and event.max_conf < confirm_below_conf and jolt_g < jolt_min_g):
        return (f"no bump felt ({jolt_g:.2f} g) and camera only {event.max_conf:.2f} sure "
                f"- likely a shadow or stain")
    return None


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
