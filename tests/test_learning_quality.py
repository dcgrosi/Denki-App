"""Qualitäts-Tests für die Extraktion und das Gedächtnis-Verhalten.

Diese Tests sichern die Feinheiten ab, die Denki glaubwürdig machen:
saubere Werte, gezieltes Vergessen, Korrekturen mit Historie und Profilwirkung.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Extraktions-Qualität
# ---------------------------------------------------------------------------


def test_mehrfachaussage_liefert_beide_fakten(fresh_db):
    """„Ich heiße X und arbeite bei Y“ muss zwei Fakten ergeben."""
    fresh_db.learn("Ich heiße Anna Weber und arbeite bei Siemens.")
    facts = {f["key"]: f["value"] for f in fresh_db.all_facts("active")}
    assert facts.get("identitaet:name") == "Anna Weber"
    assert facts.get("arbeit:arbeitgeber") == "Siemens"


def test_ortsangabe_landet_nicht_im_firmennamen(fresh_db):
    fresh_db.learn("Ich arbeite als Berater bei Siemens in München.")
    facts = {f["key"]: f["value"] for f in fresh_db.all_facts("active")}
    assert facts.get("arbeit:arbeitgeber") == "Siemens"


def test_rolle_und_arbeitgeber_aus_einem_satz(fresh_db):
    fresh_db.learn("Ich bin Softwareentwickler bei GroTeck.")
    keys = {f["key"] for f in fresh_db.all_facts("active")}
    assert "arbeit:rolle" in keys
    assert "arbeit:arbeitgeber" in keys


def test_satzteil_lernt_system_und_hardware(fresh_db):
    """Auch der zweite Satzteil ohne Subjekt muss gelernt werden."""
    fresh_db.learn("Ich wohne in Köln und nutze Windows 11.")
    facts = {f["key"]: f["value"] for f in fresh_db.all_facts("active")}
    assert facts.get("identitaet:wohnort") == "Köln"
    assert facts.get("umgebung:system") == "Windows 11"

    fresh_db.learn("Ich arbeite bei GroTeck und habe 32 GB RAM.")
    labels = " ".join(f["label"] for f in fresh_db.all_facts("active"))
    assert "32 GB RAM" in labels


def test_betriebssystem_wird_umgebung_nicht_werkzeug(fresh_db):
    fresh_db.learn("Ich nutze Windows 11.")
    facts = fresh_db.all_facts("active")
    assert len(facts) == 1
    assert facts[0]["category"] == "umgebung"
    assert facts[0]["value"] == "Windows 11"


def test_initial_im_namen_bleibt_erhalten(fresh_db):
    fresh_db.learn("Ich heiße Dennis C. Großer.")
    facts = {f["key"]: f["value"] for f in fresh_db.all_facts("active")}
    assert facts.get("identitaet:name") == "Dennis C. Großer"


def test_verneinung_wird_abneigung_nicht_vorliebe(fresh_db):
    fresh_db.learn("Ich mag keinen Kaffee.")
    facts = fresh_db.all_facts("active")
    assert len(facts) == 1
    assert facts[0]["category"] == "abneigungen"
    assert facts[0]["value"] == "Kaffee"


def test_haustier_mit_name(fresh_db):
    fresh_db.learn("Ich habe eine Katze namens Mimi.")
    facts = fresh_db.all_facts("active")
    assert any(f["value"] == "Mimi" and "Katze" in f["label"] for f in facts)


def test_termin_wird_erkannt(fresh_db):
    fresh_db.learn("Ich habe am Freitag um 10 Uhr einen Zahnarzttermin.")
    facts = fresh_db.all_facts("active")
    assert any(f["category"] == "termine" and "Zahnarzttermin" in f["label"] for f in facts)


# ---------------------------------------------------------------------------
# Vergessen
# ---------------------------------------------------------------------------


def test_vergiss_trifft_nur_den_gemeinten_fakt(fresh_db):
    fresh_db.learn("Mein Lieblingseditor ist VS Code.")
    fresh_db.learn("Mein Lieblingskaffee ist Espresso.")

    fresh_db.forget_by_query("Vergiss meinen Lieblingseditor")
    remaining = {f["value"] for f in fresh_db.all_facts("active")}

    assert "Espresso" in remaining, "Der Lieblingskaffee darf nicht mitgelöscht werden"
    assert "VS Code" not in remaining


def test_vergiss_ueber_thema_loescht_alle_treffer(fresh_db):
    fresh_db.learn("Mein Lieblingskaffee ist Espresso.")
    fresh_db.learn("Ich mag keinen Kaffee.")
    fresh_db.learn("Ich wohne in Köln.")

    fresh_db.forget_by_query("Vergiss alles über Kaffee")
    remaining = [f["label"] for f in fresh_db.all_facts("active")]

    assert remaining == ["Wohnt in Köln."]


def test_kein_unbeabsichtigtes_vergessen_durch_verneinung(fresh_db):
    """„Ich mag keinen Kaffee“ darf nicht als Löschbefehl verstanden werden."""
    fresh_db.learn("Ich heiße Tim.")
    fresh_db.learn("Ich mag keinen Kaffee.")
    assert fresh_db.all_facts("active"), "Fakten müssen erhalten bleiben"


# ---------------------------------------------------------------------------
# Abruf
# ---------------------------------------------------------------------------


def test_abruf_ueber_synonym(fresh_db):
    fresh_db.learn("Ich arbeite bei GroTeck.")
    hits = fresh_db.recall("Wie heißt mein Arbeitgeber?")
    assert hits and "GroTeck" in hits[0]["label"]


def test_abruf_bei_kurzer_frage(fresh_db):
    fresh_db.learn("Ich wohne in Köln.")
    fresh_db.learn("Ich mag Kätzchen.")
    hits = fresh_db.recall("Wo wohne ich?")
    assert hits and "Köln" in hits[0]["label"]


def test_negation_lenkt_abruf(fresh_db):
    fresh_db.learn("Ich mag keinen Kaffee.")
    fresh_db.learn("Ich mag Kätzchen.")
    hits = fresh_db.recall("Was mag ich nicht?")
    assert hits and "Kaffee" in hits[0]["label"]


def test_spezifische_frage_schlaegt_allgemeine(fresh_db):
    fresh_db.learn("Ich heiße Jonas.")
    fresh_db.learn("Ich arbeite bei GroTeck.")
    hits = fresh_db.recall("Kennst du meinen Arbeitgeber?")
    assert hits and "GroTeck" in hits[0]["label"]


# ---------------------------------------------------------------------------
# Profil & Antwortverhalten
# ---------------------------------------------------------------------------


def test_siezen_aendert_antwort(fresh_db):
    from denki.brain import MockBrain

    brain = MockBrain()
    brain.chat("Sieze mich bitte.")
    answer = brain.chat("Hallo!")
    assert "Sie" in answer.text or "Ihnen" in answer.text
    assert " über dich" not in answer.text


def test_duzen_macht_siezen_rueckgaengig(fresh_db):
    from denki.brain import MockBrain

    brain = MockBrain()
    brain.chat("Sieze mich bitte.")
    brain.chat("Duz mich wieder.")
    facts = {f["key"]: f["value"] for f in fresh_db.all_facts("active")}
    assert facts.get("profil:anrede", "").lower() == "du"


def test_korrektur_historie_bleibt_sichtbar(fresh_db):
    fresh_db.learn("Ich wohne in Berlin.")
    fresh_db.learn("Ich wohne in Hamburg.")

    all_facts = fresh_db.all_facts("all")
    assert len(all_facts) == 2
    assert {f["status"] for f in all_facts} == {"active", "superseded"}


def test_wiederholung_zaehlt_hoch(fresh_db):
    for _ in range(3):
        fresh_db.learn("Ich lerne gerade Rust.")
    fact = fresh_db.all_facts("active")[0]
    assert fact["times_learned"] == 3
    assert fact["confidence"] > 0.7


def test_emoji_wunsch_wird_profil_nicht_ziel(fresh_db):
    fresh_db.learn("Ich will keine Emojis.")
    facts = fresh_db.all_facts("active")
    assert len(facts) == 1
    assert facts[0]["key"] == "profil:emojis"


def test_spitzname_erkannt(fresh_db):
    fresh_db.learn("Nenn mich einfach Denny.")
    facts = {f["key"]: f["value"] for f in fresh_db.all_facts("active")}
    assert facts.get("identitaet:spitzname") == "Denny"


def test_negierte_anrede_wird_umgedreht(fresh_db):
    fresh_db.learn("Bitte siezen Sie mich nicht, duzen ist besser.")
    facts = {f["key"]: f["value"] for f in fresh_db.all_facts("active")}
    assert facts.get("profil:anrede", "").lower() == "du"


def test_reset_loescht_alles(fresh_db):
    fresh_db.learn("Ich heiße Tim und wohne in Köln.")
    assert fresh_db.stats()["facts_active"] >= 2
    fresh_db.reset_memory()
    stats = fresh_db.stats()
    assert stats["facts_active"] == 0
    assert stats["messages_total"] == 0
