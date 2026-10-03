# Denki

**Denki – lokale, mitlernende KI für Windows.** Erfunden von Dennis C. Großer · GroTeck

> [!NOTE]
> **Experiment, nicht Denki 2.0.** Dieser Branch enthält einen Web-Prototyp, der als Versuch
> entstanden ist. Er lernt automatisch aus jeder Aussage und unterscheidet sich damit vom
> eigentlichen Denki. Das echte Denki (Windows-Programm) gibt es unter
> [Releases](https://github.com/dcgrosi/Denki-App/releases/latest).

Denki ist eine KI, die dem Nutzer gehört: Sie läuft vollständig auf dem eigenen Rechner,
lernt aus jedem Gespräch dazu und macht ihr Gedächtnis sichtbar, korrigierbar und löschbar.
Kein Konto, keine Cloud, keine Telemetrie.

> **Status:** lauffähiger Prototyp (v0.1) – FastAPI-Backend mit echter Gedächtnis-/Lernschicht,
> Web-UI und austauschbarem KI-Backend (MockBrain offline, optional lokales LLM via Ollama).

---

## Schnellstart

```bash
# 1) Abhängigkeiten (einmalig)
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS
pip install -r requirements.txt

# 2) Starten
python run.py                   # UI: http://127.0.0.1:8000 · API-Doku: /api/docs
```

Optionale Flags:

| Flag | Wirkung |
| --- | --- |
| `--brain auto\|mock\|ollama` | KI-Backend wählen (Standard `auto`: Ollama wenn lokal verfügbar, sonst Mock) |
| `--ollama-model llama3.1` | Modell für lokale Inferenz |
| `--port 8000` | Port (Standard `8000`) |
| `--host 127.0.0.1` | Bind-Adresse. Standard: nur dieser Rechner. `0.0.0.0` öffnet Denki **ohne Passwort** für alle Geräte im Netzwerk (Start-Warnung) |
| `--data-dir <pfad>` | Ort der Gedächtnis-Datenbank (z. B. `%APPDATA%\Denki`) |
| `--reload` | Auto-Reload während der Entwicklung |

Tests:

```bash
pytest -q          # 47 Tests: Extraktion, Verstärkung, Korrektur, Vergessen, API
```

Terminal-Demo ohne Browser:

```bash
python scripts/demo.py
```

---

## Was Denki kann

1. **Merkwürdig gut erinnern** – Namen, Wohnort, Arbeit, Projekte, Vorlieben, Abneigungen,
   Ziele, Termine, Menschen/Haustiere, Hardware und System.
2. **Mitlernen** – jede Aussage wird extrahiert; Wiederholungen erhöhen das Vertrauen,
   Widersprüche ersetzen den alten Fakt (mit Historie).
3. **Vergessen auf Zuruf** – „Vergiss meinen Lieblingseditor“ löscht genau diesen Eintrag,
   nicht den Lieblingskaffee. Dazu kommt sanftes Zeit-Decay für ungenutzte Erinnerungen.
4. **Kontext nutzen** – Antworten werden aus dem Gedächtnis belegt (inkl. Relevanz-Anzeige),
   statt zu raten.
5. **Sich anpassen** – Du/Sie, kurze oder ausführliche Antworten, mit oder ohne Emojis.
6. **Transparent bleiben** – das Gedächtnis-Panel zeigt jeden Fakt mit Vertrauen,
   Lernhäufigkeit, Abrufzahl und Quelle; Bearbeiten, Bestätigen und Löschen sind möglich.

---

## Architektur

```
Denki-App/
├── run.py                     Startskript (CLI, Banner, Uvicorn)
├── backend/denki/
│   ├── config.py              Pfade, Lern-Parameter, Backend-Wahl
│   ├── db.py                  SQLite-Schema & Zugriff (Facts, Sessions, Events, Topics, Prefs)
│   ├── textutil.py            Tokenizer, Normalisierung, Ähnlichkeit, Synonyme, Wortformen
│   ├── memory.py              ★ Gedächtnis: Extraktion, Verstärkung, Korrektur, Vergessen, Abruf
│   ├── intents.py             Regelbasierte Intent-Erkennung (DE/EN)
│   ├── brain.py               MockBrain (offline) + OllamaBrain (lokal), Profil-Dekorierung
│   ├── conversation.py        Sitzungen und Nachrichten
│   └── main.py                FastAPI-App (REST + statische UI)
├── frontend/static/           UI ohne Build-Schritt: index.html, styles.css, app.js, fonts/
├── scripts/demo.py            Dialog-Demo im Terminal
└── tests/                     pytest-Suiten (Gedächtnis, Gehirn, API, Lernqualität)
```

**Datenfluss einer Nachricht**

```
Nutzer-Text
  → Intent bestimmen            (intents.classify)
  → Vergessens-Befehl?          (memory.forget_by_query)
  → Gedächtnis-Abruf            (memory.recall → Relevanz-Score)
  → Lernen                      (memory.learn → extrahiert / verstärkt / korrigiert)
  → Antwort erzeugen            (MockBrain oder OllamaBrain, inkl. gelernter Vorlieben)
  → Persistieren                (messages, learning_events, topics)
  → UI-Update                   (Chips, Gedächtnis-Panel, Lern-Log, Stats)
```

---

## Wie das Mitlernen funktioniert

Jeder Fakt lebt in `facts` mit `key`, `category`, `label`, `value`, `source_text`,
`confidence`, `status` (`active` / `superseded` / `forgotten`), `times_learned`,
`times_recalled` und `supersedes` (Provenienz).

**1. Extraktion** – rund 25 Regeln erkennen Aussagen, z. B.
`Ich heiße …`, `Ich wohne in …`, `Ich arbeite bei …`, `Ich bin <Rolle>`,
`Mein Lieblings-X ist …`, `Ich mag (nicht) …`, `Ich möchte …`, `Ich lerne …`,
`Ich habe am <Tag> um <Zeit> …`, `Meine Frau heißt …`, `Ich habe einen Hund namens …`,
`Ich nutze Windows 11`, `Sieze mich`, `Antworte kurz`, `Keine Emojis`.
Zwei Durchläufe: voller Satz und zusätzlich Satzteile ohne Subjekt, damit
„Ich heiße Anna und arbeite bei Siemens“ **beide** Fakten liefert.

**2. Verstärkung** – gleiche Aussage erneut → `times_learned += 1`,
`confidence += 0.20` (gedeckelt bei 0.97).

**3. Korrektur** – neuer Wert für denselben Schlüssel oder dieselbe Einzelwert-Kategorie
→ alter Fakt wird `superseded` (Vertrauen −0.35), neuer Fakt verweist via `supersedes`
darauf. Die Historie bleibt erhalten, nichts wird stillschweigend überschrieben.

**4. Vergessen** – Befehl („vergiss …“, „lösche …“) oder Klick im Panel → Status
`forgotten`. Zusätzlich: `apply_decay()` reduziert Vertrauen für Erinnerungen, die
länger als 7 Tage nicht abgerufen wurden.

**5. Abruf** – Relevanz je Fakt aus
`Abdeckung` (exakt 1.0 > Synonym/Wortform 0.85 > Präfix/Flexion 0.62 > Teilwort 0.55),
`Negations-Abgleich`, `Jaccard-Ähnlichkeit`, `Vertrauen` und `Frische`:

```
score = 0.66 · relevance + 0.22 · confidence + 0.12 · freshness + Lern-Bonus
```

Deutsche Flexion und Komposita werden ohne ML gelöst: `wohnt ~ Wohnort`,
`arbeitet ~ Arbeitgeber`, `Lieblingseditor ~ Lieblings-Editor`. Kuratierte
Synonym- und Wortform-Gruppen (`textutil.SYNONYMS`, `FORM_GROUPS`) decken
`Arbeitgeber ~ Arbeit/Job/Firma` oder `mag ~ mögen/like` ab.

---

## REST-API

| Methode & Pfad | Zweck |
| --- | --- |
| `GET /api/health` | Status, aktives Backend, Ollama-Verfügbarkeit, DB-Pfad |
| `POST /api/chat` | `{message, session_id?}` → Antwort, Intent, Recall, Lern-Ereignisse, Stats |
| `GET /api/facts?status=&q=` | Erinnerungen listen/suchen |
| `GET/PATCH/DELETE /api/facts/{id}` | Fakt lesen, bearbeiten, vergessen |
| `POST /api/confirm/{id}` · `POST /api/confirm` | Vertrauen durch Bestätigung erhöhen |
| `POST /api/learn` | Text gezielt lernen (ohne Chat) |
| `POST /api/forget` | `{query}` → gezielt vergessen |
| `POST /api/memory/reset` | Gedächtnis vollständig löschen |
| `GET /api/stats` | Kennzahlen, Kategorien, Themen, letzte Lern-Ereignisse |
| `GET /api/events` | Lern-Protokoll |
| `GET/POST/DELETE /api/sessions…` | Gesprächsverlauf |
| `GET/PUT /api/prefs` | Lokale Einstellungen |

Interaktive Doku: `http://127.0.0.1:8000/api/docs`

---

## Echte lokale Inferenz (optional)

Der Prototyp antwortet mit `MockBrain` – deterministisch und offline, aber bereits
voll an das Gedächtnis angebunden. Für echte Sprachmodelle:

```bash
# Ollama installieren (Windows: Installer von ollama.com), dann
ollama pull llama3.1
python run.py --brain auto      # erkennt Ollama automatisch
```

`OllamaBrain` baut denselben Gedächtnis-Kontext in den System-Prompt ein
(inkl. gelernter Anrede/Antwortstil) und fällt bei Problemen automatisch auf
`MockBrain` zurück. **Das Gedächtnis lernt backend-unabhängig** – der Wechsel
des Modells verändert nichts am Lernverhalten.

---

## Datenschutz

* Alle Daten liegen in einer lokalen SQLite-Datei (`data/denki.sqlite3`, per
  `DENKI_DATA_DIR` verschiebbar, z. B. nach `%APPDATA%\Denki`).
* Keine externen Aufrufe außer einem optionalen, lokalen Ollama-Endpunkt (`127.0.0.1`).
  Auch die Schriften (Inter, JetBrains Mono, SIL OFL 1.1) liegen lokal in `frontend/static/fonts/`.
* Der Server lauscht standardmäßig nur auf `127.0.0.1` – andere Geräte im Netzwerk erreichen
  Denki nicht. Erst `--host 0.0.0.0` öffnet ihn bewusst (ohne Anmeldung, daher mit Warnung).
* Jede Erinnerung ist im UI einsehbar, bearbeitbar, bestätigbar und löschbar.
* „Gedächtnis leeren“ entfernt Fakten, Verlauf, Themen und Lern-Protokoll vollständig.

---

## Nächste Schritte (Roadmap)

- [ ] Windows-Desktop-Shell (Tauri/Electron) mit Tray-Icon und Autostart
- [ ] Streaming-Antworten (SSE) statt Tipp-Animation
- [ ] Vektor-Embeddings lokal (z. B. `sentence-transformers`) zusätzlich zur Regel-Ähnlichkeit
- [ ] Verschlüsselung der Gedächtnis-Datei (SQLCipher) + Export/Import
- [ ] Proaktive Erinnerungen („Du wolltest Freitag zum Zahnarzt“)
- [ ] Plugin-Schnittstelle für lokale Aktionen (Dateien, Kalender, Zwischenablage)
- [ ] Packaging als `Denki-Setup.exe` mit Signatur

---

© Dennis C. Großer · GroTeck
