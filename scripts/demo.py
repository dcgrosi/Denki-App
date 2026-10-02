#!/usr/bin/env python3
"""Denki-Demo im Terminal – zeigt das Mitlernen ohne Browser.

    python scripts/demo.py                # läuft in einer temporären Demo-Datenbank
    python scripts/demo.py --eigene-db    # schreibt ins echte Gedächtnis (data/)
    python scripts/demo.py --interaktiv   # danach selbst tippen

Standardmäßig nutzt das Skript eine Wegwerf-Datenbank, damit die Demo nichts am
echten Gedächtnis verändert.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

DEMO_DIALOG = [
    "Hallo Denki!",
    "Ich heiße Dennis C. Großer und arbeite bei GroTeck.",
    "Ich wohne in Köln und nutze Windows 11.",
    "Mein Lieblingseditor ist VS Code, aber ich mag keinen Kaffee.",
    "Ich möchte Denki als Windows-Desktop-App veröffentlichen.",
    "Sieze mich bitte und antworte kurz.",
    "Hallo!",
    "Was weißt du über mich?",
    "Wie heißt mein Arbeitgeber?",
    "Wo wohne ich?",
    "Ich heiße Dennis Großer.",                 # Korrektur -> Historie bleibt
    "Vergiss meinen Lieblingseditor.",          # gezieltes Vergessen
    "Duz mich wieder und antworte ausführlich.",
    "Zeig mir alle Erinnerungen.",
]

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="Denki-Demo im Terminal")
    parser.add_argument("--eigene-db", action="store_true",
                        help="echtes Gedächtnis (data/denki.sqlite3) statt Temp-DB verwenden")
    parser.add_argument("--interaktiv", action="store_true",
                        help="nach der Demo selbst Nachrichten tippen")
    parser.add_argument("--brain", default=os.environ.get("DENKI_BRAIN", "auto"))
    args = parser.parse_args()

    if not args.eigene_db:
        temp_dir = tempfile.mkdtemp(prefix="denki-demo-")
        os.environ["DENKI_DATA_DIR"] = temp_dir
        os.environ["DENKI_DB"] = str(Path(temp_dir) / "demo.sqlite3")
    os.environ["DENKI_BRAIN"] = args.brain

    from denki import config, db, memory
    from denki.brain import get_brain

    db.init_db()
    memory.reset_memory()
    brain = get_brain()

    print(f"{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║  Denki – lokale, mitlernende KI für Windows                  ║{RESET}")
    print(f"{BOLD}{CYAN}║  erfunden von Dennis C. Großer · GroTeck                     ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════════╝{RESET}")
    print(f"{DIM}Backend: {brain.name} · Gedächtnis: {config.DB_PATH}{RESET}\n")

    for line in DEMO_DIALOG:
        print(f"{BOLD}Du:{RESET} {line}")
        result = brain.chat(line)
        print(f"{CYAN}Denki:{RESET} {result.text}")

        events = (result.meta.get("learning") or {}).get("events") or []
        icons = {"extracted": f"{GREEN}+ gelernt{RESET}", "reinforced": f"{YELLOW}↑ verstärkt{RESET}",
                 "corrected": f"{YELLOW}✎ korrigiert{RESET}", "forgotten": "\033[31m– vergessen\033[0m",
                 "confirmed": f"{GREEN}✓ bestätigt{RESET}"}
        for event in events:
            print(f"  {DIM}└─ {icons.get(event['kind'], event['kind'])}: "
                  f"{event['label']} ({event.get('detail', '')}){RESET}")
        if result.recalled:
            hits = ", ".join(f"{f['label']} {f['score']:.0%}" for f in result.recalled[:3])
            print(f"  {DIM}└─ erinnert: {hits}{RESET}")
        print()

    stats = memory.stats()
    print(f"{BOLD}Gedächtnis-Stand:{RESET} {stats['facts_active']} aktive Erinnerungen · "
          f"{stats['facts_superseded']} ersetzt · {stats['facts_forgotten']} vergessen · "
          f"Ø Vertrauen {stats['avg_confidence']:.0%} · Lernfortschritt {stats['mastery']:.0%}")
    print(f"{DIM}Kategorien: " + ", ".join(f"{c['label']} ({c['n']})" for c in stats["categories"]) + RESET)

    if args.interaktiv:
        print(f"\n{BOLD}Interaktiver Modus – 'exit' zum Beenden:{RESET}")
        while True:
            try:
                text = input(f"{BOLD}Du:{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() in {"exit", "quit", "ende", ""}:
                break
            print(f"{CYAN}Denki:{RESET} {brain.chat(text).text}\n")


if __name__ == "__main__":
    main()
