"""Denki-Backend (FastAPI).

Start:  python run.py           ->  http://127.0.0.1:8000
Alles läuft lokal; die Web-UI wird vom selben Prozess ausgeliefert, damit es
keine CORS-Probleme gibt und relative URLs funktionieren.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, conversation, db, memory
from .brain import MockBrain, OllamaBrain, get_brain
from .intents import INTENTS

db.init_db()

app = FastAPI(
    title=f"{config.APP_NAME} API",
    description=f"{config.APP_NAME} – {config.APP_TAGLINE}. Erfunden von {config.AUTHOR}.",
    version=config.APP_VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# Für lokale Entwicklung (z. B. wenn die UI aus einem anderen Dev-Server kommt)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Modelle
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=0, max_length=8000)
    session_id: str | None = None


class FactUpdate(BaseModel):
    label: str | None = None
    value: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class LearnRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)


class ForgetRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


class PrefRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    value: Any = None


# ---------------------------------------------------------------------------
# Status & Chat
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    ollama_ok, models = OllamaBrain.available()
    brain = get_brain()
    return {
        "status": "ok",
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "tagline": config.APP_TAGLINE,
        "author": config.AUTHOR,
        "brain": brain.name,
        "brain_model": getattr(brain, "model", "") or config.OLLAMA_MODEL,
        "brain_backend_setting": config.BRAIN_BACKEND,
        "ollama_available": ollama_ok,
        "ollama_models": models[:10],
        "db_path": str(config.DB_PATH),
        "local_only": True,
        "server_time": db.now_iso(),
    }


@app.post("/api/chat")
def chat(payload: ChatRequest) -> JSONResponse:
    started = time.perf_counter()
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Nachricht ist leer.")

    session = conversation.ensure_session(payload.session_id)
    conversation.add_message(session["id"], "user", text)

    brain = get_brain()
    result = brain.chat(text)

    # Antwort als Überschrift der Sitzung übernehmen (erste Nachricht)
    if session.get("title", "").startswith("Neues Gespräch"):
        conversation.rename_session(session["id"], text[:60] + ("…" if len(text) > 60 else ""))

    meta = {
        "brain": result.brain,
        "model": result.model,
        "intent": result.intent.to_dict() if result.intent else None,
        "learning": result.meta.get("learning", {}),
        "recalled": [{"id": f["id"], "label": f["label"], "score": f.get("score")} for f in result.recalled],
        "note": result.meta.get("note"),
        "ollama_error": result.meta.get("ollama_error"),
    }
    message = conversation.add_message(session["id"], "assistant", result.text, meta)

    return JSONResponse(
        {
            "reply": result.text,
            "message": message,
            "session_id": session["id"],
            "brain": result.brain,
            "model": result.model,
            "intent": meta["intent"],
            "recalled": [
                {
                    "id": f["id"],
                    "label": f["label"],
                    "value": f.get("value"),
                    "category": f.get("category"),
                    "category_label": memory.CATEGORY_LABELS.get(f.get("category"), f.get("category")),
                    "confidence": round(float(f.get("confidence") or 0), 3),
                    "score": round(float(f.get("score") or 0), 3),
                    "times_learned": f.get("times_learned"),
                }
                for f in result.recalled
            ],
            "learning": meta["learning"],
            "stats": memory.stats(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    )


# ---------------------------------------------------------------------------
# Gedächtnis
# ---------------------------------------------------------------------------


@app.get("/api/facts")
def facts(status: str = "active", q: str | None = None) -> dict[str, Any]:
    items = memory.search_facts(q) if q else memory.all_facts(status=status)
    return {
        "count": len(items),
        "facts": [
            {
                **f,
                "category_label": memory.CATEGORY_LABELS.get(f.get("category"), f.get("category")),
            }
            for f in items
        ],
        "categories": memory.CATEGORY_LABELS,
    }


@app.get("/api/facts/{fact_id}")
def get_fact(fact_id: int) -> dict[str, Any]:
    with db.db() as conn:
        row = db.row_to_dict(conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone())
    if not row:
        raise HTTPException(status_code=404, detail="Fakt nicht gefunden")
    return row


@app.patch("/api/facts/{fact_id}")
def patch_fact(fact_id: int, payload: FactUpdate) -> dict[str, Any]:
    updated = memory.update_fact(
        fact_id, label=payload.label, value=payload.value, confidence=payload.confidence
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Fakt nicht gefunden")
    return {"ok": True, "fact": updated, "stats": memory.stats()}


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int) -> dict[str, Any]:
    memory.delete_fact(fact_id)
    return {"ok": True, "stats": memory.stats()}


@app.post("/api/confirm/{fact_id}")
def confirm_fact(fact_id: int) -> dict[str, Any]:
    events = memory.confirm(fact_id)
    if not events:
        raise HTTPException(status_code=404, detail="Fakt nicht gefunden")
    return {"ok": True, "events": [e.to_dict() for e in events], "stats": memory.stats()}


@app.post("/api/confirm")
def confirm_all() -> dict[str, Any]:
    events = memory.confirm(all_facts=True)
    return {"ok": True, "count": len(events), "stats": memory.stats()}


@app.post("/api/learn")
def learn(payload: LearnRequest) -> dict[str, Any]:
    result = memory.learn(payload.text, source="manual")
    return {"ok": True, "learning": result.to_dict(), "stats": memory.stats()}


@app.post("/api/forget")
def forget(payload: ForgetRequest) -> dict[str, Any]:
    events = memory.forget_by_query(payload.query)
    return {
        "ok": True,
        "count": len(events),
        "events": [e.to_dict() for e in events],
        "stats": memory.stats(),
    }


@app.post("/api/memory/reset")
def reset_memory() -> dict[str, Any]:
    memory.reset_memory()
    return {"ok": True, "stats": memory.stats()}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    return memory.stats()


@app.get("/api/events")
def events(limit: int = 40) -> dict[str, Any]:
    limit = max(1, min(200, limit))
    with db.db() as conn:
        rows = db.rows_to_dicts(
            conn.execute(
                """SELECT le.*, f.label FROM learning_events le
                   LEFT JOIN facts f ON f.id=le.fact_id
                   ORDER BY le.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        )
    return {"count": len(rows), "events": rows}


