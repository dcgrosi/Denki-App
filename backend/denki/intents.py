"""Intent-Erkennung für Denki (regelbasiert, offline, deterministisch).

Später kann hier problemlos ein lokales Klassifikationsmodell eingesetzt werden –
die Schnittstelle (`classify`) bleibt gleich.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .textutil import normalize

INTENTS = (
    "greeting", "farewell", "thanks", "confirm", "deny", "forget",
    "ask_memory", "list_memories", "ask_profile", "ask_identity",
    "ask_capabilities", "ask_help", "ask_time", "ask_mood", "ask_howdoing",
    "ask_local_privacy", "smalltalk", "statement", "question", "fallback",
)

GREETING = re.compile(
    r"^(?:hallo|hallowchen|hi|huhu|hey|hej|moin|servus|grüß\s+(?:dich|gott)|guten\s+(?:morgen|tag|abend|mittag)|good\s+(?:morning|evening|afternoon)|hello|yo|na\??)\b",
    re.I,
)
FAREWELL = re.compile(r"^(?:tschüss|tschuess|ciao|bye|adieu|bis\s+(?:später|spaeter|dann|bald|morgen)|gute\s+nacht|schluss\s+für\s+heute)\b", re.I)
THANKS = re.compile(r"\b(?:danke|dankeschön|dankeschoen|vielen\s+dank|merci|thx|thanks|thank\s+you)\b", re.I)
CONFIRM = re.compile(
    r"^(?:ja|jep|jupp|genau|stimmt|richtig|korrekt|exakt|jawohl|ok|okay|alles\s+klar|passt|sehr\s+gut|super|prima|yep|yes|yeah|correct|right|exactly)\b[\s.!]*$",
    re.I,
)
DENY = re.compile(
    r"^(?:nein|nö|noe|falsch|stimmt\s+nicht|nicht\s+richtig|quatsch|blödsinn|nope|no[,.!]|wrong|incorrect)\b",
    re.I,
)
FORGET = re.compile(r"\b(?:vergiss|vergiß|vergessen|lösche|loesche|entferne|streiche|forget|delete|remove)\b", re.I)
ASK_MEMORY = re.compile(
    r"(?:\bwas\s+weißt\s+du|\bwas\s+weisst\s+du|\bwas\s+hast\s+du\s+(?:dir\s+)?gemerkt|"
    r"\bwas\s+hast\s+du\s+gelernt|\berinnerst\s+du\s+dich|\bkennst\s+du\s+mein|"
    r"\bweißt\s+du\s+(?:noch|wie|wer|was|wo|ob)|\bwas\s+weißt\s+du\s+über\s+mich|"
    r"\b(?:weißt|weisst|erinnerst|merkst)\s+du.{0,24}\?$|"
    r"\b(?:wo|wann|wer|wie|was|welche[nrs]?|ob|woher|woran)\s+[\wäöüßÄÖÜ]+\s+"
    r"(?:ich|mein|meine|meinen|meiner|meinem)\b.{0,40}\?$|"
    r"\bwhat\s+do\s+you\s+(?:know|remember)|\bwhere\s+do\s+i\b|\bwho\s+am\s+i\b|"
    r"\bwhat\s+(?:is|s)\s+my\b)",
    re.I,
)
# Eigenaussage des Nutzers („Ich heiße …“, „Ich arbeite bei …“) – darf niemals
# als Frage nach Denkis Herkunft missverstanden werden.
SELF_STATEMENT = re.compile(
    r"\b(?:ich\s+(?:heiße|heisse|bin|arbeite|wohne|lebe|komme|nenne\s+mich)|"
    r"mein\s+name|my\s+name|i\s+am|i\s+work|i\s+live)\b",
    re.I,
)
LIST_MEMORIES = re.compile(r"\b(?:zeig(?:e)?\s+(?:mir\s+)?(?:alle\s+)?(?:erinnerungen|fakten|gedächtnis|memory)|was\s+kannst\s+du\s+alles\s+über\s+mich\s+sagen|list(?:e)?\s+(?:alle\s+)?(?:facts|memories)|alles\s+was\s+du\s+weißt)\b", re.I)
ASK_PROFILE = re.compile(r"\b(?:wer\s+bist\s+du|was\s+bist\s+du|wie\s+heißt\s+du|wie\s+heisst\s+du|stell\s+dich\s+vor|who\s+are\s+you|what\s+are\s+you)\b", re.I)
ASK_IDENTITY = re.compile(r"\b(?:wer\s+hat\s+dich\s+(?:erfunden|gemacht|entwickelt)|von\s+wem\s+bist\s+du|wer\s+steckt\s+hinter\s+dir|großer|groesser|groteck|dennis)\b", re.I)
ASK_CAPABILITIES = re.compile(r"\b(?:was\s+kannst\s+du|was\s+kannst\s+du\s+(?:alles|so)|welche\s+funktionen|hast\s+du\s+features|how\s+does\s+this\s+work|wie\s+funktionierst\s+du|kannst\s+du\s+(?:auch|mir)\s+helfen)\b", re.I)
ASK_HELP = re.compile(r"\b(?:hilfe|help|brauch(?:e)?\s+hilfe|unterstütz|wie\s+bedient\s+man|was\s+soll\s+ich\s+(?:sagen|tun))\b", re.I)
ASK_TIME = re.compile(r"\b(?:wie\s+spät|welcher\s+tag\s+ist|datum\s+heute|what\s+time|how\s+late)\b", re.I)
ASK_MOOD = re.compile(r"\b(?:wie\s+geht(?:'|e)?s\s+dir|wie\s+fühlst\s+du\s+dich|alles\s+gut\s+bei\s+dir|how\s+are\s+you)\b", re.I)
ASK_HOWDOING = re.compile(r"\b^(?:wie\s+geht(?:'s|s)?|na\?,?\s+alles\s+gut|und\s+selbst)\b", re.I)
ASK_LOCAL = re.compile(r"\b(?:lokal|local|offline|datenschutz|privacy|cloud|server|sicher|private|daten\s+weiter)\b", re.I)
QUESTION = re.compile(r"(\?\s*$|^(?:was|wer|wie|wo|wann|warum|wieso|weshalb|welche|welcher|welches|kann|kannst|könntest|koenntest|soll|ist|sind|hast|haben|do|does|is|are|can|could|what|who|where|when|why|how)\b)", re.I)
STATEMENT = re.compile(
    r"\b(?:ich\s+(?:bin|heiße|heisse|wohne|arbeite|mag|liebe|hasse|nutze|verwende|habe|will|möchte|moechte|plane|lerne|bevorzuge|brauche|muss|muß|denke|glaube|finde)|mein(?:e|en|er)?\s+\w+\s+(?:ist|sind|heißt|heisst|war|wurde)|i\s+(?:am|like|love|hate|use|have|want|need|prefer|work|live))\b",
    re.I,
)


@dataclass
class Intent:
    name: str
    confidence: float
    matched: str = ""

    def to_dict(self) -> dict[str, str | float]:
        return {"name": self.name, "confidence": round(self.confidence, 3), "matched": self.matched}


def _check(pattern: re.Pattern[str], text: str, name: str, conf: float) -> Intent | None:
    m = pattern.search(text)
    if m:
        return Intent(name, conf, m.group(0)[:40])
    return None


def classify(text: str) -> Intent:
    """Ordnet einer Äußerung genau einen Intent zu (höchste Priorität gewinnt)."""
    raw = (text or "").strip()
    t = normalize(raw)
    if not t:
        return Intent("fallback", 0.0)

    ordered = [
        (FORGET, "forget", 0.95),
        (LIST_MEMORIES, "list_memories", 0.9),
        (ASK_MEMORY, "ask_memory", 0.88),
        (ASK_IDENTITY, "ask_identity", 0.85),
        (ASK_PROFILE, "ask_profile", 0.85),
        (ASK_CAPABILITIES, "ask_capabilities", 0.85),
        (ASK_TIME, "ask_time", 0.8),
        (ASK_MOOD, "ask_mood", 0.8),
        (CONFIRM, "confirm", 0.82),
        (DENY, "deny", 0.8),
        (FAREWELL, "farewell", 0.78),
        (THANKS, "thanks", 0.7),
        (GREETING, "greeting", 0.75),
        (ASK_HELP, "ask_help", 0.7),
        (ASK_HOWDOING, "smalltalk", 0.5),
    ]
    for pattern, name, conf in ordered:
        # Herkunft/Autor nur beantworten, wenn wirklich gefragt wird
        if name == "ask_identity" and not raw.rstrip().endswith("?"):
            continue
        if name == "ask_identity" and SELF_STATEMENT.search(t):
            continue
        hit = _check(pattern, t, name, conf)
        if hit:
            return hit

    if STATEMENT.search(t):
        return Intent("statement", 0.6, "Aussage über dich")
    if ASK_LOCAL.search(t) and QUESTION.search(t):
        return Intent("ask_local_privacy", 0.6, "Datenschutz-Frage")
    if QUESTION.search(t):
        return Intent("question", 0.4, "Frage")
    if len(t.split()) <= 3:
        return Intent("smalltalk", 0.25, "Kurzäußerung")
    return Intent("statement", 0.3, "freie Äußerung")


def greeting_for_now() -> str:
    """Tageszeitabhängige Begrüßung – kleiner Lokalitätsgewinn."""
    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "Guten Morgen"
    if 11 <= hour < 18:
        return "Guten Tag"
    if 18 <= hour < 23:
        return "Guten Abend"
    return "Gute Nacht"
