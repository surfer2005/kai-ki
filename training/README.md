# KAI KI nachtrainieren („Weg 3“)

Das Training läuft in der App „KAI KI“ im Reiter **„Training“** — ohne Terminal. Die beiden Skripte in diesem Ordner
werden mit der App ausgeliefert (PyInstaller `--add-data training:training`, beim Bauen geprüft) und von ihr gestartet:

- `trainieren.py` — der Ablauf in sechs Schritten (prüfen und aufteilen → Fehlerwert vorher → Training → Fehlerwert nachher →
  zusammenführen → ins App-Format umwandeln und ablegen). Es schreibt Zeilen wie `▶ 3/6 …`, `Fehlerwert …`, `✔`/`✖`, aus denen die
  App ihren Fortschrittsbalken bildet (`kai_ki/training.py`, `zeile_auswerten()`).
- `zusammenfuehren.py` — rechnet das Gelernte (LoRA) auf die **Original**-Gewichte des Grundmodells.

## So geht es in der App

1. **Beispiele in KAI sammeln:** Administration → KI → Protokoll — Antworten klären und „für Training freigeben“
   (schlechte nur mit korrigierter Antwort). Dazu kommen automatisch Abfrage-Beispiele aus dem Systemcheck.
2. In der App, Reiter „Training“, einmal **Einrichten**. Die App legt wie beim Sprecher über uv eigene Python-Umgebungen an
   (mlx-lm für das Training, der Umwandler aus llama.cpp in der Version des Rechenprogramms). Das dauert einige Minuten, etwa 2 GB.
3. **Aus KAI holen:** Die App holt die Trainingsdatei über ihre Kopplung (`POST /api/ki-geraet/training`, in KAI im Audit).
   Alternativ „Stattdessen eine Datei wählen …“ mit der Datei aus Administration → KI → Training.
4. **Training starten** (20–90 Minuten, Netzteil anschließen). Die KI pausiert solange, der Mac schläft nicht ein.
   Beim ersten Mal lädt das Training das Grundmodell (ca. 19 GB).
5. **Angepasstes Modell verwenden**, dann in KAI unter Administration → KI → Systemcheck „Mit Modell prüfen“ und mit dem
   letzten Lauf des Grundmodells vergleichen. Schlechter? „Zurück zum Grundmodell“. Das vorige eigene Modell liegt als
   `kai-eigen-vorher.gguf` daneben.

Voraussetzungen: Mac mit Apple-Chip, am besten ab 32 GB Arbeitsspeicher (mit 16–24 GB nimmt das Training das 4-Bit-Grundmodell,
langsamer und etwas ungenauer), rund 60 GB frei. Die App einmal mit dem Grundmodell „Qwen3.5 9B“ gestartet haben — sie lädt dabei
das Rechenprogramm (llama.cpp, für `llama-quantize`) und den Bildteil, den das eigene Modell mitbenutzt.

## Datenschutz

Die Trainingsdaten enthalten Fragen aus dem Haus samt den Daten, die KAI dazu geliefert hat. Sie bleiben auf diesem Mac;
hochgeladen wird nichts (geladen werden nur Programme und das öffentliche Grundmodell). Nach einem erfolgreichen Training löscht die
App die geholten Daten, `trainieren.py` löscht die Kopien im Arbeitsordner (`~/Library/Application Support/KAI-KI/training/lauf-…`).

## Technik

- Training: [mlx-lm](https://github.com/ml-explore/mlx-lm) 0.32.2, LoRA auf 16 Schichten, nur die Antworten werden
  gelernt (`--mask-prompt`), Grundmodell `Qwen/Qwen3.5-9B` bzw. `mlx-community/Qwen3.5-9B-4bit`
- Zusammenführen: `zusammenfuehren.py` rechnet W + scale·Bᵀ·Aᵀ auf die Original-Gewichte — bewusst nicht `mlx_lm fuse`:
  das speichert bei Qwen3.5 die Normen umgerechnet (1 + w), und nach der Umwandlung antwortete das Modell nur Unsinn.
  Beim 4-Bit-Grundmodell wird dafür einmal das Original (ca. 19 GB) geladen.
- Umwandlung: `convert_hf_to_gguf.py` und `llama-quantize` (Q4_K_M) aus llama.cpp in der Version der App
- Die App startet das eigene Modell mit `-m kai-eigen.gguf --mmproj <Bildteil des Grundmodells>`
- Probelauf der ganzen Kette am 2026-11-18 unter Linux mit dem kleinen `Qwen/Qwen3.5-0.8B` (gleicher Aufbau): Fehlerwert
  3,05 → 0,30 nach 20 Schritten, Ergebnis lädt mit dem Bildteil des Grundmodells und liest ein Bildschirmfoto richtig
