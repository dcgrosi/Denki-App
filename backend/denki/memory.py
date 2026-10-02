"""Denkis Gedächtnis – die „mitlernende“ Schicht.

Prinzip (bewusst transparent und auditierbar statt Blackbox):

1. **Extraktion**  – Regeln erkennen Aussagen über den Nutzer („Ich heiße …“,
   „Ich arbeite bei …“, „Mein Lieblings…“). Jeder Treffer wird eine *Fact*.
2. **Verstärkung** – Wird dieselbe Aussage wiederholt, steigt das Vertrauen
   (`times_learned`, `confidence`). Bestätigungen ebenfalls.
3. **Korrektur**   – Widerspricht eine neue Aussage einer alten derselben
   Kategorie, wird die alte als `superseded` markiert (Provenienz bleibt).
4. **Vergessen**    – „Vergiss X“ entfernt Fakten; zusätzlich gibt es sanftes
   Zeit-Decay für lange ungenutzte Erinnerungen.
5. **Abruf**        – Token-Ähnlichkeit + Vertrauen + Frische bestimmen, was
   in den Antwort-Kontext wandert.

Alles landet in einer lokalen SQLite-Datei – kein Cloud-Zugriff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from . import config, db
from .textutil import (base_form, clean_value, content_tokens, expand_synonyms,
                       keywords, levenshtein, normalize, similarity, stem,
                       tokenize, word_forms)

CATEGORY_LABELS = {
    "identitaet": "Identität",
    "beziehungen": "Menschen & Beziehungen",
    "arbeit": "Arbeit & Projekte",
    "vorlieben": "Vorlieben",
    "abneigungen": "Abneigungen",
    "ziele": "Ziele",
    "termine": "Termine",
    "umgebung": "Umgebung & Setup",
    "profil": "Denki-Verhalten",
}

# Kategorien, in denen pro Subjekt nur EIN Fakt sinnvoll ist (=> Korrektur)
SINGLE_VALUE_CATEGORIES = {"identitaet", "arbeit", "vorlieben", "abneigungen", "umgebung", "termine"}


@dataclass
class Pattern:
    name: str
    category: str
    regex: re.Pattern[str]
    label: str            # Template mit {value}
    key_hint: str = ""    # z. B. "name" -> key = identitaet:name
    confidence: float = 0.0
    subject: str = "ich"      # über wen die Aussage getroffen wird
    allow_clause: bool = False  # darf auch in Satzteilen ohne Subjekt greifen


_PATTERNS: list[Pattern] = [
    # --- Identität -------------------------------------------------------
    Pattern("name", "identitaet",
            re.compile(r"\b(?:(?:ich\s+)?(?:heiße|heisse|nenne\s+mich)\s+|mein\s+name\s+ist\s+|my\s+name\s+is\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ'-]*(?:\.)?(?:\s+[\wäöüßÄÖÜ][\wäöüßÄÖÜ'-]*(?:\.?)){0,3})", re.I),
            "Der Nutzer heißt {value}.", key_hint="name", confidence=0.30, allow_clause=True),
    Pattern("spitzname", "identitaet",
            re.compile(r"\b(?:nenn\s+mich\s+(?:bitte\s+)?|ruf\s+mich\s+|du\s+kannst\s+mich\s+|\bcall\s+me\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ'-]*(?:\s+[\wäöüßÄÖÜ][\wäöüßÄÖÜ'-]*){0,2})", re.I),
            "Möchte „{value}“ genannt werden.", key_hint="spitzname", confidence=0.24),
    Pattern("wohnort", "identitaet",
            re.compile(r"\b(?:(?:ich\s+)?(?:wohne|lebe)\s+in\s+|(?:ich\s+)?komme\s+aus\s+|wohnhaft\s+in\s+|i\s+live\s+in\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .-]{0,40})", re.I),
            "Wohnt in {value}.", key_hint="wohnort", confidence=0.18, allow_clause=True),
    Pattern("sprache", "identitaet",
            re.compile(r"\b(?:ich\s+spreche\s+|meine\s+muttersprache\s+ist\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ ,-]{0,32})", re.I),
            "Spricht {value}.", key_hint="sprache", confidence=0.12),
    Pattern("alter", "identitaet",
            re.compile(r"\b(?:ich\s+(?:bin|werde)\s+|i\s+am\s+)(?P<value>\d{1,3})\s*(?:jahre(?:\s+alt)?|years(?:\s+old)?)", re.I),
            "Ist {value} Jahre alt.", key_hint="alter", confidence=0.14),

    # --- Arbeit & Projekte ----------------------------------------------
    Pattern("arbeitgeber", "arbeit",
            re.compile(r"\b(?:(?:ich\s+)?(?:arbeite|bin\s+angestellt|bin\s+tätig|bin\s+taetig)\s+(?:bei|für|fur|an)\s+|i\s+work\s+(?:at|for|on)\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .&/-]{0,44})", re.I),
            "Arbeitet bei/an: {value}.", key_hint="arbeitgeber", confidence=0.20, allow_clause=True),
    Pattern("rolle", "arbeit",
            re.compile(r"\b(?:(?:ich\s+)?bin\s+(?:von\s+beruf\s+|selbstständige?r?\s+|freiberufliche?r?\s+)?|i\s+am\s+(?:an?\s+)?)(?P<value>(?:software|web|frontend|backend|full[-\s]?stack|data|ki|ai|ml|devops|cloud|ux|ui|product|projekt|team|tech|sales|marketing|hr)?[\wäöüßÄÖÜ .-]{0,30}?(?:entwickler|entwicklerin|developer|ingenieur|ingenieurin|engineer|designer|designerin|manager|managerin|architekt|architektin|berater|beraterin|student|studentin|schüler|schueler|auszubildende[rn]?|geschäftsführer|geschaeftsfuehrer|gründer|gruender|founder|autor|autorin|lehrer|lehrerin|arzt|ärztin|handwerker|informatiker|informatikerin|elektriker|mechaniker|koch|kellner)\b)", re.I),
            "Tätigkeit: {value}.", key_hint="rolle", confidence=0.18, allow_clause=True),
    Pattern("arbeitgeber_bei", "arbeit",
            re.compile(r"\b(?:(?:ich\s+)?bin\s+[\wäöüßÄÖÜ .-]{0,34}?\s+bei\s+|(?:ich\s+)?(?:arbeite|wirke)\s+als\s+[\wäöüßÄÖÜ .-]{0,30}?\s+bei\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .&/-]{0,40})", re.I),
            "Arbeitet bei/an: {value}.", key_hint="arbeitgeber", confidence=0.18, allow_clause=True),
    Pattern("projekt", "arbeit",
            re.compile(r"\b(?:(?:ich\s+)?(?:arbeite|bastel|baue)\s+(?:gerade\s+)?an\s+|aktuell\s+baue\s+ich\s+|mein\s+(?:aktuelles\s+)?projekt\s+(?:ist|heißt|heisst)\s+|i\s+am\s+(?:currently\s+)?working\s+on\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .&/+-]{0,44})", re.I),
            "Aktuelles Projekt: {value}.", key_hint="projekt", confidence=0.16, allow_clause=True),
    Pattern("system", "umgebung",
            re.compile(r"\b(?:"
                       r"(?:ich\s+)?(?:nutze|verwende|benutze|arbeite\s+auf|fahre|setze\s+auf)\s+"
                       r"(?:einen?\s+|eine\s+|mit\s+)?"
                       r"(?P<value>windows(?:\s+\d+)?|linux|ubuntu|debian|fedora|macos|mac|android|ios)"
                       r"|mein\s+(?:rechner|pc|laptop)\s+(?:läuft|laeuft|nutzt)\s+(?:mit\s+)?"
                       r"(?P<value2>windows(?:\s+\d+)?|linux|ubuntu|debian|fedora|macos|mac)"
                       r"|i\s+(?:use|run|am\s+on)\s+(?P<value3>windows(?:\s+\d+)?|linux|ubuntu|macos|mac)"
                       r")\b", re.I),
            "System: {value}.", key_hint="system", confidence=0.12, allow_clause=True),
    Pattern("nutzt_tool", "arbeit",
            re.compile(r"\b(?:(?:ich\s+)?(?:nutze|verwende|benutze|programmiere\s+mit|arbeite\s+mit)\s+|mein\s+(?:setup|stack)\s+(?:ist|nutzt)\s+|i\s+(?:use|work\s+with)\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .+#/-]{0,32})", re.I),
            "Nutzt: {value}.", confidence=0.06, allow_clause=True),

    # --- Vorlieben / Abneigungen ----------------------------------------
    Pattern("lieblings", "vorlieben",
            re.compile(r"\b(?:mein(?:e|en|er)?\s+lieblings(?P<domain>[\wäöüßÄÖÜ]{2,20})\s+ist\s+(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .&/-]{0,40})|my\s+favou?rite\s+(?P<domain2>[\w]{2,20})\s+is\s+(?P<value2>[\w][\w .&/-]{0,40}))", re.I),
            "Lieblings-{domain}: {value}.", confidence=0.16),
    Pattern("mag", "vorlieben",
            re.compile(r"\b(?:(?:ich\s+)?(?:mag|liebe|feiere)\s+|i\s+(?:like|love)\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .,&/+:-]{0,40})", re.I),
            "Mag: {value}.", confidence=0.10, allow_clause=True),
    Pattern("mag_nicht", "abneigungen",
            re.compile(r"\b(?:(?:ich\s+)?(?:mag|hasse|verabscheue|esse|trinke)\s+(?:absolut\s+|überhaupt\s+nicht\s+|gar\s+nicht\s+)?(?:nicht|keine|kein|keinen|keinem|keiner)\s+|i\s+(?:hate|don'?t\s+like|dislike)\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .,&/+:-]{0,40})", re.I),
            "Mag nicht: {value}.", confidence=0.12, allow_clause=True),
    Pattern("bevorzugt", "vorlieben",
            re.compile(r"\b(?:ich\s+(?:bevorzuge|präferiere|preferiere)\s+|i\s+prefer\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .,&/+:-]{0,40})", re.I),
            "Bevorzugt: {value}.", confidence=0.14),

    # --- Ziele ----------------------------------------------------------
    Pattern("ziel", "ziele",
            re.compile(r"\b(?:(?:ich\s+)?(?:will|möchte|moechte|plane)\s+|mein\s+ziel\s+ist(?:\s+es)?,?\s+|i\s+(?:want|plan)\s+to\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .,&/+-]{0,60})", re.I),
            "Ziel: {value}.", confidence=0.10, allow_clause=True),
    Pattern("lernen", "ziele",
            re.compile(r"\b(?:(?:ich\s+)?(?:lerne|möchte\s+lernen|will\s+lernen)\s+(?:gerade\s+|jetzt\s+|momentan\s+|aktuell\s+)?|i\s+(?:am\s+(?:currently\s+)?learning|want\s+to\s+learn)\s+)(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .,+/-]{0,40})", re.I),
            "Lernt gerade: {value}.", key_hint="lernen", confidence=0.10, allow_clause=True),

    # --- Termine --------------------------------------------------------
    Pattern("termin", "termine",
            re.compile(r"\b(?:ich\s+habe\s+)?(?:(?:am|um)\s+)?"
                       r"(?P<value>(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|heute|morgen|übermorgen|\d{1,2}\.\d{1,2}\.?(?:\d{2,4})?)"
                       r"(?![\wäöüßÄÖÜ])"
                       r"(?:\s+(?:um|at|gegen|von)\s+\d{1,2}(?:[:.]\d{2})?\s*(?:uhr)?)?"
                       r"\s+(?:einen?\s+|eine\s+|meinen?\s+|meine\s+)?"
                       r"[\wäöüßÄÖÜ][\wäöüßÄÖÜ .-]{1,26}(?![\wäöüßÄÖÜ]))", re.I),
            "Termin: {value}.", confidence=0.04),

    # --- Menschen & Beziehungen -----------------------------------------
    Pattern("haustier", "beziehungen",
            re.compile(r"\bich\s+habe\s+(?:einen?\s+|eine\s+|zwei\s+|drei\s+)?(?P<domain>hund|katze|kater|hunde|katzen|kaninchen|pferd|vogel|hamster)\b"
                       r"(?:\s+(?:namens|mit\s+namen|heißt|heisst)\s+|,?\s+(?:der|die)\s+)?(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ'-]{0,20})?", re.I),
            "Haustier ({domain}): {value}.", confidence=0.08),
    Pattern("familie", "beziehungen",
            re.compile(r"\bmein(?:e|en)?\s+(?P<domain>frau|mann|partner|partnerin|freund|freundin|sohn|tochter|bruder|schwester|mutter|vater|mama|papa|oma|opa)\s+(?:heißt|heisst|ist)\s+(?P<value>[\wäöüßÄÖÜ][\wäöüßÄÖÜ .-]{0,24})", re.I),
            "{domain_cap}: {value}.", confidence=0.12),

    # --- Umgebung / Setup -----------------------------------------------
    Pattern("hardware", "umgebung",
            re.compile(r"\b(?:(?:ich\s+)?(?:habe|nutze|verwende)\s+(?:einen?\s+|eine\s+)?"
                       r"(?P<value>\d+\s*gb\s*(?:ram|arbeitsspeicher)|rtx\s*\d{3,4}|gtx\s*\d{3,4}|"
                       r"ryzen\s*\d|i[3579][- ]\d{4,5}|einen?\s+[\wäöüßÄÖÜ .-]{0,24}rechner))", re.I),
            "Hardware: {value}.", confidence=0.08, allow_clause=True),

    # --- Denki-Verhalten (Profil) ---------------------------------------
    Pattern("ton", "profil",
            re.compile(r"\b(?:(?:sei|antworte|rede|sprich|schreib)\s+(?:bitte\s+)?(?P<value>du|sie)\b|"
                       r"(?:duz|siez)\w*(?:\s+(?:mich|uns|bitte|mal|wieder|weiter))?|"
                       r"(?:wir\s+)?(?:duzen|siezen)\s+uns|"
                       r"please\s+(?:use\s+)?(?P<value2>du|sie)\b|"
                       r"(?:call|address)\s+me\s+(?:by\s+)?(?P<value3>du|sie))", re.I),
            "Anrede: {value}.", key_hint="anrede", confidence=0.20, subject="denki"),
    Pattern("antwortstil", "profil",
            re.compile(r"\b(?:antworte\s+(?:bitte\s+)?(?P<value>kurz|knapp|ausführlich|ausfuehrlich|detailliert|präzise|praezise|einfach|technisch)|halte\s+(?:dich\s+)?(?:bitte\s+)?(?P<value2>kurz|knapp)|answer\s+(?P<value3>briefly|short|in\s+detail))", re.I),
            "Antwortstil: {value}.", key_hint="antwortstil", confidence=0.16, subject="denki"),
    Pattern("kein_emoji", "profil",
            re.compile(r"\b(?:keine\s+emojis|ohne\s+emojis|lass\s+die\s+emojis\s+weg|no\s+emojis)", re.I),
            "Keine Emojis verwenden.", key_hint="emojis", confidence=0.18, subject="denki"),
]

# Satzteile, die ohne Subjekt wiederholt werden („… und arbeite bei GroTeck“)
_CLAUSE_SPLIT_RE = re.compile(r"\s+(?:und|aber|oder|sowie|,)\s+", re.I)
_CLAUSE_PENALTY = 0.92  # etwas weniger Vertrauen für indirekt erkannte Satzteile

# Füllwörter, die nicht als „Wert“ gelernt werden sollen
_VALUE_BLACKLIST = {
    "müde", "muede", "tired", "fertig", "unsicher", "neu", "hier", "da",
    "gestern", "heute", "morgen", "dabei", "dran", "so", "halt", "eben",
    "auch", "gerade", "noch", "nicht", "kein", "keine", "sehr", "viel",
    "alles", "nichts", "was", "wer", "wie", "ganz", "einfach", "total",
    "wirklich", "leider", "denki", "ki", "künstliche", "intelligenz",
    "dich", "mich", "es", "das", "ein", "eine", "ok", "okay", "super",
    "gut", "gute", "guter", "schlecht", "lange", "wenig", "mehr", "wieder",
    "los", "bereit", "gespannt", "neugierig", "sauer", "traurig", "froh",
    # Rollen/Gefühle sind keine Werte für sich
    "müde", "erschöpft", "erschoepft", "glücklich", "gluecklich", "aufgeregt",
    "entwickler", "student", "lehrer",
}

# Betriebssysteme sind eine eigene Kategorie („Umgebung“) und sollen nicht
# zusätzlich als generisches Werkzeug („Nutzt: Windows 11“) gelernt werden.
_OS_VALUES = {
    "windows", "windows 10", "windows 11", "linux", "ubuntu", "debian",
    "fedora", "macos", "mac", "android", "ios",
}

# Muster-spezifische Blacklists
_PATTERN_BLACKLIST = {
    "nutzt_tool": _OS_VALUES,
    "hardware": _OS_VALUES,
    # „Du kannst mich duzen“ ist eine Anrede-Regel, kein Spitzname
    "spitzname": {"du", "sie", "duzen", "siezen", "ihn", "ihnen", "einfach"},
}

# Muster, deren Treffer wir verwerfen (zu generisch / Selbstbezug)
_DROP_VALUE_RE = re.compile(
    r"^(?:\d+\s*(?:minuten|stunden|tage|wochen|jahre|mal|euro)|"
    r"(?:etwas|was|irgendetwas|nichts|viel|wenig)\s+(?:zu|an|mit)\s+|"
    r"(?:keine\s+ahnung|keine\s+zeit|keine\s+lust|lust\s+drauf)|"
    r"(?:das|es|dies|dieses)\s+(?:gemacht|getan|gesehen|gehört|gelesen)|"
    r"(?:mit\s+(?:der|dem|den)\s+(?:arbeit|familie|projekt)|"
    r"denki|ki\s+app|app|ding|sache|zeug|kram)$)",
    re.I,
)


@dataclass
class Candidate:
    category: str
    key: str
    label: str
    value: str
    source_text: str
    confidence: float
    subject: str = "ich"


@dataclass
class LearningEvent:
    kind: str                 # extracted | reinforced | corrected | forgotten | nothing
    fact_id: int | None = None
    label: str = ""
    detail: str = ""
    confidence: float | None = None
    value: str = ""           # der extrahierte Wert (für lesbare Antworten)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "fact_id": self.fact_id,
            "label": self.label.strip(),
            "detail": self.detail,
            "confidence": self.confidence,
            "value": self.value,
        }


@dataclass
class LearningResult:
    events: list[LearningEvent] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)

    @property
    def learned_anything(self) -> bool:
        return any(e.kind in {"extracted", "reinforced", "corrected", "forgotten"} for e in self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "topics": self.topics,
            "learned_anything": self.learned_anything,
        }


# ---------------------------------------------------------------------------
# Extraktion
# ---------------------------------------------------------------------------

# Muster-spezifische Wertgrenzen: „arbeite bei GroTeck in Köln“ -> Wert „GroTeck“,
# denn Ort/Zeit gehören in eigene Kategorien und nicht in den Firmennamen.
_VALUE_CUT: dict[str, re.Pattern[str]] = {
    "name": re.compile(r"\s+(?:und|sowie|aus|in|im|bei|von|seit)\b.*$", re.I),
    "wohnort": re.compile(r"\s+(?:und|sowie|mit|bei|seit|am|in\s+der)\b.*$", re.I),
    "arbeitgeber": re.compile(r"\s+(?:in|im|am|um|seit|als|und|sowie|mit)\b.*$", re.I),
    "rolle": re.compile(r"\s+(?:in|im|bei|für|fuer|am|und|sowie|seit)\b.*$", re.I),
    "projekt": re.compile(r"\s+(?:in|im|mit|für|fuer|und|sowie|am|um|seit)\b.*$", re.I),
    "nutzt_tool": re.compile(r"\s+(?:in|im|auf|mit|für|fuer|seit|am|um)\b.*$", re.I),
    "ziel": re.compile(r"\s+(?:in|im|am|um|seit)\s+(?:der|dem|den|die|das|einen?|eine|mein\w*)\b.*$", re.I),
}


def _cut_value(value: str, pattern_name: str) -> str:
    """Schneidet orts-/zeitbezogene Nachsätze ab, wo sie den Wert verwässern."""
    pattern = _VALUE_CUT.get(pattern_name)
    if not pattern:
        return value
    cut = pattern.sub("", value).strip().rstrip(",;:-").strip()
    # Nie auf einen leeren Wert kürzen
    return cut if len(cut) >= 2 else value


def _valid_value(value: str, pattern_name: str = "") -> bool:
    v = (value or "").strip().strip(" .,!?-–—")
    if len(v) < 2 or len(v) > 200:
        return False
    if v.lower() in _VALUE_BLACKLIST:
        return False
    if v.lower() in _PATTERN_BLACKLIST.get(pattern_name, ()):
        return False
    if _DROP_VALUE_RE.match(v):
        return False
    # Reine Zahlen ohne Kontext sind zu schwach
    if re.fullmatch(r"[\d\s.,:]+", v):
        return False
    return True


def _make_key(category: str, hint: str, value: str) -> str:
    base = hint.strip() if hint else " ".join(sorted(content_tokens(value)))[:40]
    base = re.sub(r"\s+", "-", normalize(base)).strip("-")
    if not base:
        base = "wert"
    return f"{category}:{base}"


def _candidates_from(patterns: list[Pattern], text: str, *, penalty: float = 1.0) -> list[Candidate]:
    """Wendet eine Musterliste auf einen Text an und liefert Kandidaten."""
    out: list[Candidate] = []
    for pattern in patterns:
        for match in pattern.regex.finditer(text):
            groups = match.groupdict()
            value = clean_value(
                groups.get("value") or groups.get("value2") or groups.get("value3")
                or groups.get("value4") or ""
            )
            domain = clean_value(groups.get("domain") or groups.get("domain2") or "")

            # Wertgrenzen über den Schlüsselbegriff wählen (deckt Varianten ab,
            # z. B. „arbeitgeber_bei“ -> Regeln für „arbeitgeber“)
            value = _cut_value(value, pattern.key_hint or pattern.name)

            # Sonderfall Anrede: Wert aus dem Verb ableiten („Sieze mich“ -> Sie)
            if pattern.name == "ton":
                low = match.group(0).lower()
                value = "sie" if "siez" in low else "du" if "duz" in low else (value or "du")
                # „Bitte siezen Sie mich nicht“ -> Wunsch ist die Du-Form
                tail = text[match.end():match.end() + 22].lower()
                if re.search(r"\b(?:nicht|kein|keine|nie|no|don'?t)\b", tail):
                    value = "du" if value == "sie" else "sie"
                value = value.capitalize()

            # Sonderfall Haustier: ohne Namen die Gattung als Wert nehmen
            if pattern.name == "haustier" and not value:
                value = (domain or "Haustier").capitalize()

            # Sonderfall Emoji-Regel: das Muster hat kein Wert-Group
            if pattern.name == "kein_emoji" and not value:
                value = "nein"

            if not _valid_value(value, pattern.name):
                continue

            # Negations-Wächter: „ich mag keine Montage“ ist eine Abneigung,
            # die vom Muster „mag_nicht“ gelernt wird – nicht zusätzlich positiv.
            if pattern.name in {"mag", "bevorzugt", "lieblings"} and re.match(
                r"^(?:nicht|kein|keine|keinen|keiner|nie|nichts|no|not)\b", value, re.I
            ):
                continue

            # Schlüssel & menschenlesbare Aussage bauen
            if pattern.name == "lieblings" and domain:
                key = _make_key("vorlieben", f"lieblings-{stem(domain)}", value)
                label = f"Lieblings-{domain}: {value}."
            elif pattern.name == "familie" and domain:
                key = _make_key("beziehungen", stem(domain), value)
                label = f"{domain.capitalize()}: {value}."
            elif pattern.name == "haustier":
                pet = domain or "Haustier"
                key = _make_key("beziehungen", f"haustier-{stem(pet)}", value)
                label = f"Haustier ({pet}): {value}." if value.lower() != pet.lower() else f"Hat einen {pet}."
            else:
                key = _make_key(pattern.category, pattern.key_hint, value)
                label = pattern.label.format(
                    value=value,
                    domain=domain,
                    domain_cap=domain.capitalize() if domain else "",
                )

            out.append(
                Candidate(
                    category=pattern.category,
                    key=key,
                    label=label,
                    value=value,
                    source_text=text.strip()[:500],
                    confidence=round(min(config.CONFIDENCE_MAX,
                                         (config.CONFIDENCE_NEW + pattern.confidence) * penalty), 4),
                    subject=pattern.subject,
                )
            )
    return out


def extract_candidates(text: str) -> list[Candidate]:
    """Zieht alle erkannten Aussagen aus einem Text.

    Zwei Durchläufe:
    1. voller Text (höheres Vertrauen),
    2. Satzteile ohne Subjekt – damit „Ich heiße Anna und arbeite bei Siemens“
       *beide* Fakten liefert und nicht am zweiten Verb hängen bleibt.
    """
    if not text or not text.strip():
        return []

    candidates: list[Candidate] = []
    seen: set[str] = set()

    for cand in _candidates_from(_PATTERNS, text):
        if cand.key in seen:
            continue
        seen.add(cand.key)
        candidates.append(cand)

    # Widerspruchsfreie Auswahl: Ein gelernter Emoji-Wunsch schlägt ein
    # generisches „Ziel: keine Emojis“ aus der Ziel-Kategorie.
    if any(c.key == "profil:emojis" for c in candidates):
        candidates = [c for c in candidates if "emoji" not in c.value.lower()]

    clause_patterns = [p for p in _PATTERNS if p.allow_clause]
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]
    if len(clauses) > 1:
        for clause in clauses[1:]:
            for cand in _candidates_from(clause_patterns, clause, penalty=_CLAUSE_PENALTY):
                if cand.key in seen:
                    continue
                seen.add(cand.key)
                candidates.append(cand)

    return candidates


# ---------------------------------------------------------------------------
# Lernen (Schreiben ins Gedächtnis)
# ---------------------------------------------------------------------------

# Nur echte Befehle zählen als Vergessens-Wunsch – „ich mag keinen Kaffee“
# darf niemals das Gedächtnis leeren.
FORGET_VERBS = re.compile(
    r"\b(?:vergiss|vergiß|vergessen\s+bitte|lösche|loesche|entferne|streiche|"
    r"delete|forget|remove)\b",
    re.I,
)
STOPWORD_SUBJECTS = {"mich", "meinen", "meine", "mein", "das", "den", "die", "es",
                     "me", "my", "that", "this", "it", "everything", "alles"}


def forget_by_query(query: str) -> list[LearningEvent]:
    """Entfernt Fakten, die auf die Vergessens-Anfrage passen."""
    q = normalize(query)
    # Füllwörter der Anfrage entfernen („vergiss alles über meinen job“)
    q_clean = re.sub(
        r"\b(?:vergiss|vergiß|bitte|alles|über|ueber|von|den|die|das|meinen|meine|mein|me|my|forget|about|please|all)\b",
        " ", q,
    )
    q_clean = re.sub(r"\s+", " ", q_clean).strip()

    everything = q_clean in {"", "alles", "all", "everything", "komplett", "ganz"}
    with db.db() as conn:
        if everything:
            rows = conn.execute("SELECT id, label, value FROM facts WHERE status='active'").fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE facts SET status='forgotten', confidence=?, updated_at=? WHERE id=?",
                    (config.CONFIDENCE_MIN, db.now_iso(), row["id"]),
                )
                conn.execute(
                    "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
                    ("forgotten", row["id"], "Komplett vergessen (Nutzerbefehl)", db.now_iso()),
                )
            return [
                LearningEvent("forgotten", row["id"], row["label"].strip(),
                              "auf Nutzerbefehl vergessen", config.CONFIDENCE_MIN,
                              value=row["value"] or "")
                for row in rows
            ]

        facts = db.rows_to_dicts(conn.execute("SELECT * FROM facts WHERE status='active'").fetchall())

    events: list[LearningEvent] = []
    for fact in facts:
        hay = _fact_haystack(fact)
        score = relevance(q_clean, hay)
        if (specific_token_hit(q_clean, fact) and score >= 0.26) or score >= 0.55:
            with db.db() as conn:
                conn.execute(
                    "UPDATE facts SET status='forgotten', confidence=?, updated_at=? WHERE id=?",
                    (config.CONFIDENCE_MIN, db.now_iso(), fact["id"]),
                )
                conn.execute(
                    "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
                    ("forgotten", fact["id"], f"Vergessen wegen Anfrage: {query[:120]}", db.now_iso()),
                )
            events.append(
                LearningEvent("forgotten", fact["id"], fact["label"].strip(),
                              f"Vergessen (Treffer {score:.0%})", config.CONFIDENCE_MIN,
                              value=fact.get("value") or "")
            )
    return events


def _same_value(old: str | None, new: str | None) -> bool:
    """Sind zwei Werte „dieselbe Aussage“? (Groß-/Kleinschreibung, Tippfehler)"""
    a = normalize(old or "").replace("ß", "ss")
    b = normalize(new or "").replace("ß", "ss")
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    shorter = min(len(a), len(b))
    return shorter >= 4 and levenshtein(a, b) <= max(1, shorter // 8)


def _reinforce(conn, fact: dict[str, Any], candidate: Candidate) -> LearningEvent:
    new_conf = min(config.CONFIDENCE_MAX, fact["confidence"] + config.CONFIDENCE_REINFORCED)
    conn.execute(
        """UPDATE facts SET confidence=?, times_learned=times_learned+1, updated_at=?,
                  source_text=?, status='active'
           WHERE id=?""",
        (round(new_conf, 4), db.now_iso(), candidate.source_text, fact["id"]),
    )
    conn.execute(
        "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
        ("reinforced", fact["id"], f"Wiederholung #{fact['times_learned'] + 1}", db.now_iso()),
    )
    return LearningEvent("reinforced", fact["id"], candidate.label,
                         f"wiedererkannt ({fact['times_learned'] + 1}×), Vertrauen {new_conf:.0%}",
                         round(new_conf, 4), value=candidate.value)


def _insert(conn, candidate: Candidate, supersedes: int | None) -> LearningEvent:
    now = db.now_iso()
    cur = conn.execute(
        """INSERT INTO facts(key, category, label, value, source_text, confidence,
                             status, times_learned, supersedes, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET
               label=excluded.label,
               value=excluded.value,
               confidence=MAX(facts.confidence, excluded.confidence),
               status='active',
               times_learned=facts.times_learned+1,
               source_text=excluded.source_text,
               updated_at=excluded.updated_at""",
        (candidate.key, candidate.category, candidate.label, candidate.value,
         candidate.source_text, round(candidate.confidence, 4), "active", 1,
         supersedes, now, now),
    )
    fact_id = cur.lastrowid
    if fact_id is None:  # UPDATE-Pfad
        row = conn.execute("SELECT id, times_learned, confidence FROM facts WHERE key=?",
                           (candidate.key,)).fetchone()
        fact_id = row["id"] if row else None
        conf = row["confidence"] if row else candidate.confidence
        count = row["times_learned"] if row else 1
    else:
        conf, count = candidate.confidence, 1

    kind = "extracted"
    conn.execute(
        "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
        (kind, fact_id, candidate.source_text[:200], now),
    )
    detail = (
        f"neue Tatsache (ersetzt #{supersedes})" if supersedes
        else f"neu gelernt, Vertrauen {conf:.0%}"
    )
    return LearningEvent(kind, fact_id, candidate.label, detail, round(conf, 4),
                         value=candidate.value)


def learn(text: str, *, source: str = "user") -> LearningResult:
    """Haupt-Lernschleife: extrahieren, verstärken, korrigieren, Themen zählen."""
    events: list[LearningEvent] = []
    topics = keywords(text, limit=5) if text else []

    if text and FORGET_VERBS.search(text):
        events.extend(forget_by_query(text))
        if events:
            _bump_topics(topics)
            return LearningResult(events, topics)

    candidates = extract_candidates(text)
    if not candidates:
        _bump_topics(topics)
        return LearningResult(events, topics)

    with db.db() as conn:
        for cand in candidates:
            existing = db.row_to_dict(conn.execute("SELECT * FROM facts WHERE key=?", (cand.key,)).fetchone())
            if existing and existing["status"] == "active" and _same_value(existing.get("value"), cand.value):
                # Gleiche Aussage erneut -> Vertrauen steigt (Verstärkung)
                events.append(_reinforce(conn, existing, cand))
                _bump_topics([stem(w) for w in cand.value.split()[:2]])
                continue

            # Widerspruch? Gleiche Kategorie mit Einzelwert-Charakter -> korrigieren
            superseded_id = None
            touched_ids = {e.fact_id for e in events if e.fact_id is not None}
            unique_hint = cand.key.split(":", 1)[1] in {
                "name", "spitzname", "wohnort", "alter", "arbeitgeber", "rolle",
                "anrede", "antwortstil", "emojis", "system",
            }
            if cand.category in SINGLE_VALUE_CATEGORIES and unique_hint:
                rivals = db.rows_to_dicts(
                    conn.execute(
                        """SELECT * FROM facts WHERE category=? AND status='active'
                           AND key LIKE ? AND key != ?""",
                        (cand.category, f"{cand.category}:{cand.key.split(':', 1)[1]}%", cand.key),
                    ).fetchall()
                )
                for rival in rivals:
                    if rival["key"] != cand.key and rival["id"] not in touched_ids:
                        new_conf = max(config.CONFIDENCE_MIN,
                                       rival["confidence"] - config.CONFIDENCE_PENALTY)
                        conn.execute(
                            """UPDATE facts SET status='superseded', key=?, confidence=?, updated_at=?
                               WHERE id=?""",
                            (f"{rival['key']}~alt-{rival['id']}", round(new_conf, 4),
                             db.now_iso(), rival["id"]),
                        )
                        conn.execute(
                            "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
                            ("corrected", rival["id"], f"ersetzt durch: {cand.label}", db.now_iso()),
                        )
                        superseded_id = rival["id"]
                        events.append(
                            LearningEvent("corrected", rival["id"], rival["label"],
                                          f"verworfen – neue Aussage: {cand.label}",
                                          round(new_conf, 4), value=rival.get("value") or "")
                        )

            if existing:
                value_conflict = not _same_value(existing.get("value"), cand.value)
                if existing["status"] == "active" and value_conflict:
                    # Gleicher Schlüssel, anderer Wert -> echte Korrektur.
                    # Die Historie bleibt erhalten, nur der eindeutige Schlüssel
                    # wird „entschärft“, damit der neue Fakt ihn übernehmen kann.
                    new_conf = max(config.CONFIDENCE_MIN,
                                   existing["confidence"] - config.CONFIDENCE_PENALTY)
                    conn.execute(
                        """UPDATE facts SET status='superseded', key=?, confidence=?, updated_at=?
                           WHERE id=?""",
                        (f"{existing['key']}~alt-{existing['id']}", round(new_conf, 4),
                         db.now_iso(), existing["id"]),
                    )
                    conn.execute(
                        "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
                        ("corrected", existing["id"], f"ersetzt durch: {cand.label}", db.now_iso()),
                    )
                    events.append(
                        LearningEvent("corrected", existing["id"], existing["label"],
                                      f"alter Wert „{existing.get('value')}“ ersetzt durch „{cand.value}“",
                                      round(new_conf, 4), value=cand.value)
                    )
                    superseded_id = superseded_id or existing["id"]
                elif value_conflict:
                    # Vergessener/alter Eintrag mit anderem Wert -> Platz machen
                    conn.execute("DELETE FROM facts WHERE id=?", (existing["id"],))
            events.append(_insert(conn, cand, superseded_id))

    _bump_topics(topics)
    return LearningResult(events, topics)


def confirm(fact_id: int | None = None, *, all_facts: bool = False) -> list[LearningEvent]:
    """Nutzer bestätigt Erinnerungen -> Vertrauen steigt deutlich."""
    events: list[LearningEvent] = []
    with db.db() as conn:
        if all_facts:
            rows = db.rows_to_dicts(conn.execute("SELECT * FROM facts WHERE status='active'").fetchall())
        else:
            row = db.row_to_dict(conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone())
            rows = [row] if row else []
        for fact in rows:
            new_conf = min(config.CONFIDENCE_MAX, fact["confidence"] + config.CONFIDENCE_CONFIRM)
            conn.execute("UPDATE facts SET confidence=?, updated_at=? WHERE id=?",
                         (round(new_conf, 4), db.now_iso(), fact["id"]))
            conn.execute(
                "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
                ("confirmed", fact["id"], "durch Nutzer bestätigt", db.now_iso()),
            )
            events.append(LearningEvent("confirmed", fact["id"], fact["label"],
                                        f"bestätigt, Vertrauen {new_conf:.0%}", round(new_conf, 4),
                                        value=fact.get("value") or ""))
    return events


def update_fact(fact_id: int, *, label: str | None = None, value: str | None = None,
                confidence: float | None = None) -> dict[str, Any] | None:
    """Manuelle Korrektur durch den Nutzer (voll transparent)."""
    with db.db() as conn:
        fact = db.row_to_dict(conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone())
        if not fact:
            return None
        conn.execute(
            """UPDATE facts SET label=COALESCE(?, label), value=COALESCE(?, value),
                      confidence=COALESCE(?, confidence), updated_at=? WHERE id=?""",
            (label, clean_value(value) if value else None,
             None if confidence is None else max(config.CONFIDENCE_MIN, min(config.CONFIDENCE_MAX, confidence)),
             db.now_iso(), fact_id),
        )
        conn.execute(
            "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
            ("corrected", fact_id, "manuell vom Nutzer bearbeitet", db.now_iso()),
        )
        return db.row_to_dict(conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone())


def delete_fact(fact_id: int) -> bool:
    with db.db() as conn:
        conn.execute("UPDATE facts SET status='forgotten', confidence=?, updated_at=? WHERE id=?",
                     (config.CONFIDENCE_MIN, db.now_iso(), fact_id))
        conn.execute(
            "INSERT INTO learning_events(kind, fact_id, detail, created_at) VALUES(?,?,?,?)",
            ("forgotten", fact_id, "manuell gelöscht", db.now_iso()),
        )
    return True


def _bump_topics(topics: Iterable[str]) -> None:
    now = db.now_iso()
    with db.db() as conn:
        for topic in topics:
            topic = topic.strip()
            if not topic or topic in STOPWORD_SUBJECTS:
                continue
            conn.execute(
                "INSERT INTO topics(topic, hits, last_seen_at) VALUES(?, 1, ?) "
                "ON CONFLICT(topic) DO UPDATE SET hits=topics.hits+1, last_seen_at=excluded.last_seen_at",
                (topic, now),
            )


# ---------------------------------------------------------------------------
# Abruf (Retrieval)
# ---------------------------------------------------------------------------

def apply_decay() -> int:
    """Sanftes Vergessen: lange nicht genutzte Fakten verlieren Vertrauen."""
    now = datetime.now(timezone.utc)
    changed = 0
    with db.db() as conn:
        rows = db.rows_to_dicts(conn.execute("SELECT * FROM facts WHERE status='active'").fetchall())
        for fact in rows:
            ref = fact.get("last_recalled_at") or fact["updated_at"]
            try:
                ref_dt = datetime.fromisoformat(ref)
            except (TypeError, ValueError):
                continue
            days = max(0.0, (now - ref_dt).total_seconds() / 86400.0)
            if days < 7:
                continue
            new_conf = fact["confidence"] - config.CONFIDENCE_DECAY_PER_DAY * days
            if new_conf < 0.20:
                conn.execute("UPDATE facts SET status='forgotten', confidence=?, updated_at=? WHERE id=?",
                             (round(config.CONFIDENCE_MIN, 4), db.now_iso(), fact["id"]))
            else:
                conn.execute("UPDATE facts SET confidence=?, updated_at=? WHERE id=?",
                             (round(new_conf, 4), db.now_iso(), fact["id"]))
            changed += 1
    return changed


def _fact_haystack(fact: dict[str, Any]) -> str:
    """Alles, was über einen Fakt bekannt ist – inklusive Schlüsselbegriffen."""
    key = (fact.get("key") or "").replace(":", " ").replace("-", " ")
    value = fact.get("value") or ""
    return f"{fact.get('label', '')} {value} {key}"


def _fact_text(fact: dict[str, Any]) -> str:
    """Nur die menschenlesbare Aussage (ohne Kategorie-/Schlüssel-Metadaten)."""
    return f"{fact.get('label', '')} {fact.get('value') or ''}"


# Grammatische Füll- und Negationswörter: wichtig für die *Aussage*, aber nicht
# für das Matching – sonst findet „Was mag ich?“ die Abneigung „Mag nicht: Kaffee“
# nicht, weil „nicht“ in der Frage fehlt.
_MATCH_NOISE = {
    "nicht", "kein", "keine", "keinen", "keinem", "keiner", "nix", "nie",
    "no", "not", "never", "dont", "don", "t",
    "bin", "bist", "ist", "sind", "war", "waren", "am", "is", "are", "be",
}


_NEGATION_WORDS = {
    "nicht", "kein", "keine", "keinen", "keinem", "keiner", "nie", "nichts",
    "no", "not", "never", "don't", "dont", "dislike", "hate",
}


# Begriffe, die zwar passen, aber zu allgemein für eine Lösch-Entscheidung sind
_GENERIC_MATCH_TOKENS = set(CATEGORY_LABELS) | {
    "lieblings", "liebling", "mag", "nicht", "kein", "keine", "nutzer", "wert",
    "vorlieben", "abneigungen", "identitaet", "beziehungen", "umgebung",
    "favorite", "like", "user", "value",
}


def specific_token_hit(query: str, fact: dict[str, Any]) -> bool:
    """Trifft die Anfrage einen *konkreten* Begriff des Fakts (Wert oder Schlüssel)?

    Verhindert, dass „Vergiss meinen Lieblingseditor“ auch den Lieblingskaffee
    löscht – beide teilen sich das allgemeine Wort „Lieblings-“.
    """
    key = (fact.get("key") or "").replace(":", " ").replace("-", " ")
    specific = {
        t for t in content_tokens(f"{fact.get('value') or ''} {key}")
        if t not in _GENERIC_MATCH_TOKENS and len(t) >= 4
    }
    if not specific:
        return False
    q_tokens = content_tokens(query)
    q_pool = q_tokens | {base_form(t) for t in q_tokens} | expand_synonyms(q_tokens)
    for token in specific:
        for q in q_pool:
            if token == q:
                return True
            if len(q) >= 4 and (token.startswith(q) or q.startswith(token)):
                return True
            if len(q) >= 5 and len(token) >= 4 and (q in token or token in q):
                return True
    return False


def token_hit(query: str, text: str) -> bool:
    """Trifft ein Begriff der Anfrage den Text (exakt, Synonym, Präfix, Teilwort)?"""
    q_tokens = content_tokens(query)
    t_tokens = content_tokens(text)
    if not q_tokens or not t_tokens:
        return False
    if q_tokens & t_tokens:
        return True
    q_pool = q_tokens | expand_synonyms(q_tokens) | {base_form(t) for t in q_tokens}
    t_pool = t_tokens | {base_form(t) for t in t_tokens}
    if q_pool & t_pool:
        return True
    for q in q_tokens:
        for t in t_tokens:
            if len(q) >= 4 and len(t) >= 4 and (q.startswith(t) or t.startswith(q)):
                return True
            if len(q) >= 5 and len(t) >= 5 and (q in t or t in q):
                return True
    return False


def _has_negation(text: str) -> bool:
    return bool(_NEGATION_WORDS & set(tokenize(text, keep_stopwords=True)))


def _match_tokens(tokens: set[str]) -> set[str]:
    """Entfernt Füll-/Negationswörter – behält aber alles, wenn sonst nichts bliebe."""
    filtered = tokens - _MATCH_NOISE
    return filtered or set(tokens)


def _token_match(token: str, base: str, q_raw: set[str], q_base: set[str],
                 q_syn: set[str]) -> float:
    """Bestes Signal für ein einzelnes Token des Fakts (0..1).

    exakt > Synonym/Wortform > Präfix/Flexion > Teilwort (Kompositum).
    """
    if token in q_raw:
        return 1.0
    if token in q_syn or base in q_syn:
        return 0.85
    forms = word_forms(token)
    if forms:
        if forms & q_raw:
            return 0.85
        if forms & q_base or {base_form(f) for f in forms} & q_base:
            return 0.78
    if len(base) >= 3:
        for other in q_base:
            if len(other) >= 3 and (base.startswith(other) or other.startswith(base)):
                return 0.62
    if len(token) >= 4:
        for other in q_raw | q_base:
            if len(other) >= 4 and other != token and (other in token or token in other):
                return 0.55
    return 0.0


def _avg_tokens(tokens: set[str], pool_raw: set[str], pool_syn: set[str]) -> float:
    """Umgekehrte Richtung: wie viele der `tokens` finden sich in `pool_raw`?"""
    if not tokens:
        return 0.0
    pool_base = {base_form(t) for t in pool_raw}
    total = 0.0
    for token in tokens:
        total += _token_match(token, base_form(token), pool_raw, pool_base, pool_syn)
    return total / len(tokens)


def relevance(query: str, fact_text: str) -> float:
    """Relevanz einer Anfrage für einen Fakt (0..1).

    Jeder Inhaltstreffer des Fakts wird einzeln bewertet, der Durchschnitt ergibt
    die Abdeckung. Bewertet wird gegen die Aussage *und* gegen die Aussage
    inklusive Schlüsselbegriff – das Maximum gewinnt, damit Kategorie-Schlüssel
    („wohnort“) helfen, lange Schlüssel aber nichts verwässern.
    """
    q_raw = content_tokens(query)
    if not q_raw:
        return 0.0
    q_base = {base_form(t) for t in q_raw}
    q_syn = (expand_synonyms(q_raw) | expand_synonyms(q_base)
             | set().union(*(word_forms(t) for t in q_raw)) if q_raw else set())

    all_raw = content_tokens(fact_text)
    if not all_raw:
        return 0.0
    parts = fact_text.split()
    text_raw = content_tokens(" ".join(parts[:-1])) if len(parts) > 2 else all_raw

    q_match = _match_tokens(q_raw)
    q_base_match = _match_tokens(q_base)

    def avg(raw_tokens: set[str]) -> float:
        """Abdeckung der Fakt-Inhalte (ohne Füll-/Negationswörter) durch die Anfrage."""
        tokens = _match_tokens(raw_tokens)
        if not tokens:
            tokens = raw_tokens
        if not tokens:
            return 0.0
        total = 0.0
        for token in tokens:
            total += _token_match(token, base_form(token), q_match, q_base_match, q_syn)
        return total / len(tokens)

    f_syn = expand_synonyms(all_raw) | expand_synonyms({base_form(t) for t in all_raw})

    coverage = max(avg(all_raw), avg(text_raw))

    # Negations-Abgleich: passt die Verneinung der Anfrage zur Aussage?
    if _has_negation(query) != _has_negation(fact_text):
        coverage *= 0.55

    # Bei kurzen Anfragen („Was mag ich nicht?“) zählt zusätzlich, wie viel von
    # der Anfrage im Fakt wiederzufinden ist – sonst verwässern lange Aussagen.
    if len(q_match) <= 2:
        query_coverage = _avg_tokens(q_match, all_raw, f_syn)
        coverage = max(coverage, 0.6 * coverage + 0.4 * query_coverage)

    return round(min(1.0, 0.82 * coverage + 0.18 * similarity(query, fact_text)), 4)


def recall(query: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Liefert die passendsten Erinnerungen inkl. Relevanz-Score."""
    limit = limit or config.RECALL_LIMIT
    if not query.strip():
        return []
    with db.db() as conn:
        facts = db.rows_to_dicts(conn.execute("SELECT * FROM facts WHERE status='active'").fetchall())

    scored: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for fact in facts:
        rel = relevance(query, _fact_haystack(fact))
        if rel <= 0.02:
            continue
        freshness = 1.0
        try:
            ref = fact.get("last_recalled_at") or fact["updated_at"]
            days = (now - datetime.fromisoformat(ref)).total_seconds() / 86400.0
            freshness = 1.0 / (1.0 + max(0.0, days) / 30.0)
        except (TypeError, ValueError):
            pass
        score = 0.66 * rel + 0.22 * fact["confidence"] + 0.12 * freshness
        score += min(0.07, 0.015 * fact["times_learned"])
        if score >= config.RECALL_MIN_SCORE:
            scored.append({**fact, "score": round(score, 4), "relevance": round(rel, 4)})

    scored.sort(key=lambda f: f["score"], reverse=True)
    top = scored[:limit]

    # Abruf zählt: verstärkt Fakten langfristig (Spacing-Effekt)
    if top:
        ids = [f["id"] for f in top]
        with db.db() as conn:
            conn.executemany(
                "UPDATE facts SET times_recalled=times_recalled+1, last_recalled_at=? WHERE id=?",
                [(db.now_iso(), i) for i in ids],
            )
    return top


def recall_profile(limit: int = 12) -> list[dict[str, Any]]:
    """Wichtigste Fakten unabhängig von einer Anfrage (für Selbstauskunft)."""
    with db.db() as conn:
        rows = db.rows_to_dicts(
            conn.execute(
                """SELECT * FROM facts WHERE status='active'
                   ORDER BY confidence DESC, times_learned DESC, updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        )
    return rows


def _public(fact: dict[str, Any]) -> dict[str, Any]:
    """Bereinigt interne Schlüssel-Suffixe für die Anzeige/API."""
    out = dict(fact)
    if out.get("key"):
        out["key"] = out["key"].split("~alt-")[0]
    return out


def all_facts(status: str | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM facts"
    params: tuple[Any, ...] = ()
    if status and status != "all":
        query += " WHERE status=?"
        params = (status,)
    query += " ORDER BY status='active' DESC, confidence DESC, updated_at DESC"
    with db.db() as conn:
        return [_public(f) for f in db.rows_to_dicts(conn.execute(query, params).fetchall())]


def search_facts(q: str) -> list[dict[str, Any]]:
    with db.db() as conn:
        facts = db.rows_to_dicts(conn.execute("SELECT * FROM facts WHERE status='active'").fetchall())
    hits = []
    for fact in facts:
        score = relevance(q, _fact_haystack(fact))
        if score >= 0.10:
            hits.append({**fact, "score": round(score, 4)})
    hits.sort(key=lambda f: f["score"], reverse=True)
    return hits


def stats() -> dict[str, Any]:
    with db.db() as conn:
        by_status = {
            row["status"]: row["n"]
            for row in conn.execute("SELECT status, COUNT(*) n FROM facts GROUP BY status").fetchall()
        }
        agg = db.row_to_dict(
            conn.execute(
                """SELECT COALESCE(AVG(confidence),0) avg_conf,
                          COALESCE(SUM(times_learned),0) learned_total,
                          COALESCE(SUM(times_recalled),0) recalled_total,
                          COALESCE(MAX(times_learned),0) strongest,
                          COUNT(*) n
                   FROM facts WHERE status='active'"""
            ).fetchone()
        ) or {}
        categories = db.rows_to_dicts(
            conn.execute(
                """SELECT category, COUNT(*) n FROM facts WHERE status='active'
                   GROUP BY category ORDER BY n DESC"""
            ).fetchall()
        )
        top_topics = db.rows_to_dicts(
            conn.execute("SELECT topic, hits, last_seen_at FROM topics ORDER BY hits DESC, last_seen_at DESC LIMIT 8").fetchall()
        )
        events = db.rows_to_dicts(
            conn.execute(
                """SELECT le.kind, le.fact_id, le.detail, le.created_at, f.label
                   FROM learning_events le LEFT JOIN facts f ON f.id=le.fact_id
                   ORDER BY le.id DESC LIMIT 15"""
            ).fetchall()
        )
        messages = db.row_to_dict(
            conn.execute("SELECT COUNT(*) n FROM messages").fetchone()
        ) or {"n": 0}

    active = by_status.get("active", 0)
    strongest = agg.get("strongest", 0)
    # „Lernfortschritt“ als lesbare Kennzahl für die UI
    mastery = 0.0
    if active:
        mastery = min(1.0, (float(agg.get("avg_conf", 0)) * 0.6) + (min(strongest, 10) / 10.0) * 0.4)

    return {
        "facts_active": active,
        "facts_superseded": by_status.get("superseded", 0),
        "facts_forgotten": by_status.get("forgotten", 0),
        "facts_total": sum(by_status.values()),
        "avg_confidence": round(float(agg.get("avg_conf", 0)), 4),
        "learned_total": int(agg.get("learned_total", 0)),
        "recalled_total": int(agg.get("recalled_total", 0)),
        "strongest_fact_repetitions": int(strongest),
        "messages_total": int(messages.get("n", 0)),
        "mastery": round(mastery, 3),
        "categories": [
            {**c, "label": CATEGORY_LABELS.get(c["category"], c["category"])} for c in categories
        ],
        "top_topics": top_topics,
        "recent_events": events,
        "generated_at": db.now_iso(),
    }


def reset_memory(*, keep_prefs: bool = False) -> None:
    """Kompletter Gedächtnis-Reset (Datenschutz: „alles löschen“)."""
    with db.db() as conn:
        conn.execute("DELETE FROM facts")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM topics")
        conn.execute("DELETE FROM learning_events")
        if not keep_prefs:
            conn.execute("DELETE FROM prefs")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('facts','messages','learning_events')")
