"""Konversationen: Sitzungen und Nachrichten (lokaler Verlauf)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from . import db


def create_session(title: str = "Neues Gespräch") -> dict[str, Any]:
    session_id = uuid.uuid4().hex[:12]
    now = db.now_iso()
    with db.db() as conn:
        conn.execute(
            "INSERT INTO sessions(id, title, created_at, updated_at) VALUES(?,?,?,?)",
            (session_id, title, now, now),
        )
    return {"id": session_id, "title": title, "created_at": now, "updated_at": now}


def ensure_session(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return create_session()
    with db.db() as conn:
        row = db.row_to_dict(conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
    return row or create_session()


def list_sessions(limit: int = 30) -> list[dict[str, Any]]:
    with db.db() as conn:
        rows = db.rows_to_dicts(
            conn.execute(
                """SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS message_count
                   FROM sessions s ORDER BY s.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        )
    return rows


def add_message(session_id: str, role: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    now = db.now_iso()
    with db.db() as conn:
        cur = conn.execute(
            "INSERT INTO messages(session_id, role, content, meta, created_at) VALUES(?,?,?,?,?)",
            (session_id, role, content, json.dumps(meta or {}, ensure_ascii=False), now),
        )
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        return {
            "id": cur.lastrowid,
            "session_id": session_id,
            "role": role,
            "content": content,
            "meta": meta or {},
            "created_at": now,
        }


def history(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with db.db() as conn:
        rows = db.rows_to_dicts(
            conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        )
    for row in rows:
        try:
            row["meta"] = json.loads(row.get("meta") or "{}")
        except json.JSONDecodeError:
            row["meta"] = {}
    return list(reversed(rows))


def recent_turns(session_id: str, limit: int = 8) -> list[dict[str, str]]:
    """Letzte Nachrichten als einfacher Kontext für ein LLM-Backend."""
    msgs = history(session_id, limit=limit)[-limit:]
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


def rename_session(session_id: str, title: str) -> None:
    with db.db() as conn:
        conn.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                     (title[:80], db.now_iso(), session_id))


def delete_session(session_id: str) -> None:
    with db.db() as conn:
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
