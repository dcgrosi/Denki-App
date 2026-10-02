"""Tests für Denkis Gedächtnis: Extraktion, Verstärkung, Korrektur, Vergessen, Abruf."""

from __future__ import annotations


def test_extrahiert_name_und_arbeit(fresh_db):
    result = fresh_db.learn("Ich heiße Dennis Großer und arbeite bei GroTeck.")
    kinds = {e.kind for e in result.events}
    assert "extracted" in kinds

    facts = fresh_db.all_facts("active")
    keys = {f["key"] for f in facts}
    assert "identitaet:name" in keys
    assert "arbeit:arbeitgeber" in keys
    assert any(f["value"] == "Dennis Großer" for f in facts)
    assert any("GroTeck" in (f["value"] or "") for f in facts)


def test_wiederholung_verstaerkt_vertrauen(fresh_db):
    fresh_db.learn("Ich heiße Anna.")
    first = [f for f in fresh_db.all_facts("active") if f["key"] == "identitaet:name"][0]

    result = fresh_db.learn("Ich heiße Anna.")
    second = [f for f in fresh_db.all_facts("active") if f["key"] == "identitaet:name"][0]

    assert second["times_learned"] == first["times_learned"] + 1
    assert second["confidence"] > first["confidence"]
    assert any(e.kind == "reinforced" for e in result.events)
    # Es darf kein zweiter Fakt mit gleichem Schlüssel entstehen
    assert len([f for f in fresh_db.all_facts("active") if f["key"] == "identitaet:name"]) == 1


def test_widerspruch_ersetzt_alten_fakt(fresh_db):
    fresh_db.learn("Ich wohne in Berlin.")
    fresh_db.learn("Ich wohne in Köln.")

    facts = fresh_db.all_facts()
    active = [f for f in facts if f["status"] == "active"]
    superseded = [f for f in facts if f["status"] == "superseded"]

    assert len(active) == 1
    assert active[0]["value"] == "Köln"
    assert len(superseded) == 1
    assert superseded[0]["value"] == "Berlin"
    assert active[0]["supersedes"] == superseded[0]["id"]


def test_vergiss_befehl_loescht(fresh_db):
    fresh_db.learn("Ich arbeite bei GroTeck und mag Kaffee.")
    assert fresh_db.search_facts("GroTeck")

    events = fresh_db.forget_by_query("Vergiss meinen Arbeitgeber")
    assert events, "Es sollte mindestens ein Fakt vergessen werden"

    remaining = fresh_db.all_facts("active")
    assert all("GroTeck" not in (f["label"] + (f["value"] or "")) for f in remaining)


def test_vergiss_alles(fresh_db):
    fresh_db.learn("Ich heiße Tim und mag Tee.")
    fresh_db.forget_by_query("Vergiss bitte alles")
    assert fresh_db.all_facts("active") == []
    assert fresh_db.stats()["facts_forgotten"] >= 1


def test_recall_liefert_passende_erinnerung(fresh_db):
    fresh_db.learn("Mein Lieblingseditor ist VS Code.")
    hits = fresh_db.recall("Welchen Editor benutze ich?")
    assert hits
    assert any("VS Code" in (h["value"] or "") or "VS Code" in h["label"] for h in hits)
    assert hits[0]["score"] > 0


def test_recall_zaehlt_und_verstaerkt(fresh_db):
    fresh_db.learn("Ich nutze Python.")
    fact = [f for f in fresh_db.all_facts("active") if "python" in f["label"].lower()][0]
    assert fact["times_recalled"] == 0

    fresh_db.recall("Arbeitest du mit Python?")
    after = [f for f in fresh_db.all_facts("active") if f["id"] == fact["id"]][0]
    assert after["times_recalled"] == 1
    assert after["last_recalled_at"]


def test_profil_vorlieben_werden_gelernt(fresh_db):
    fresh_db.learn("Sieze mich bitte und antworte kurz.")
    labels = " ".join(f["label"] for f in fresh_db.all_facts("active"))
    assert "Anrede" in labels
    assert "Antwortstil" in labels


def test_lern_ereignisse_werden_protokolliert(fresh_db):
    fresh_db.learn("Ich heiße Lea.")
    events = fresh_db.stats()["recent_events"]
    assert events
    assert events[0]["kind"] in {"extracted", "reinforced"}


def test_themen_statistik(fresh_db):
    fresh_db.learn("Ich entwickle eine Desktop-App mit Python und FastAPI.")
    topics = {t["topic"] for t in fresh_db.stats()["top_topics"]}
    assert topics
