"""
CLOUD — storage layer. Two backends, same code everywhere else:

  - SQLite      (default)  one local file — laptops, classroom demos, tests
  - PostgreSQL  (DATABASE_URL set) — the deployed server, e.g. a free Neon
                database behind Render. Needed there because free web hosts
                wipe the container's disk on every restart/redeploy.

Every query in the app goes through `connect()` and is written in SQL
that both databases understand ("?" placeholders, ON CONFLICT ... DO),
so this file is the only place that knows which database is in use.

Environment:
  DATABASE_URL   postgresql://user:pass@host/db?sslmode=require  -> Postgres
  ECOROADS_DB    path of the SQLite file (default ecoroads-cloud/data/ecoroads.db)
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "ecoroads.db"

# Column types differ slightly; everything else is shared.
_TYPES = {
    "sqlite":   {"ID": "INTEGER PRIMARY KEY AUTOINCREMENT", "FLOAT": "REAL"},
    "postgres": {"ID": "BIGSERIAL PRIMARY KEY",             "FLOAT": "DOUBLE PRECISION"},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS municipalities (
    municipality_id TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    center_lat      {FLOAT} NOT NULL,
    center_lon      {FLOAT} NOT NULL,
    radius_m        {FLOAT} NOT NULL,
    created_at      TEXT NOT NULL,
    token_hash      TEXT                 -- sha256 of the municipality's access token
);

-- One row per hazard event reported by an edge node.
-- The UNIQUE constraint makes ingest idempotent: if a sync response is
-- lost and the edge re-sends the same batch, the duplicates are ignored.
CREATE TABLE IF NOT EXISTS hazards (
    id              {ID},
    vehicle_id      TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    lat             {FLOAT} NOT NULL,
    lon             {FLOAT} NOT NULL,
    severity_pct    {FLOAT} NOT NULL,
    municipality_id TEXT NOT NULL REFERENCES municipalities(municipality_id),
    road_status     TEXT NOT NULL,          -- 'public' | 'unverified' (road check unavailable)
    received_at     TEXT NOT NULL,
    UNIQUE (vehicle_id, timestamp, lat, lon)
);
CREATE INDEX IF NOT EXISTS idx_hazards_muni ON hazards(municipality_id);

-- A municipality marks a spot as repaired. Detections at that spot
-- AFTER repaired_at mean the repair failed (or was never done).
CREATE TABLE IF NOT EXISTS repairs (
    id              {ID},
    municipality_id TEXT NOT NULL REFERENCES municipalities(municipality_id),
    lat             {FLOAT} NOT NULL,
    lon             {FLOAT} NOT NULL,
    repaired_at     TEXT NOT NULL,
    note            TEXT
);

-- Cache of OpenStreetMap road checks, keyed by ~11 m grid cell.
CREATE TABLE IF NOT EXISTS road_cache (
    cell_key   TEXT PRIMARY KEY,
    is_public  INTEGER NOT NULL,
    checked_at TEXT NOT NULL
);
"""


def backend():
    return "postgres" if os.environ.get("DATABASE_URL") else "sqlite"


def db_path():
    return Path(os.environ.get("ECOROADS_DB", DEFAULT_DB))


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def schema_sql(kind=None):
    return SCHEMA.format(**_TYPES[kind or backend()])


class _PgConn:
    """Makes a psycopg connection look like sqlite3's for our queries ('?' -> '%s')."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=()):
        return self.raw.execute(sql.replace("?", "%s"), params)

    def executescript(self, script):
        for stmt in (s.strip() for s in script.split(";")):
            if stmt:
                self.raw.execute(stmt)


@contextmanager
def connect():
    """One short-lived connection per operation; commits on success.
    Rows support row["column"] on both backends."""
    if backend() == "postgres":
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=15)
        try:
            yield _PgConn(raw)
            raw.commit()
        finally:
            raw.close()
        return

    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    if backend() == "sqlite":
        db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(schema_sql())
        _migrate(conn)


def _migrate(conn):
    """Bring databases created by older versions up to date."""
    if backend() == "postgres":
        conn.execute("ALTER TABLE municipalities ADD COLUMN IF NOT EXISTS token_hash TEXT")
        return
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(municipalities)")}
    if "token_hash" not in cols:
        conn.execute("ALTER TABLE municipalities ADD COLUMN token_hash TEXT")
