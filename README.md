# KAI KI — eigene KI auf dem Mac

Liest Belegseiten (z. B. eingehende Lieferscheine) für KAI mit einem **Modell auf diesem Mac**. Die App holt die
Aufträge bei KAI ab (nur ausgehende Verbindung, eigener Schlüssel je Gerät) — die Belegbilder verlassen den Mac nicht.

## Einrichten
1. Release laden: <https://github.com/surfer2005/kai-ki/releases/latest> → `KAI-KI-macOS-….zip` entpacken, „KAI KI“ in
   *Programme* ziehen, beim ersten Öffnen **Rechtsklick → Öffnen** (nicht bei Apple signiert).
2. In KAI: *Einstellungen → Schnittstellen → KI* → Anbieter „Eigene KI auf einem Gerät“ → Name eintragen → **Gerät koppeln**.
3. In der App KAI-Adresse und Code eintragen → **Koppeln**. Beim ersten Start lädt die App das Rechenprogramm
   (llama.cpp, macOS arm64) und das gewählte Modell (Qwen3-VL 8B empfohlen, ca. 6 GB; außerdem Qwen3-VL 8B Q8, Qwen3.5 9B, Qwen2.5-VL 7B/3B) — das dauert einmalig. Jedes Modell liegt danach im Ordner `modelle`; nicht mehr gebrauchte lassen sich dort löschen.

## Wie es arbeitet
- KAI legt je Seite einen Auftrag ab; die App holt ihn ab, macht aus dem PDF ein Bild (pdfium), liest den Text mit
  **Apples Texterkennung** (auf dem Gerät) und gibt Bild + Text an das Modell (llama.cpp, nur auf 127.0.0.1).
  Die Antwort (JSON) geht an KAI zurück; dort wird zerlegt, zugeordnet usw. wie mit der Cloud-KI.
- Fenster schließen = weiter im Hintergrund (Punkt in der Menüleiste: grün bereit, blau arbeitet, rot getrennt).
- Daten: `~/Library/Application Support/KAI-KI/` (Einstellungen mit Schlüssel nur für den Benutzer lesbar, Modelle, Protokoll).

## Entwickeln
Quelle liegt im KAI-Repo unter `edge/kai-ki/` und wird hierher gespiegelt. Release: Version in `kai_ki/__init__.py`
anheben, Tag `vX.Y.Z` pushen → GitHub baut die App (macOS arm64) und legt das Release an.

## Abgebrochener Download (ab 0.1.6)

Bricht der Modell-Download ab (Netz), setzt llama.cpp beim nächsten Start am angefangenen Stück fort
(`*.downloadInProgress` im Modell-Ordner, HTTP-Range) — nichts wird doppelt geladen. Die App versucht das von selbst
bis zu sechsmal; die Anzeige zählt das schon Geladene mit und beginnt nicht wieder bei 0 %.

## Sprechen (ab 0.1.5)

Zweite Auftragsart: KAI schickt einen Text, die App macht daraus eine Tonspur (WAV) — für Erklärvideos und Filme.
Modell: **Chatterbox Multilingual** (Resemble AI, MIT-Lizenz, Deutsch). Weil PyTorch für die App zu groß ist, richtet die App
beim ersten Sprechauftrag eine eigene Umgebung ein (`~/Library/Application Support/KAI-KI/sprecher`): `uv` (Astral) →
Python 3.11 → `chatterbox-tts==0.1.7`, danach lädt der Sprecher-Dienst das Modell von Hugging Face (einige GB, einmalig).
Das dauert beim ersten Mal einige Minuten; der Stand steht in KAI in der Gerätezeile. Protokoll: `sprecher/sprecher.log`.
Stimmproben (10–30 s echte deutsche Sprache) liegen in KAI (Einstellungen → Schnittstellen → KI → Sprechen) und reisen mit
dem Auftrag; ohne Probe nimmt das Modell seine Standardstimme (im Deutschen evtl. mit englischem Klang).
