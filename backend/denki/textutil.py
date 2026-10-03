"""Sehr kleine, locale NLP-Hilfsmittel.

Bewusst ohne externe Modelle: Stoppwörter, Normalisierung und Token-Ähnlichkeit
reichen für die Gedächtnis-Schicht völlig aus und halten Denki offline-fähig.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

# Deutsche + englische Stoppwörter (gekürzt, aber praxistauglich)
STOPWORDS = {
    # deutsch
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "einer", "eines", "und", "oder", "aber", "als", "wie", "wenn", "dann",
    "ich", "du", "er", "sie", "es", "wir", "ihr", "mein", "meine", "meinen",
    "meiner", "meinem", "dein", "deine", "ist", "sind", "war", "waren", "bin",
    "bist", "sei", "hat", "habe", "haben", "hatte", "hatten", "wird", "werden",
    "wurde", "würde", "kann", "können", "muss", "müssen", "will", "wollen",
    "mögen", "gern", "gerne", "sehr", "auch", "noch", "schon", "mal",
    "bitte", "danke", "hallo", "hi", "hey", "jo", "ok", "okay", "ja", "nein",
    "nicht", "kein", "keine", "keinen", "mit", "ohne", "auf", "aus", "bei",
    "für", "gegen", "in", "im", "an", "am", "zu", "zum", "zur", "von", "vom",
    "vor", "nach", "über", "unter", "zwischen", "weil", "dass", "denn",
    "doch", "hier", "dort", "heute", "morgen", "gestern", "immer", "nie",
    "oft", "manchmal", "vielleicht", "wirklich", "einfach", "so", "was",
    "wer", "wo", "wann", "warum", "wie", "welche", "welcher", "welches",
    "diese", "dieser", "dieses", "jene", "man", "sich", "uns", "euch", "ihnen",
    "denki", "weiß", "weiss", "kennst", "kennen", "weißt", "weisst",
    # englisch
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "for", "with", "without", "at", "by", "from",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her",
    "our", "their", "this", "that", "these", "those", "do", "does", "did",
    "have", "has", "had", "will", "would", "can", "could", "should", "am",
    "not", "no", "yes", "so", "as", "if", "then", "than", "there", "here",
}

_TOKEN_RE = re.compile(r"[\wäöüßÄÖÜ]+", re.UNICODE)
# Wörter, die getrennt geschrieben genauso gemeint sind („Lieblings-Editor“)
_HYPHEN_RE = re.compile(r"[-–—_/+]+", re.UNICODE)


def normalize(text: str) -> str:
    """Kleinbuchstaben, Unicode glätten, überflüssige Leerzeichen entfernen."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str, keep_stopwords: bool = False) -> list[str]:
    """Zerlegt Text in Tokens; optional ohne Stoppwörter.

    Bindestriche, Unterstriche, Schräg- und Plusstriche gelten als Trenner,
    damit „Lieblings-Editor“ und „Lieblingseditor“ dieselben Tokens liefern.
    """
    tokens = [t for t in _TOKEN_RE.findall(_HYPHEN_RE.sub(" ", normalize(text)))]
    if keep_stopwords:
        return tokens
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


_SAFE_SUFFIXES = ("chen", "lein", "ungen", "heit", "keit", "schaft", "end", "ern",
                  "ing", "ies", "en", "er", "es", "st", "e", "s", "n")


def stem(token: str) -> str:
    """Sehr konservatives Stemming (eine Endung, Mindestlänge).

    Wichtig: Der Stamm dient nur der *Anzeige* (Themenliste, Schlüssel).
    Für das Matching nutzt Denki Roh-Tokens plus Präfix-Vergleich, weil deutsches
    Stemming sonst „Arbeitgeber“ und „arbeitet“ auseinanderreißt.
    """
    t = normalize(token).replace("ß", "ss")
    for suffix in _SAFE_SUFFIXES:
        if len(t) - len(suffix) >= 4 and t.endswith(suffix):
            return t[: -len(suffix)]
    return t


_INFLECTION_SUFFIXES = ("etest", "est", "st", "test", "en", "et", "te", "em", "er",
                        "es", "n", "t", "e", "s")


def base_form(token: str) -> str:
    """Reduziert ein Wort auf seine Vergleichsform (Flexionsendung weg).

    „wohne“/„wohnst“/„wohnt“ -> „wohn“, „arbeitet“ -> „arbeit“.
    Das ist absichtlich *kein* echtes Stemming, sondern nur die Basis für den
    Präfix-Vergleich – damit „wohn“ auf „wohnort“ und „arbeit“ auf
    „arbeitgeber“ trifft.
    """
    t = normalize(token).replace("ß", "ss")
    for suffix in _INFLECTION_SUFFIXES:
        if len(t) - len(suffix) >= 3 and t.endswith(suffix):
            return t[: -len(suffix)]
    return t


