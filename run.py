#!/usr/bin/env python3
"""Denki starten.

    python run.py                 # http://127.0.0.1:8000
    python run.py --port 8080
    python run.py --brain mock    # Mock-KI erzwingen (Standard: auto -> Ollama wenn verfügbar)

Voraussetzung:  pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

# Nur diese Adressen halten Denki auf dem eigenen Rechner
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Denki – lokale, mitlernende KI")
    parser.add_argument("--host", default=os.environ.get("DENKI_HOST") or "127.0.0.1",
                        help="Bind-Adresse (Standard: 127.0.0.1 = nur dieser Rechner; "
                             "0.0.0.0 öffnet Denki ohne Passwort fürs ganze Netzwerk)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DENKI_PORT", "8000")))
    parser.add_argument("--reload", action="store_true", help="Auto-Reload für Entwicklung")
    parser.add_argument("--brain", choices=("auto", "mock", "ollama"),
                        default=os.environ.get("DENKI_BRAIN", "auto"),
                        help="KI-Backend (Standard: auto)")
    parser.add_argument("--ollama-model", default=os.environ.get("DENKI_OLLAMA_MODEL", "llama3.1"))
    parser.add_argument("--data-dir", default=os.environ.get("DENKI_DATA_DIR"))
    args = parser.parse_args()

    os.environ["DENKI_BRAIN"] = args.brain
    os.environ["DENKI_OLLAMA_MODEL"] = args.ollama_model
    if args.data_dir:
        os.environ["DENKI_DATA_DIR"] = args.data_dir

    import uvicorn

    from denki import config
    from denki.db import init_db

    init_db()
    config.ensure_dirs()

    print("=" * 68)
    print("  Denki – lokale, mitlernende KI für Windows")
    print("  erfunden von Dennis C. Großer · GroTeck")
    print("=" * 68)
    print(f"  UI:       http://127.0.0.1:{args.port}")
    print(f"  API-Doku: http://127.0.0.1:{args.port}/api/docs")
    print(f"  Gedächtnis: {config.DB_PATH}")
    print(f"  Backend:    {args.brain} (Ollama: {config.OLLAMA_URL}, Modell {args.ollama_model})")
    print("  Es werden keine Daten an externe Dienste übertragen.")
    if args.host not in LOOPBACK_HOSTS:
        print(f"  ACHTUNG: Bindung an {args.host} – andere Geräte im Netzwerk können")
        print("  Denki und das Gedächtnis ohne Passwort erreichen.")
    print("=" * 68)

    uvicorn.run("denki.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
