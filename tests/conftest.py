"""Pytest-Fixtures: jedes Testmodul bekommt eine frische, isolierte Denki-Datenbank."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Setzt eine leere SQLite-DB auf und liefert das `memory`-Modul zurück."""
    monkeypatch.setenv("DENKI_DB", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("DENKI_DATA_DIR", str(tmp_path))

    for name in [m for m in sys.modules if m == "denki" or m.startswith("denki.")]:
        del sys.modules[name]

    from denki import config, db, memory  # noqa: WPS433 (Import nach Env-Setup)

    assert config.DB_PATH == tmp_path / "test.sqlite3"
    db.init_db()
    memory.reset_memory()
    return memory


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """FastAPI-Testclient gegen eine temporäre Datenbank."""
    monkeypatch.setenv("DENKI_DB", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("DENKI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DENKI_BRAIN", "mock")

    for name in [m for m in sys.modules if m == "denki" or m.startswith("denki.")]:
        del sys.modules[name]

    from fastapi.testclient import TestClient  # noqa: WPS433
    from denki.main import app  # noqa: WPS433

    with TestClient(app) as test_client:
        yield test_client