def content_tokens(text: str) -> set[str]:
    """Inhaltstragende Tokens im Rohzustand (Basis für das Matching).

    Flexion wird über Präfix-Vergleiche und `word_forms` abgedeckt, nicht über
    Stemming – das ist bei deutschen Komposita deutlich robuster. Besteht ein
    Text nur aus Stoppwörtern („Wer bin ich?“), greift das Sicherheitsnetz und
    alle Tokens zählen.
    """
    raw = [normalize(t).replace("ß", "ss") for t in tokenize(text, keep_stopwords=True)]
    meaningful = {t for t in raw if t not in STOPWORDS and len(t) > 1}
    return meaningful or set(raw)


def prefix_overlap(a: str, b: str, min_len: int = 4) -> bool:
    """True, wenn ein Token das Präfix des anderen ist („wohnt“ ~ „wohnort“)."""
    if not a or not b or a == b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= min_len and long.startswith(short)


def shared_prefixes(left: set[str], right: set[str], min_len: int = 4) -> int:
    """Zählt Präfix-Treffer zwischen zwei Token-Mengen (jedes Token zählt einmal)."""
    hits = 0
    for token in left:
        if any(prefix_overlap(token, other, min_len) for other in right):
            hits += 1
    return hits


def keywords(text: str, limit: int = 12) -> list[str]:
    """Häufigste Inhaltswörter – genutzt für Themen-Statistik und Suche."""
    counts = Counter(stem(t) for t in tokenize(text))
    return [word for word, _ in counts.most_common(limit)]


def similarity(a: str, b: str) -> float:
    """Jaccard-ähnliche Token-Überlappung (0..1), mit Teilwort-Bonus.

    Substring-Treffer werden berücksichtigt, damit z. B. „Python“ auch bei
    „Python-Entwicklung“ greift.
    """
    ta, tb = content_tokens(a), content_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    score = len(inter) / len(ta | tb)

    # Bonus: Präfix-/Teilwort-Treffer („wohnt“ ~ „wohnort“, „Python“ ~ „Python-Projekt“)
    partial = shared_prefixes(ta, tb)
    partial += sum(1 for x in ta for y in tb
                   if x != y and len(x) >= 5 and len(y) >= 5 and (x in y or y in x))
    if partial:
        score += min(0.3, 0.07 * partial)
    return min(1.0, score)


