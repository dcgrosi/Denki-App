"""End-to-End-Tests der HTTP-API (FastAPI TestClient)."""

from __future__ import annotations


def test_health(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["app"] == "Denki"
    assert data["local_only"] is True


def test_chat_roundtrip_lernt_und_erinnert(client):
    first = client.post("/api/chat", json={"message": "Ich heiße Jonas und arbeite bei GroTeck."}).json()
    assert first["reply"]
    assert first["session_id"]
    assert first["stats"]["facts_active"] >= 2

    second = client.post(
        "/api/chat",
        json={"message": "Wie heißt mein Arbeitgeber?", "session_id": first["session_id"]},
    ).json()
    assert "GroTeck" in second["reply"]


def test_facts_patch_confirm_delete(client):
    client.post("/api/chat", json={"message": "Ich wohne in Köln."})
    facts = client.get("/api/facts?status=active").json()["facts"]
    fact = next(f for f in facts if f["key"] == "identitaet:wohnort")

    patched = client.patch(f"/api/facts/{fact['id']}", json={"label": "Wohnt in Ehrenfeld (Köln)."}).json()
    assert patched["fact"]["label"] == "Wohnt in Ehrenfeld (Köln)."

    confirmed = client.post(f"/api/confirm/{fact['id']}").json()
    assert confirmed["ok"] is True

    deleted = client.delete(f"/api/facts/{fact['id']}").json()
    assert deleted["ok"] is True
    remaining = client.get("/api/facts?status=active").json()["facts"]
    assert all(f["id"] != fact["id"] for f in remaining)


def test_forget_endpoint(client):
    client.post("/api/chat", json={"message": "Mein Lieblingskaffee ist Espresso."})
    result = client.post("/api/forget", json={"query": "Kaffee"}).json()
    assert result["ok"] is True


def test_reset_endpoint(client):
    client.post("/api/chat", json={"message": "Ich heiße Tim."})
    assert client.get("/api/stats").json()["facts_active"] >= 1
    client.post("/api/memory/reset")
    assert client.get("/api/stats").json()["facts_active"] == 0


def test_ui_wird_ausgeliefert(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Denki" in response.text
    assert client.get("/static/app.js").status_code == 200
