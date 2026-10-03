# Denki

**Denki – lokale, mitlernende KI für Windows.** Erfunden von Dennis C. Großer · GroTeck
Ausgearbeitet mit Kimi, Opus und Luna

Denki merkt sich, was du ihr sagst – aber nur, wenn du „ja“ sagst. Alles bleibt auf deinem PC.

## Download

**[Denki 2.0 herunterladen](https://github.com/dcgrosi/Denki-App/releases/latest)** · Windows 10 oder 11 (64 Bit)

| Datei | Größe | SHA-256 |
| --- | --- | --- |
| `Denki-Installation-2.exe` | ca. 23 MB | `505e8157e383e3829d8127891e71088aac7a2c4a8b0a401d18303f695259ba30` |

## Installation

1. `Denki-Installation-2.exe` herunterladen und starten
2. Falls Windows warnt („Unbekannter Herausgeber“): „Weitere Informationen“ → „Trotzdem ausführen“
3. Denki liegt danach auf dem Desktop
4. Beim ersten Start fragt Denki nach deinem Namen

## Virenprüfung

[VirusTotal-Bericht](https://www.virustotal.com/gui/file/505e8157e383e3829d8127891e71088aac7a2c4a8b0a401d18303f695259ba30)

Stand 02.10.2026: 2 von 71 Scannern melden einen Verdacht (Trapmine, Zillya). Microsoft Defender
und die anderen großen Scanner melden nichts. Solche Einzelmeldungen sind bei Python-Programmen,
die mit PyInstaller gepackt sind, häufig Fehlalarme.

## Sprachmodell (freiwillig)

Ohne Sprachmodell versteht Denki feste Sätze („hilfe“ zeigt sie). Mit Sprachmodell versteht Denki
auch freie Sätze und kann plaudern.

Entwickelt mit: [Boldt-1B-IT-Preview](https://huggingface.co/Boldt/Boldt-1B-IT-Preview) – deutsches
Sprachmodell der Humboldt-Universität zu Berlin (Lizenz: Apache 2.0)

Das Modell ist nicht enthalten. So kommt es dazu:

1. [GGUF-Datei herunterladen](https://huggingface.co/flozen1981/boldt-1b-it-preview-gguf/resolve/main/boldt-1b-it-preview-Q4_K_M.gguf)
   (ca. 740 MB, umgewandelt von flozen1981 – nicht vom Hersteller)
2. In Denki auf „Modell“ klicken und die Datei wählen

Andere GGUF-Modelle funktionieren grundsätzlich auch.
Antworten des Sprachmodells (grau) können falsch sein und werden nie gespeichert.

## Datenschutz

Denki selbst verschickt keine Daten. Das Sprachmodell läuft nur auf deinem PC.

## Voraussetzungen

Windows 10 oder 11 (64 Bit). Startet das Sprachmodell nicht: „Microsoft Visual C++ Redistributable (x64)“
von Microsoft installieren.

## Deinstallieren

Windows → Einstellungen → Apps → Denki. Dein Gedächtnis bleibt dabei erhalten.

## Lizenzen

Denki enthält freie Bauteile (Python, Tcl/Tk, SQLite, llama.cpp, LLVM OpenMP). Die Lizenztexte liegen
im Installationsordner in `LIZENZEN.txt`.

Kostenlos und ohne Gewähr. Nutzung auf eigene Verantwortung.

---

Hinweis: Der Branch [`web-prototyp`](https://github.com/dcgrosi/Denki-App/tree/web-prototyp) enthält einen
Web-Prototyp, der als Experiment entstanden ist. Er ist nicht Denki 2.0.