def levenshtein(a: str, b: str) -> int:
    """Editierdistanz – um zu erkennen, ob zwei Werte „fast gleich“ sind."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


_LEADING_FILLER_RE = re.compile(
    r"^(?:(?:einen?|eine|eines|einer|einem|mein(?:e|en|er)?|dein(?:e|en|er)?|"
    r"aktuell|gerade|jetzt|heute|morgen|immer|noch|auch|sehr|ziemlich|total|einfach|bitte|"
    r"the|a|an|my|currently|right\s+now|today|really)\s+)+",
    re.I,
)

_TRAILING_FILLER_RE = re.compile(
    r"[,;:\s]\s*(?:und|aber|oder|weil|dass|wenn|dann|denn|doch|während|waehrend)"
    r"\s+(?:ich|du|wir|sie|ihr|mein\w*|dein\w*|es|man|er|es\s+gibt|"
    r"i|we|you|my|they|it|that|he|she)\b"
    r"(?:\s+[\w'-]+){0,2}"
    r"\s*(?:\b(?:bin|heiße|heisse|wohne|lebe|arbeite|nutze|verwende|mache|habe|will|möchte|moechte|"
    r"plane|lerne|mag|liebe|hasse|suche|brauche|denke|finde|spiele|lese|höre|hoere|trinke|esse|fahre)\b|"
    r"\b(?:am|work|live|use|like|love|hate|prefer|need|want|study|learn|build|running|based)\b).*$",
    re.I,
)

# „… Köln und arbeite im Homeoffice“ -> Nebensatz ohne Subjekt ebenfalls kappen
_TRAILING_CLAUSE_RE = re.compile(
    r"\s+(?=(?:und|aber|oder|sowie)\s+[\wäöüßÄÖÜ]*(?:arbeite|wohne|lebe|heiße|heisse|bin|nutze|"
    r"verwende|mache|habe|will|möchte|moechte|plane|lerne|mag|liebe|hasse|spiele|lese|höre|hoere|"
    r"trinke|esse|fahre|gehe|komme|suche|brauche|denke|finde)\b).*$",
    re.I,
)

# Eingestreuter Artikel nach einer Zeitangabe („Freitag um 10 Uhr einen Termin“)
_INNER_ARTICLE_RE = re.compile(
    r"(\d{1,2}(?:[:.]\d{2})?\s*(?:uhr)?|\b(?:montag|dienstag|mittwoch|donnerstag|freitag|"
    r"samstag|sonntag|heute|morgen|übermorgen)\b)\s+(?:einen?|eine|eines|meinen?|meine)\s+",
    re.I,
)

# Einzelne Bindewörter am Ende („Dennis Großer und“)
_TRAILING_CONJ_RE = re.compile(r"\s+(?:und|oder|aber|and|or|but|sowie|,)$", re.I)


def clean_value(value: str) -> str:
    """Bereinigt einen extrahierten Wert.

    Entfernt Satzzeichen, führende Artikel/Füllwörter und schneidet alles ab,
    was hinter einem Bindewort folgt („Ich heiße Anna und wohne in Köln“
    -> Wert „Anna“ statt „Anna und wohne in Köln“).
    """
    v = (value or "").strip()
    v = re.sub(r"\s+", " ", v)
    # Satzende-Zeichen entfernen, aber nicht den Punkt eines Initials („Dennis C.“)
    while v and re.search(r"[!?,;:-]$", v):
        v = v[:-1].rstrip()
    while v.endswith("."):
        head = v[:-1].rstrip()
        if re.search(r"(?:^|\s)[\wäöüßÄÖÜ]$", head):   # einzelner Buchstabe = Initial
            break
        v = head

    v = _TRAILING_FILLER_RE.sub("", v).strip()

    for filler in (
        " und ich", " aber ich", " weil ich", " dass ich", " wenn ich",
        " and i", " but i", " because i",
    ):
        idx = v.lower().find(filler)
        if idx > 2:
            v = v[:idx].strip()

    v = _TRAILING_CLAUSE_RE.sub("", v).strip()
    v = _INNER_ARTICLE_RE.sub(r"\1 ", v).strip()
    v = _LEADING_FILLER_RE.sub("", v).strip()
    v = _TRAILING_FILLER_RE.sub("", v).strip()
    v = _TRAILING_CONJ_RE.sub("", v).strip()

    # Punkte nur dann kappen, wenn es kein Initial ist („Dennis C. Großer“ bleibt)
    while v:
        if re.search(r"(?:^|\s)[\wäöüßÄÖÜ]\.?$", v):
            break
        v = re.sub(r"[\s.!?,;:-]+$", "", v).strip()
        v = _TRAILING_CONJ_RE.sub("", v).strip()
        if not re.search(r"[.!?,;:-]$", v):
            break
    return v[:240]


# ---------------------------------------------------------------------------
# Synonyme (lokal, kuratiert) – helfen bei Abruf und Vergessens-Anfragen
# ---------------------------------------------------------------------------

SYNONYMS: dict[str, tuple[str, ...]] = {
    "arbeitgeber": ("arbeit", "job", "firma", "beruf", "unternehmen", "company", "employer",
                    "taetigkeit", "beruflich"),
    "arbeit": ("job", "arbeitgeber", "firma", "beruf", "taetigkeit", "projekt", "beruflich"),
    "job": ("arbeit", "arbeitgeber", "firma", "beruf", "beruflich"),
    "firma": ("arbeitgeber", "arbeit", "unternehmen"),
    "beruf": ("arbeit", "arbeitgeber", "rolle", "taetigkeit", "beruflich", "job"),
    "beruflich": ("beruf", "arbeit", "arbeitgeber", "job", "taetigkeit"),
    "rolle": ("beruf", "arbeit", "taetigkeit", "job"),
    "name": ("heissen", "identitaet", "vorname", "nachname", "nutzer", "ich", "wer"),
    "nutzer": ("ich", "name", "identitaet", "user", "wer"),
    "identitaet": ("ich", "name", "nutzer", "wer"),
    "wohnort": ("wohnen", "leben", "stadt", "zuhause", "heimat", "adresse"),
    "stadt": ("wohnort", "wohnen"),
    "adresse": ("wohnort", "wohnen"),
    "editor": ("ide", "werkzeug", "programm"),
    "sprache": ("sprechen", "programmiersprache"),
    "termin": ("kalender", "meeting", "verabredung", "appointment"),
    "kalender": ("termin", "meeting"),
    "vorliebe": ("mögen", "lieblings", "gerne", "favorit", "mag", "liebe"),
    "lieblings": ("mögen", "vorliebe", "favorit", "mag", "liebling", "gerne"),
    "liebling": ("lieblings", "vorliebe", "mag"),
    "abneigung": ("hassen", "nicht", "stoert", "mag nicht"),
    "editor": ("ide", "werkzeug", "programm", "vscode", "code"),
    "kaffee": ("getränk", "trinken", "espresso", "tee"),
    "ziel": ("plan", "vorhaben", "wunsch", "traum"),
    "hardware": ("rechner", "pc", "laptop", "gpu", "ram", "grafikkarte"),
    "system": ("betriebssystem", "windows", "linux", "os"),
    "familie": ("frau", "mann", "kind", "tochter", "sohn", "partner"),
    "haustier": ("tier", "pet", "haustiere"),
    "anrede": ("duzen", "siezen", "du", "sie"),
    "projekt": ("bauen", "entwickeln", "arbeit"),
}


_SYNONYM_INDEX: dict[str, set[str]] = {}


def _build_synonym_index() -> dict[str, set[str]]:
    """Baut einen bidirektionalen, gestemmten Synonym-Index (lazy, einmalig)."""
    if _SYNONYM_INDEX:
        return _SYNONYM_INDEX
    for key, values in SYNONYMS.items():
        raw = {normalize(key).replace("ß", "ss")} | {
            normalize(v).replace("ß", "ss") for v in values
        }
        group = raw | {base_form(w) for w in raw}
        for member in group:
            _SYNONYM_INDEX.setdefault(member, set()).update(group)
    for member, group in list(_SYNONYM_INDEX.items()):
        _SYNONYM_INDEX[member] = group - {member}
    return _SYNONYM_INDEX


def expand_synonyms(tokens: set[str], limit: int = 16) -> set[str]:
    """Liefert zusätzliche, bedeutungsverwandte Tokens (ohne die Originale)."""
    index = _build_synonym_index()
    extra: set[str] = set()
    for token in tokens:
        extra |= index.get(token, set())
    return set(list(extra - tokens)[:limit])


# ---------------------------------------------------------------------------
# Wortform-Klassen: verbinden flektierte Formen, die kein gemeinsames Präfix
# mehr haben („bin“ ~ „ich“, „mag“ ~ „mögen“). Klein und kuratiert.
# ---------------------------------------------------------------------------

FORM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ich", "bin", "am", "i", "wer", "mich", "mir", "mein", "me"),
    ("du", "bist", "you", "are"),
    ("er", "sie", "es", "ist", "he", "she", "it", "is"),
    ("wir", "sind", "we"),
    ("mag", "mögen", "moegen", "like", "lieb", "liebe", "gern", "gerne"),
    ("heißt", "heissen", "name", "namen", "called"),
    ("wohnt", "wohnen", "wohn", "leben", "lebt", "zuhause", "live"),
    ("arbeitet", "arbeiten", "arbeit", "job", "beruf"),
    ("nutzt", "nutzen", "verwendet", "verwenden", "tool", "werkzeug", "use"),
    ("lernt", "lernen", "learn"),
    ("hat", "haben", "have"),
    ("termin", "termine", "kalender", "meeting", "appointment", "date"),
    ("projekt", "projekte", "project"),
    ("ziel", "ziele", "plan", "plaene", "goal"),
    ("editor", "editoren", "ide"),
    ("kaffee", "coffee", "espresso"),
    ("nicht", "kein", "keine", "keinen", "never", "no", "hate", "hasse"),
)

_FORM_INDEX: dict[str, set[str]] = {}


def _build_form_index() -> dict[str, set[str]]:
    if _FORM_INDEX:
        return _FORM_INDEX
    for group in FORM_GROUPS:
        forms = set()
        for word in group:
            raw = normalize(word).replace("ß", "ss")
            forms |= {raw, base_form(raw)}
        for member in forms:
            _FORM_INDEX.setdefault(member, set()).update(forms)
    for member, group in list(_FORM_INDEX.items()):
        _FORM_INDEX[member] = group - {member}
    return _FORM_INDEX


def word_forms(token: str) -> set[str]:
    """Bekannte Wortformen/Synonyme eines Tokens (inkl. Vergleichsform)."""
    index = _build_form_index()
    base = base_form(token)
    return index.get(token, set()) | index.get(base, set())
