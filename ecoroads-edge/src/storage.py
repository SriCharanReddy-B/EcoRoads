"""
Local SQLite storage for the edge node.

Schema is deliberately minimal — lat, lon, severity_pct, timestamp,
vehicle_id, synced flag. NO images, NO raw confidence, NO bounding box
coordinates are stored here. Severity is computed once on the edge and
that's the only number kept.

This is the "always works, never fails" write path: every hazard event
gets written here immediately regardless of internet availability.

Two processes use this file at the same time (capture_detect writes,
sync_worker reads + marks synced), so the DB runs in WAL mode with a
busy timeout. Without that, one process would occasionally hit
"database is locked" while the other is mid-write.
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# ECOROADS_EDGE_DB lets the classroom demo use its own throw-away database
DB_PATH = Path(os.environ.get("ECOROADS_EDGE_DB",
                              Path(__file__).resolve().parent.parent / "data" / "local_hazards.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS hazards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    severity_pct REAL NOT NULL,
    synced INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hazards_synced ON hazards(synced);
"""


def get_connection(db_path=DB_PATH):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def log_hazard(conn, vehicle_id, lat, lon, severity_pct, timestamp=None):
    """Called once per pothole event. Fully local, no network needed."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO hazards (vehicle_id, timestamp, lat, lon, severity_pct, synced)
           VALUES (?, ?, ?, ?, ?, 0)""",
        (vehicle_id, ts, lat, lon, severity_pct),
    )
    conn.commit()


def unsynced_rows(conn, limit=100):
    cur = conn.execute(
        "SELECT * FROM hazards WHERE synced = 0 ORDER BY id ASC LIMIT ?", (limit,)
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def mark_synced(conn, row_ids):
    conn.executemany("UPDATE hazards SET synced = 1 WHERE id = ?", [(i,) for i in row_ids])
    conn.commit()


def unsynced_count(conn):
    return conn.execute("SELECT COUNT(*) FROM hazards WHERE synced = 0").fetchone()[0]


if __name__ == "__main__":
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM hazards").fetchone()[0]
    pending = unsynced_count(conn)
    print(f"local_hazards.db ready at {DB_PATH}")
    print(f"  total rows: {total}, pending sync: {pending}")
