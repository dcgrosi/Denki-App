"""Tests für Intent-Erkennung und die Mock-KI."""

from __future__ import annotations


def test_intent_erkennung():
    from denki.intents import classify

    assert classify("Hallo Denki!").name == "greeting"
    assert classify("Vergiss bitte meinen Arbeitgeber").name == "forget"
    assert classify("Was weißt du über mich?").name in {"ask_memory", "list_memories"}
    assert classify("Wer hat dich erfunden?").name == "ask_identity"
    assert classify("Ich heiße Mara und arbeite bei Siemens.").name == "statement"
    assert classify("genau").name == "confirm"
    assert classify("nein, das stimmt nicht").name == "deny"


def test_mock_brain_lernt_und_antwortet(fresh_db):
    from denki.brain import MockBrain

    brain = MockBrain()
    result = brain.chat("Hallo! Ich heiße Dennis und arbeite bei GroTeck.")
    assert "Dennis" in result.text or "GroTeck" in result.text
    assert result.brain == "mock"

    facts = fresh_db.all_facts("active")
    assert any(f["key"] == "identitaet:name" for f in facts)


def test_mock_brain_erinnert_sich(fresh_db):
    from denki.brain import MockBrain

    brain = MockBrain()
    brain.chat("Ich wohne in Köln.")
    answer = brain.chat("Wo wohne ich nochmal?")
    assert "Köln" in answer.text
    assert answer.recalled


def test_mock_brain_vergisst_auf_zuruf(fresh_db):
    from denki.brain import MockBrain

    brain = MockBrain()
    brain.chat("Ich mag Ananas auf Pizza.")
    result = brain.chat("Vergiss bitte, dass ich Ananas auf Pizza mag.")
    assert result.intent.name == "forget"
    assert not [f for f in fresh_db.all_facts("active") if "Ananas" in f["label"]]


def test_profil_anrede_wird_angewendet(fresh_db):
    from denki.brain import MockBrain

    brain = MockBrain()
    brain.chat("Sieze mich bitte ab jetzt.")
    answer = brain.chat("Hallo!")
    assert "Ihnen" in answer.text or "Sie" in answer.text


def test_backend_factory_waehlt_mock(monkeypatch):
    from denki import config
    from denki.brain import MockBrain, get_brain

    monkeypatch.setattr(config, "BRAIN_BACKEND", "mock")
    assert isinstance(get_brain(), MockBrain)
