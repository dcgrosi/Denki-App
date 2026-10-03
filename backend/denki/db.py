"""SQLite-Schicht von Denki.

Ein einziges, lokales Datenbankfile – portabel, ohne Server, verschlüsselbar
(bei Bedarf später mit SQLCipher). Alle Schreibzugriffe sind idempotent
gehalten, damit die App auch bei Abstürzen kein kaputtes Gedächtnis hinterlässt.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT    NOT NULL UNIQUE,          -- normierter Fakt-Schlüssel
    category        TEXT    NOT NULL,                 -- identitaet, vorliebe, arbeit, …
    label           TEXT    NOT NULL,                 -- menschenlesbare Aussage
    value           TEXT,                             -- extrahierter Wert
    source_text     TEXT,                             -- Originaläußerung (Beleg)
    confidence      REAL    NOT NULL DEFAULT 0.42,
    status          TEXT    NOT NULL DEFAULT 'active',-- active | superseded | forgotten
    times_learned   INTEGER NOT NULL DEFAULT 1,
    times_recalled  INTEGER NOT NULL DEFAULT 0,
    supersedes      INTEGER,                          -- Vorgänger-Fakt bei Korrektur
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    last_recalled_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    title      TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role       TEXT    NOT NULL,                      -- user | assistant | system
    content    TEXT    NOT NULL,
    meta       TEXT,                                  -- JSON: recalled, learned, brain …
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS topics (
    topic        TEXT PRIMARY KEY,
    hits         INTEGER NOT NULL DEFAULT 1,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,                         -- extracted | reinforced | corrected | forgotten | confirmed
    fact_id    INTEGER,
    detail     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prefs (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    """Pro Thread eine Verbindung (SQLite + Threads = sonst Ärger)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.ensure_dirs()
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO prefs(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO NOTHING",
            ("installed_at", now_iso(), now_iso()),
        )


# ---------------------------------------------------------------------------
# Kleine Helfer
# ---------------------------------------------------------------------------

def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def set_pref(key: str, value: Any) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO prefs(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now_iso()),
        )


def get_pref(key: str, default: Any = None) -> Any:
    with db() as conn:
        row = conn.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return row["value"]


def all_prefs() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM prefs ORDER BY key").fetchall()
    out: dict[str, Any] = {}
    for row in rows:
        try:
            out[row["key"]] = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            out[row["key"]] = row["value"]
    return out
