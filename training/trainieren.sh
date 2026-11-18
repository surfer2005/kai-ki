#!/bin/bash
# KAI KI nachtrainieren — Trainingsdatei aus KAI (Administration → KI → Training → „Beispiele herunterladen“).
# Beispiel: ./trainieren.sh ~/Downloads/kai-ki-training-2026-11-18.jsonl
# Weitere Schalter: ./trainieren.sh --help
set -euo pipefail
ORDNER="${KAI_KI_ORDNER:-$HOME/Library/Application Support/KAI-KI}"
T="$ORDNER/training"
HIER="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$T/venv-mlx/bin/python" ]; then
  echo "Erst einrichten: $HIER/einrichten.sh"; exit 1
fi
# caffeinate: der Mac schläft während des Trainings nicht ein (Deckel offen lassen, Netzteil anschließen)
if command -v caffeinate >/dev/null; then
  exec caffeinate -i "$T/venv-mlx/bin/python" "$HIER/trainieren.py" "$@"
fi
exec "$T/venv-mlx/bin/python" "$HIER/trainieren.py" "$@"
