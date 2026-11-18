# KAI KI nachtrainieren („Weg 3“)

Macht aus den gesammelten Beispielen in KAI ein eigenes Modell **„KAI angepasst“**, das die App „KAI KI“ wie jedes
andere Modell startet. Die KI lernt dabei, **welche Abfrage zu welcher Frage gehört und wie eine gute Antwort aussieht** —
nicht die Zahlen selbst, die fragt sie weiter bei KAI ab.

## Was man braucht

- Mac mit Apple-Chip, **ab 32 GB Arbeitsspeicher** (dann volle Genauigkeit). Mit 16–24 GB geht es mit dem
  4-Bit-Grundmodell — langsamer und etwas ungenauer, das Skript wählt das selbst.
- rund 60 GB freier Platz (Grundmodell 18 GB, Zwischenstände, Ergebnis 6 GB)
- Python ab 3.10 (z. B. `brew install python@3.12`)
- die App „KAI KI“, einmal mit dem Grundmodell „Qwen3.5 9B“ gestartet (sie lädt das Rechenprogramm llama.cpp und den
  Bildteil, den das eigene Modell mitbenutzt)

## Ablauf

1. **Beispiele in KAI sammeln:** Administration → KI → Protokoll — Antworten klären und „für Training freigeben“
   (schlechte nur mit korrigierter Antwort). Dazu kommen automatisch Abfrage-Beispiele aus dem Systemcheck.
2. **Trainingsdatei holen:** Administration → KI → Training → „Beispiele herunterladen“ (`kai-ki-training-….jsonl`).
3. **Einmal einrichten** (lädt mlx-lm und den Umwandler aus llama.cpp):
   ```
   ./einrichten.sh
   ```
4. **Trainieren** (20–90 Minuten, Netzteil anschließen; der Mac schläft solange nicht ein):
   ```
   ./trainieren.sh ~/Downloads/kai-ki-training-2026-11-18.jsonl
   ```
   Schritte: prüfen und aufteilen (10 % zur Kontrolle) → Fehlerwert vorher → Training → Fehlerwert nachher →
   zusammenführen (Gelerntes auf die Original-Gewichte) → ins App-Format (GGUF, 4 Bit) → ablegen als `modelle/kai-eigen.gguf`.
5. **In der App** „KAI angepasst (eigenes Training, Stand …)“ wählen und starten.
6. **In KAI vergleichen:** Administration → KI → Systemcheck → „Mit Modell prüfen“ — mit dem letzten Lauf des
   Grundmodells vergleichen. Schlechter? In der App wieder „Qwen3.5 9B“ wählen; das vorige eigene Modell liegt als
   `kai-eigen-vorher.gguf` daneben.

Weitere Schalter: `./trainieren.sh --help` (z. B. `--laenge 4096` bei Speicherfehler, `--iters`, `--basis`).

## Datenschutz

Die Trainingsdatei enthält Fragen aus dem Haus samt den Daten, die KAI dazu geliefert hat. Sie bleibt auf diesem Mac:
nichts davon wird hochgeladen (geladen werden nur Programme und das öffentliche Grundmodell). Nach dem Training die
Datei löschen. Die Zwischenstände liegen unter `~/Library/Application Support/KAI-KI/training/lauf-…` und können
ebenfalls gelöscht werden.

## Technik

- Training: [mlx-lm](https://github.com/ml-explore/mlx-lm) 0.32.2, LoRA auf 16 Schichten, nur die Antworten werden
  gelernt (`--mask-prompt`), Grundmodell `Qwen/Qwen3.5-9B` bzw. `mlx-community/Qwen3.5-9B-4bit`
- Zusammenführen: `zusammenfuehren.py` rechnet das Gelernte (LoRA) auf die **Original**-Gewichte (W + scale·Bᵀ·Aᵀ) —
  bewusst nicht `mlx_lm fuse`: das speichert bei Qwen3.5 die Normen umgerechnet (1 + w), und nach der Umwandlung antwortete
  das Modell nur Unsinn. Beim 4-Bit-Grundmodell wird dafür einmal das Original (ca. 19 GB) geladen.
- Umwandlung: `convert_hf_to_gguf.py` und `llama-quantize` aus llama.cpp in der Version der App
- Die App startet das eigene Modell mit `-m kai-eigen.gguf --mmproj <Bildteil des Grundmodells>`
- Probelauf der ganzen Kette am 2026-11-18 unter Linux mit dem kleinen `Qwen/Qwen3.5-0.8B` (gleicher Aufbau): Fehlerwert
  3,05 → 1,64 nach 4 Schritten, Ergebnis lädt mit dem Bildteil des Grundmodells und liest ein Bildschirmfoto richtig