# ---------------------------------------------------------------------------
# Sitzungen & Einstellungen
# ---------------------------------------------------------------------------


@app.get("/api/sessions")
def sessions() -> dict[str, Any]:
    return {"sessions": conversation.list_sessions()}


@app.post("/api/sessions")
def new_session() -> dict[str, Any]:
    return conversation.create_session()


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: str) -> dict[str, Any]:
    return {"session_id": session_id, "messages": conversation.history(session_id)}


@app.delete("/api/sessions/{session_id}")
def remove_session(session_id: str) -> dict[str, Any]:
    conversation.delete_session(session_id)
    return {"ok": True}


@app.get("/api/prefs")
def prefs() -> dict[str, Any]:
    return {"prefs": db.all_prefs(), "intents": list(INTENTS)}


@app.put("/api/prefs")
def put_pref(payload: PrefRequest) -> dict[str, Any]:
    db.set_pref(payload.key, payload.value)
    return {"ok": True, "prefs": db.all_prefs()}


# ---------------------------------------------------------------------------
# Frontend (statische Dateien,relative Pfade -> funktioniert hinter Proxys)
# ---------------------------------------------------------------------------

if config.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(config.FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(config.FRONTEND_DIR / "index.html"))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        icon = config.FRONTEND_DIR / "favicon.svg"
        if icon.exists():
            return FileResponse(str(icon), media_type="image/svg+xml")
        return JSONResponse({"app": config.APP_NAME}, status_code=200)
else:  # pragma: no cover
    @app.get("/", include_in_schema=False)
    def index_missing() -> JSONResponse:
        return JSONResponse({"hint": "frontend/static fehlt – API läuft unter /api/docs"})
