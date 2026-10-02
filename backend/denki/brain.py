"""Denkis „Gehirn“ – austauschbare Antwort-Erzeugung.

Der Prototyp nutzt ein **MockBrain**: deterministisch, offline, aber bereits
voll an das Gedächtnis angebunden (Erinnern, Lernen, Korrigieren, Profil).
Sobald lokal Ollama läuft, übernimmt `OllamaBrain` automatisch dieselbe
Schnittstelle – dann mit echter Inferenz auf dem eigenen Rechner.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import config, memory
from .intents import Intent, classify, greeting_for_now
from .textutil import keywords, normalize

# ---------------------------------------------------------------------------
# Schnittstelle
# ---------------------------------------------------------------------------


@dataclass
class BrainResult:
    text: str
    recalled: list[dict[str, Any]] = field(default_factory=list)
    intent: Intent | None = None
    brain: str = "mock"
    model: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "recalled": [_slim(f) for f in self.recalled],
            "intent": self.intent.to_dict() if self.intent else None,
            "brain": self.brain,
            "model": self.model,
            "meta": self.meta,
        }


def _slim(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": fact["id"],
        "label": fact["label"],
        "value": fact.get("value"),
        "category": fact.get("category"),
        "category_label": memory.CATEGORY_LABELS.get(fact.get("category"), fact.get("category")),
        "confidence": fact.get("confidence"),
        "score": fact.get("score"),
        "times_learned": fact.get("times_learned"),
        "times_recalled": fact.get("times_recalled"),
    }


class Brain:
    name = "base"
    model = ""

    def reply(
        self,
        user_text: str,
        context: list[dict[str, Any]],
        intent: Intent,
        learning: Any | None = None,
    ) -> BrainResult:
        raise NotImplementedError

    def chat(self, user_text: str) -> BrainResult:
        """Kompletter Denki-Zyklus – alles lokal, in dieser Reihenfolge:

        1. Intent bestimmen
        2. Vergessen ausführen (falls gewünscht)
        3. Gedächtnis-Abruf für den Kontext
        4. **Lernen** aus der neuen Äußerung (extrahieren/verstärken/korrigieren)
        5. Antwort erzeugen (Mock oder lokales LLM) und Profil-Vorlieben anwenden
        """
        intent = classify(user_text)
        memory.apply_decay()

        forgotten: list[Any] = []
        if intent.name == "forget":
            forgotten = memory.forget_by_query(user_text)
            learning = memory.LearningResult(events=forgotten, topics=keywords(user_text, limit=5))
        else:
            learning = memory.learn(user_text, source="user")

        recalled = memory.recall(user_text)
        result = self.reply(user_text, recalled, intent, learning)
        result.intent = intent
        result.recalled = recalled
        result.meta.setdefault("learning", learning.to_dict())
        if forgotten:
            result.meta["forgotten"] = [e.to_dict() for e in forgotten]
        return result


# ---------------------------------------------------------------------------
# Profil-Helfer (gelernte Vorlieben für Denkis Verhalten)
# ---------------------------------------------------------------------------


def _profile(context: list[dict[str, Any]]) -> dict[str, Any]:
    prof: dict[str, Any] = {"anrede": "du", "stil": "normal", "emojis": True, "facts": []}
    for fact in memory.recall_profile(limit=40):
        if fact.get("category") != "profil":
            continue
        key = fact["key"].split(":", 1)[-1]
        value = normalize(fact.get("value") or "")
        prof["facts"].append(fact["label"])
        if key == "anrede":
            prof["anrede"] = value or "du"
        elif key == "antwortstil":
            prof["stil"] = value or "normal"
        elif key == "emojis":
            prof["emojis"] = False
    return prof


def _name_of(context: list[dict[str, Any]]) -> str | None:
    for fact in memory.recall_profile(limit=40):
        if fact["key"] == "identitaet:name" and fact["status"] == "active":
            value = (fact.get("value") or "").strip()
            return value.split(" ")[0].title() if value else None
    return None


_SIE_FORMS = {
    "du": "Sie", "dich": "Sie", "dir": "Ihnen", "dein": "Ihr", "deine": "Ihre",
    "deinen": "Ihren", "deinem": "Ihrem", "deiner": "Ihrer", "deines": "Ihres",
    "bist": "sind", "hast": "haben", "weißt": "wissen", "weisst": "wissen",
    "magst": "mögen", "kannst": "können", "willst": "wollen", "möchtest": "möchten",
    "moechtest": "möchten", "sollst": "sollen", "siehst": "sehen", "machst": "machen",
    "sagst": "sagen", "brauchst": "brauchen", "arbeitest": "arbeiten", "wohnst": "wohnen",
    "lernst": "lernen", "kommst": "kommen",
    "erzähl": "erzählen Sie", "erzähle": "erzählen Sie", "probier": "probieren Sie",
    "frag": "fragen Sie", "teste": "testen Sie", "schau": "schauen Sie",
}

_SIE_PATTERN = re.compile(
    r"\b(?:" + "|".join(sorted(_SIE_FORMS, key=len, reverse=True)) + r")\b", re.I
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9„“»«(])")


def _decorate(text: str, prof: dict[str, Any]) -> str:
    """Passt die Antwort an gelernte Vorlieben an (Siezen, Kürze, Emojis)."""
    out = text

    if prof.get("anrede") == "sie":
        def replace(match: "re.Match[str]") -> str:
            word = match.group(0)
            new_word = _SIE_FORMS.get(word.lower(), word)
            if word[:1].isupper():
                new_word = new_word[:1].upper() + new_word[1:]
            return new_word

        out = _SIE_PATTERN.sub(replace, out)

    # „Antworte kurz“: nur Fließtext stauchen – Listen und Blöcke bleiben lesbar
    if prof.get("stil") in {"kurz", "knapp"} and "\n" not in out:
        sentences = [sentence for sentence in _SENTENCE_SPLIT.split(out) if sentence.strip()]
        out = " ".join(sentences[:2]) if sentences else out
        if len(out) > 260:
            out = out[:260].rsplit(" ", 1)[0].rstrip(" ,;:") + " …"

    if prof.get("emojis") is False:
        out = "".join(ch for ch in out if ord(ch) < 0x2600 or ch in "–—…„“‚‘»«")
    return out


# Allgemeine Gedächtnis-Fragen: hier passt das komplette Profil besser als ein
# einzelner Treffer („Was weißt du über mich?“).
_GENERAL_MEMORY_QUESTION = re.compile(
    r"(?:über\s+mich|ueber\s+mich|alles\s+(?:was|über)|was\s+weißt\s+du|"
    r"was\s+weisst\s+du|allgemein|about\s+me|what\s+do\s+you\s+know)",
    re.I,
)

_FILLER_WORDS = {
    "ich", "und", "der", "die", "das", "ist", "bin", "mit", "bei", "für", "auf",
    "nicht", "kein", "keine", "auch", "sehr", "gerade", "heute", "morgen",
    "mal", "noch", "hier", "eine", "einen", "einem", "mein", "meine", "meinen",
    "denki", "bitte", "danke", "hallo", "the", "and", "for", "with", "that",
    "habe", "haben", "wird", "werden", "kann", "könnte", "soll", "will",
}


def _topic_phrase(user_text: str, learning: Any = None) -> str:
    """Lesbarer Kern einer Aussage – die Mock-KI spricht darüber.

    Nutzt bevorzugt die frisch gelernten Werte („VS Code“, „GroTeck“) und fällt
    sonst auf die inhaltlichen Wörter der Nachricht zurück (im Original, nicht
    gestemmt – sonst klingt Denki nach einer Suchmaschine).
    """
    values: list[str] = []
    for event in (getattr(learning, "events", None) or []):
        value = (getattr(event, "value", "") or "").strip()
        label = (getattr(event, "label", "") or "").strip()

        # Denki-Verhalten (Profil) klingt als Klartext besser als Rohwert
        if label.startswith("Anrede:"):
            values.append("die Sie-Form" if value.lower().startswith("sie") else "die Du-Form")
            continue
        if label.startswith("Antwortstil:"):
            values.append(f"{value}e Antworten" if value else label)
            continue
        if label.startswith("Keine Emojis"):
            values.append("keine Emojis")
            continue
        if value and len(value) <= 44:
            values.append(value)
            continue
        label = (getattr(event, "label", "") or "").strip()
        if ":" in label:
            tail = label.rsplit(":", 1)[-1].strip().rstrip(".")
            if tail and len(tail) <= 44:
                values.append(tail)
    if values:
        unique = list(dict.fromkeys(values))
        return unique[0] if len(unique) == 1 else f"{unique[0]} und {unique[1]}"

    words = [w.strip(" .,!?:;„“\"'()") for w in (user_text or "").split()]
    words = [w for w in words if len(w) > 3 and w.lower() not in _FILLER_WORDS]
    if not words:
        return "das"
    if len(words) == 1:
        return words[0]
    if len(words) == 2:
        return f"{words[0]} und {words[1]}"
    return f"{', '.join(words[:2])} und {words[2]}"


def _learning_note(fresh: list[Any], corrections: list[Any]) -> str:
    """Formuliert die Lern-Notiz unter einer Antwort (transparentes Mitlernen)."""
    if corrections and fresh:
        old_label = corrections[0].label.strip().rstrip(".")
        new_label = fresh[0].label.strip().rstrip(".")
        note = f"✏️ **Korrigiert:** „{old_label}“ → „{new_label}“"
        if fresh[0].confidence is not None:
            note += f" _(Vertrauen {fresh[0].confidence:.0%})_"
        rest = len(fresh) + len(corrections) - 2
    elif fresh and fresh[0].kind == "reinforced":
        note = (f"🔁 **Wiedererkannt:** {fresh[0].label.strip()} "
                f"_(Vertrauen jetzt {fresh[0].confidence:.0%})_")
        rest = len(fresh) - 1
    elif fresh:
        note = (f"🧠 **Gemerkt:** {fresh[0].label.strip()} "
                f"_(Vertrauen {fresh[0].confidence:.0%})_")
        rest = len(fresh) - 1
    else:
        note = f"🗑️ **Verworfen:** {corrections[0].label.strip()}"
        rest = len(corrections) - 1

    if rest > 0:
        note += f" · +{rest} weitere Änderung{'en' if rest > 1 else ''}"
    return note


# ---------------------------------------------------------------------------
# MockBrain: deterministische, gedächtnisbewusste Demo-KI
# ---------------------------------------------------------------------------


class MockBrain(Brain):
    name = "mock"
    model = "denki-mock-0.1"

    def reply(self, user_text, context, intent, learning=None) -> BrainResult:
        prof = _profile(context)
        name = _name_of(context)
        handler = getattr(self, f"_on_{intent.name}", self._on_fallback)
        text, meta = handler(user_text, context, prof, name, learning)
        return BrainResult(text=_decorate(text, prof), brain=self.name, model=self.model, meta=meta)

    # -- einzelne Intents -------------------------------------------------

    def _on_greeting(self, user_text, context, prof, name, learning=None):
        base = f"{greeting_for_now()}"
        if name:
            base += f", {name}"
        stats = memory.stats()
        if stats["facts_active"] == 0:
            base += (
                "! Ich bin Denki – ich lerne lokal mit, was du mir erzählst.\n\n"
                "Probier zum Beispiel: „Ich heiße Dennis und arbeite bei GroTeck.“"
            )
        else:
            base += (
                f"! Schön, dass du wieder da bist – ich habe aktuell "
                f"{stats['facts_active']} Erinnerung{'en' if stats['facts_active'] != 1 else ''} über dich."
            )
        return base + " Womit fangen wir an?", {"name_known": bool(name)}

    def _on_farewell(self, user_text, context, prof, name, learning=None):
        return (
            f"Bis dann{', ' + name if name else ''}! Ich behalte alles Wichtige im lokalen Gedächtnis – "
            "nichts verlässt deinen Rechner."
        ), {}

    def _on_thanks(self, user_text, context, prof, name, learning=None):
        return random.choice([
            "Gern! Dafür bin ich da.",
            "Sehr gerne – sag Bescheid, wenn ich noch etwas übernehmen soll.",
            "Kein Ding. Ich lerne bei jedem Austausch ein bisschen mehr dazu.",
        ]), {}

    def _on_confirm(self, user_text, context, prof, name, learning=None):
        events = memory.confirm(all_facts=False, fact_id=context[0]["id"]) if context else []
        if events:
            return (
                f"Verstanden – ich habe mir „{events[0].label}“ jetzt fester gemerkt "
                f"(Vertrauen {events[0].confidence:.0%})."
            ), {"confirmed": [e.to_dict() for e in events]}
        return "Alles klar, notiert. Wenn du mir mehr erzählst, werde ich präziser.", {}

    def _on_deny(self, user_text, context, prof, name, learning=None):
        if context:
            fact = context[0]
            memory.delete_fact(fact["id"])
            return (
                f"Okay – ich habe die Erinnerung „{fact['label']}“ verworfen. "
                "Sag mir gern die richtige Version, dann lerne ich sie neu."
            ), {"forgotten": [fact["id"]]}
        return (
            "Danke für die Rückmeldung. Was war falsch? Sobald du es richtig stellst, "
            "überschreibe ich die alte Erinnerung."
        ), {}

    def _on_forget(self, user_text, context, prof, name, learning=None):
        result = learning or memory.learn(user_text, source="user")
        forgotten = [e for e in result.events if e.kind == "forgotten"]
        if forgotten:
            labels = "; ".join(f"„{e.label}“" for e in forgotten[:5])
            more = f" (+{len(forgotten) - 5} weitere)" if len(forgotten) > 5 else ""
            return f"Erledigt – vergessen: {labels}{more}. Das bleibt auch gelöscht.", {
                "learning": result.to_dict()
            }
        return (
            "Ich habe nichts Passendes gefunden, das ich löschen könnte. "
            "Im Gedächtnis-Panel rechts kannst du jede Erinnerung einzeln entfernen.",
            {"learning": result.to_dict()},
        )

    def _on_ask_memory(self, user_text, context, prof, name, learning=None):
        # Allgemeine Frage („Was weißt du über mich?“) -> komplettes Profil zeigen
        if not context and _GENERAL_MEMORY_QUESTION.search(user_text or ""):
            return self._on_list_memories(user_text, context, prof, name, learning)

        if context:
            lines = "\n".join(
                f"• {f['label']} _(Vertrauen {f['confidence']:.0%}, {f['times_learned']}× gelernt)_"
                for f in context[:5]
            )
            return (
                f"Ja, daran erinnere ich mich – direkt aus dem lokalen Gedächtnis:\n{lines}"
                f"\n\nTrefferquote für deine Frage: {context[0]['score']:.0%}."
            ), {"recall_used": True}
        stats = memory.stats()
        if stats["facts_active"] == 0:
            return (
                "Bisher weiß ich noch nichts Persönliches über dich – das Gedächtnis ist leer. "
                "Erzähl mir etwas wie „Ich heiße …“ oder „Ich arbeite an …“."
            ), {}
        return (
            "Dazu habe ich noch nichts gespeichert. Ich weiß aber bereits "
            f"{stats['facts_active']} andere Dinge über dich – frag mich z. B. „Was weißt du über mich?“."
        ), {}

    def _on_list_memories(self, user_text, context, prof, name, learning=None):
        facts = memory.all_facts(status="active")
        if not facts:
            return "Mein Gedächtnis ist aktuell leer. Erzähl mir etwas, dann ändert sich das sofort.", {}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            grouped.setdefault(fact["category"], []).append(fact)
        blocks = []
        for category, items in grouped.items():
            title = memory.CATEGORY_LABELS.get(category, category)
            body = "\n".join(
                f"  • {f['label']} – {f['confidence']:.0%}, {f['times_learned']}× gelernt" for f in items
            )
            blocks.append(f"**{title}**\n{body}")
        return "Das ist mein komplettes Wissen über dich:\n\n" + "\n\n".join(blocks), {}

    def _on_ask_profile(self, user_text, context, prof, name, learning=None):
        return (
            "Ich bin **Denki** – eine lokale, mitlernende KI für Windows, erfunden von "
            f"Dennis C. Großer (GroTeck).\n\n"
            f"Was mich ausmacht:\n"
            "• **100 % lokal** – deine Daten liegen in einer SQLite-Datei auf deinem Rechner.\n"
            "• **Mitlernend** – jede Aussage wird extrahiert, bei Wiederholung verstärkt, bei Widerspruch korrigiert.\n"
            "• **Transparent** – im Gedächtnis-Panel siehst du jeden Fakt samt Vertrauen und kannst ihn löschen.\n\n"
            "Im Prototyp antwortet eine Mock-KI; sobald Ollama läuft, übernimmt ein lokales LLM dieselbe Rolle."
        ), {"version": config.APP_VERSION}

    def _on_ask_capabilities(self, user_text, context, prof, name, learning=None):
        return (
            "Ich kann zuhören, behalten und mitdenken:\n\n"
            "1. **Merkwürdig gut erinnern** – Namen, Projekte, Vorlieben, Termine, Setup.\n"
            "2. **Mitlernen** – sagst du etwas zweimal, steigt mein Vertrauen; korrigierst du mich, ersetze ich den alten Fakt.\n"
            "3. **Vergessen auf Zuruf** – „Vergiss meinen Job“ löscht den Eintrag wirklich.\n"
            "4. **Kontext nutzen** – ich beantworte Fragen aus deinem Gedächtnis, statt raten zu müssen.\n"
            "5. **Sich anpassen** – Du/Sie, kurze oder ausführliche Antworten, mit oder ohne Emojis.\n\n"
            "Tipp: Frag „Was weißt du über mich?“ oder öffne rechts das Gedächtnis-Panel."
        ), {}

    def _on_ask_identity(self, user_text, context, prof, name, learning=None):
        return (
            "Erfunden und gebaut von **Dennis C. Großer** unter dem Label **GroTeck**. "
            "Der Anspruch: KI, die dem Nutzer gehört – lokal, nachvollziehbar, ohne Cloud-Zwang."
        ), {}

    def _on_ask_help(self, user_text, context, prof, name, learning=None):
        return (
            "Klar, ich helfe. Damit ich wirklich nützlich werde, erzähl mir kurz den Kontext – "
            "z. B. woran du arbeitest, welches Ziel du hast oder was schiefgeht. "
            "Ich behalte das und baue beim nächsten Mal darauf auf.\n\n"
            "Konkret kann ich gerade: Fragen aus deinem Gedächtnis beantworten, Termine und "
            "Vorlieben festhalten, Texte zusammenfassen (Stichpunkte) und nächste Schritte vorschlagen."
        ), {}

    def _on_ask_time(self, user_text, context, prof, name, learning=None):
        now = datetime.now()
        return (
            f"Bei dir ist es {now.strftime('%H:%M')} Uhr am {now.strftime('%d.%m.%Y')} "
            f"({['Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag','Sonntag'][now.weekday()]}). "
            "Ich nutze deine lokale Systemzeit – kein Server gefragt."
        ), {"local_time": now.isoformat(timespec="seconds")}

    def _on_ask_mood(self, user_text, context, prof, name, learning=None):
        stats = memory.stats()
        return (
            f"Funktionierend und neugierig: {stats['facts_active']} aktive Erinnerungen, "
            f"{stats['recalled_total']} Abrufe, Lernfortschritt {stats['mastery']:.0%}. "
            "Und bei dir?"
        ), {"stats": stats}

    def _on_ask_local_privacy(self, user_text, context, prof, name, learning=None):
        return (
            "Kurz: **nichts verlässt deinen Rechner.**\n\n"
            "• Gedächtnis: eine lokale SQLite-Datei (`data/denki.sqlite3`).\n"
            "• Inferenz: MockBrain offline, alternativ ein lokales Modell via Ollama (`127.0.0.1`).\n"
            "• Keine Telemetrie, kein Konto, kein Upload. Reset jederzeit über „Gedächtnis leeren“.\n\n"
            "Genau das ist der Punkt von Denki: mitlernende KI ohne Datenpreisgabe."
        ), {}

    def _on_smalltalk(self, user_text, context, prof, name, learning=None):
        if context:
            return (
                f"Verstanden. Passend dazu habe ich im Gedächtnis: „{context[0]['label']}“. "
                "Soll ich das ausbauen oder möchtest du mir etwas Neues erzählen?"
            ), {"recall_used": True}
        return (
            "Ich höre zu. Wenn du mir etwas Persönliches oder Projektbezogenes erzählst, "
            "merkt sich Denki es dauerhaft – probier es aus."
        ), {}

    def _on_statement(self, user_text, context, prof, name, learning=None):
        learned = learning or memory.learn(user_text, source="user")
        fresh = [e for e in learned.events if e.kind in {"extracted", "reinforced"}]
        corrections = [e for e in learned.events if e.kind == "corrected"]

        if fresh or corrections:
            note = _learning_note(fresh, corrections)
            lead = self._acknowledge(user_text, context, prof, name, learned)
            return f"{lead}\n\n{note}", {"learning": learned.to_dict()}

        # nichts Neues gelernt -> Kontext nutzen oder nachfragen
        if context:
            lead = self._acknowledge(user_text, context, prof, name, learned)
            return (
                f"{lead}\n\nIch verknüpfe das mit „{context[0]['label']}“ "
                f"(Relevanz {context[0]['score']:.0%}). Soll ich das vertiefen?"
            ), {"learning": learned.to_dict(), "recall_used": True}

        return (
            self._acknowledge(user_text, context, prof, name, learned)
            + "\n\nErzähl ruhig konkreter – Namen, Zahlen oder Vorlieben merke ich mir dauerhaft."
        ), {"learning": learned.to_dict()}

    def _acknowledge(self, user_text, context, prof, name, learning=None) -> str:
        """Kurze, inhaltliche Spiegelung der Aussage (Mock-Ersatz für ein LLM)."""
        topic = _topic_phrase(user_text, learning)
        opener = random.choice([
            "Alles klar", "Verstanden", "Notiert", "Okay", "Danke für die Info",
        ])
        followups = [
            f"Gibt es zu {topic} einen Zeitplan oder ein Ziel, das ich mitdenken soll?",
            f"Soll ich zu {topic} etwas festhalten, das ich später automatisch einbringe?",
            f"Wie wichtig ist {topic} gerade für dich – eher Nebenprojekt oder Hauptfokus?",
            f"Möchtest du, dass ich bei {topic} ab jetzt aktiv mitdenke und nachfrage?",
        ]
        return f"{opener} – ich habe {topic} aufgenommen. {random.choice(followups)}"

    def _on_question(self, user_text, context, prof, name, learning=None):
        if context:
            top = context[0]
            lines = "\n".join(f"• {f['label']}" for f in context[:3])
            return (
                f"Aus deinem lokalen Gedächtnis (beste Übereinstimmung {top['score']:.0%}):\n{lines}\n\n"
                "Soll ich daraus eine konkrete Empfehlung oder einen Plan machen?"
            ), {"recall_used": True}
        return (
            "Dazu habe ich noch keine Erinnerung – und raten ist nicht mein Stil. "
            "Gib mir ein, zwei Fakten, dann beantworte ich solche Fragen beim nächsten Mal direkt."
        ), {}

    def _on_fallback(self, user_text, context, prof, name, learning=None):
        if not user_text.strip():
            return "Ich bin hier, wenn du etwas sagen möchtest.", {}
        return self._on_statement(user_text, context, prof, name)


# ---------------------------------------------------------------------------
# OllamaBrain: echte lokale Inferenz (optional, gleiche Schnittstelle)
# ---------------------------------------------------------------------------


class OllamaBrain(Brain):
    name = "ollama"

    def __init__(self, url: str = config.OLLAMA_URL, model: str = config.OLLAMA_MODEL):
        self.url = url.rstrip("/")
        self.model = model
        self.fallback = MockBrain()

    @staticmethod
    def available(url: str = config.OLLAMA_URL) -> tuple[bool, list[str]]:
        try:
            import httpx  # lokal, kein Cloud-Zugriff

            resp = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=config.OLLAMA_TIMEOUT)
            if resp.status_code != 200:
                return False, []
            data = resp.json()
            return True, [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return False, []

    def _system_prompt(self, context: list[dict[str, Any]], prof: dict[str, Any]) -> str:
        if context:
            mem = "\n".join(
                f"- {f['label']} (Vertrauen {f['confidence']:.0%})" for f in context
            )
        else:
            mem = "(noch keine Erinnerungen zu dieser Anfrage)"
        anrede = "Sie" if prof.get("anrede") == "sie" else "Du"
        stil = prof.get("stil", "normal")
        return (
            f"Du bist Denki, eine lokale, mitlernende KI für Windows von Dennis C. Großer (GroTeck). "
            f"Antworte auf Deutsch, nutze die Anrede „{anrede}“, Antwortstil: {stil}. "
            f"Keine Emojis, wenn der Nutzer das nicht will. "
            f"Du erinnerst dich an Folgendes:\n{mem}\n"
            "Wenn du eine Erinnerung nutzt, erwähne sie kurz. Erfinde nichts."
        )

    def reply(self, user_text, context, intent, learning=None) -> BrainResult:
        prof = _profile(context)
        try:
            import httpx

            model = self.model
            ok, models = self.available(self.url)
            if ok and models and not any(model in m for m in models):
                model = models[0]
            payload = {
                "model": model,
                "stream": False,
                "prompt": user_text,
                "system": self._system_prompt(context, prof),
                "options": {"temperature": 0.4, "num_predict": 400},
            }
            resp = httpx.post(f"{self.url}/api/generate", json=payload, timeout=120)
            resp.raise_for_status()
            text = (resp.json().get("response") or "").strip()
            if not text:
                raise ValueError("leere Antwort")
            result = BrainResult(text=_decorate(text, prof), brain="ollama", model=model,
                                 meta={"local_model": True})
            # Das Gedächtnis arbeitet Backend-unabhängig: Lernen passiert in Brain.chat()
            result.meta["learning"] = (learning or memory.LearningResult()).to_dict()
            return result
        except Exception as exc:  # pragma: no cover - hängt vom lokalen Setup ab
            result = self.fallback.reply(user_text, context, intent, learning)
            result.meta["ollama_error"] = str(exc)[:200]
            result.meta["note"] = "Ollama nicht erreichbar – MockBrain übernommen."
            return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_brain() -> Brain:
    backend = (config.BRAIN_BACKEND or "auto").lower()
    if backend == "mock":
        return MockBrain()
    if backend == "ollama":
        return OllamaBrain()
    ok, _models = OllamaBrain.available()
    return OllamaBrain() if ok else MockBrain()
