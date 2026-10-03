"""Zentrale Konfiguration für Denki.

Alles ist darauf ausgelegt, vollständig lokal auf dem Rechner des Nutzers zu
laufen (Windows-Desktop-App). Es werden keine Daten an externe Dienste gesendet,
solange nicht ausdrücklich ein Backend (z. B. Ollama) konfiguriert ist – und auch
dann bleibt Ollama ein lokaler Dienst.
"""

from __future__ import annotations

import os
from pathlib import Path

# Projektverzeichnis (…/Denki-App): backend/denki/config.py -> drei Ebenen hoch
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Lokale Daten (SQLite-Gedächtnis). Kann per Umgebungsvariable verschoben werden,
# z. B. nach %APPDATA%\Denki bei einer echten Windows-Installation.
DATA_DIR = Path(os.environ.get("DENKI_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("DENKI_DB", DATA_DIR / "denki.sqlite3"))

# Statische Dateien (Web-UI)
FRONTEND_DIR = BASE_DIR / "frontend" / "static"

# Standard-Identität
APP_NAME = "Denki"
APP_TAGLINE = "lokale, mitlernende KI für Windows"
APP_VERSION = "0.1.0-prototype"
AUTHOR = "Dennis C. Großer · GroTeck"

# ---------------------------------------------------------------------------
# Gedächtnis-Parameter (das „Mitlernen“)
# ---------------------------------------------------------------------------

# Wie viele Erinnerungen maximal in den Kontext einer Antwort wandern
RECALL_LIMIT = 6
# Ab welcher Relevanz eine Erinnerung als „passend“ gilt (0..1)
RECALL_MIN_SCORE = 0.17

# Start-Vertrauen für eine frisch gelernte Tatsache
CONFIDENCE_NEW = 0.42
# Vertrauen, wenn dieselbe Tatsache erneut geäußert wird (Verstärkung)
CONFIDENCE_REINFORCED = 0.20
# Vertrauen, wenn der Nutzer eine Erinnerung ausdrücklich bestätigt
CONFIDENCE_CONFIRM = 0.18
# Abzug bei Widerspruch/Korrektur
CONFIDENCE_PENALTY = 0.35
# Abzug pro Tag ohne Nutzung (sanftes Vergessen, erst beim Zugriff berechnet)
CONFIDENCE_DECAY_PER_DAY = 0.004
# Harte Grenzen
CONFIDENCE_MIN = 0.05
CONFIDENCE_MAX = 0.97

# ---------------------------------------------------------------------------
# KI-Backend
# ---------------------------------------------------------------------------
# "auto"   -> Ollama nutzen, wenn lokal verfügbar, sonst MockBrain
# "mock"   -> immer die eingebaute, deterministische Demo-KI
# "ollama" -> immer Ollama (Fehler, wenn nicht verfügbar)
BRAIN_BACKEND = os.environ.get("DENKI_BRAIN", "auto")
OLLAMA_URL = os.environ.get("DENKI_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("DENKI_OLLAMA_MODEL", "llama3.1")
OLLAMA_TIMEOUT = float(os.environ.get("DENKI_OLLAMA_TIMEOUT", "0.6"))

# Server (Standard: nur dieser Rechner; 0.0.0.0 öffnet Denki fürs Netzwerk)
HOST = os.environ.get("DENKI_HOST") or "127.0.0.1"
PORT = int(os.environ.get("DENKI_PORT", "8000"))


def ensure_dirs() -> None:
    """Legt die Datenverzeichnisse an (idempotent)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
