# KAI KI — eigene KI auf dem Mac

Liest Belegseiten (z. B. eingehende Lieferscheine) für KAI mit einem **Modell auf diesem Mac**. Die App holt die
Aufträge bei KAI ab (nur ausgehende Verbindung, eigener Schlüssel je Gerät) — die Belegbilder verlassen den Mac nicht.

## Einrichten
1. Release laden: <https://github.com/surfer2005/kai-ki/releases/latest> → `KAI-KI-macOS-….zip` entpacken, „KAI KI“ in
   *Programme* ziehen, beim ersten Öffnen **Rechtsklick → Öffnen** (nicht bei Apple signiert).
2. In KAI: *Einstellungen → Schnittstellen → KI* → Anbieter „Eigene KI auf einem Gerät“ → Name eintragen → **Gerät koppeln**.
3. In der App KAI-Adresse und Code eintragen → **Koppeln**. Beim ersten Start lädt die App das Rechenprogramm
   (llama.cpp, macOS arm64) und das Modell (Qwen2.5-VL, 3 bzw. 6 GB) — das dauert einmalig.

## Wie es arbeitet
- KAI legt je Seite einen Auftrag ab; die App holt ihn ab, macht aus dem PDF ein Bild (pdfium), liest den Text mit
  **Apples Texterkennung** (auf dem Gerät) und gibt Bild + Text an das Modell (llama.cpp, nur auf 127.0.0.1).
  Die Antwort (JSON) geht an KAI zurück; dort wird zerlegt, zugeordnet usw. wie mit der Cloud-KI.
- Fenster schließen = weiter im Hintergrund (Punkt in der Menüleiste: grün bereit, blau arbeitet, rot getrennt).
- Daten: `~/Library/Application Support/KAI-KI/` (Einstellungen mit Schlüssel nur für den Benutzer lesbar, Modelle, Protokoll).

## Entwickeln
Quelle liegt im KAI-Repo unter `edge/kai-ki/` und wird hierher gespiegelt. Release: Version in `kai_ki/__init__.py`
anheben, Tag `vX.Y.Z` pushen → GitHub baut die App (macOS arm64) und legt das Release an.
