#!/bin/bash
# Einmal auf dem Trainingsrechner (Mac mit Apple-Chip): Umgebungen für das Training (mlx-lm) und für die Umwandlung
# ins App-Format (llama.cpp) anlegen. Danach: ./trainieren.sh <Trainingsdatei aus KAI>.
# Lädt aus dem Netz: Python-Pakete (mlx-lm, Abhängigkeiten des Umwandlers) und den Quelltext von llama.cpp.
# Das Grundmodell (ca. 18 GB) lädt erst das Training beim ersten Lauf.
set -euo pipefail
ORDNER="${KAI_KI_ORDNER:-$HOME/Library/Application Support/KAI-KI}"
T="$ORDNER/training"
MLX_LM_VERSION="0.32.2"
RUECKFALL_TAG="b12473"          # wie das Rechenprogramm der App, falls sie noch keins geladen hat

if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  echo "Das Training läuft nur auf einem Mac mit Apple-Chip (M1–M4)."
  [ -n "${KAI_KI_TEST:-}" ] || exit 1
fi

PY=""
for p in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$p" >/dev/null && "$p" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then PY=$(command -v "$p"); break; fi
done
if [ -z "$PY" ]; then
  echo "Python ab 3.10 fehlt. Am einfachsten über Homebrew: brew install python@3.12 — dann erneut ./einrichten.sh"
  exit 1
fi
echo "▶ Python: $PY ($("$PY" --version))"
mkdir -p "$T"

echo "▶ Umgebung für das Training (mlx-lm $MLX_LM_VERSION)"
[ -x "$T/venv-mlx/bin/python" ] || "$PY" -m venv "$T/venv-mlx"
"$T/venv-mlx/bin/pip" install -q --upgrade pip
if [ -n "${KAI_KI_TEST:-}" ] && [ "$(uname -s)" != Darwin ]; then "$T/venv-mlx/bin/pip" install -q "mlx[cpu]"; fi   # nur Prüflauf unter Linux
"$T/venv-mlx/bin/pip" install -q "mlx-lm==$MLX_LM_VERSION"

TAG=$(cat "$ORDNER/llama/version.txt" 2>/dev/null || true)
TAG=${TAG:-$RUECKFALL_TAG}
if [ "$(cat "$T/llama.cpp/.kai-tag" 2>/dev/null || true)" != "$TAG" ]; then
  echo "▶ Umwandler aus llama.cpp $TAG (gleiche Version wie das Rechenprogramm der App)"
  rm -rf "$T/llama.cpp" "$T/llama.cpp.tar.gz"
  curl -fsSL --retry 3 -o "$T/llama.cpp.tar.gz" "https://github.com/ggml-org/llama.cpp/archive/refs/tags/$TAG.tar.gz"
  mkdir -p "$T/llama.cpp"
  tar -xzf "$T/llama.cpp.tar.gz" -C "$T/llama.cpp" --strip-components 1
  rm -f "$T/llama.cpp.tar.gz"
  echo "$TAG" > "$T/llama.cpp/.kai-tag"
fi

echo "▶ Umgebung für die Umwandlung"
[ -x "$T/venv-gguf/bin/python" ] || "$PY" -m venv "$T/venv-gguf"
"$T/venv-gguf/bin/pip" install -q --upgrade pip
( cd "$T/llama.cpp" && "$T/venv-gguf/bin/pip" install -q -r requirements/requirements-convert_hf_to_gguf.txt )

echo
echo "✔ Eingerichtet in $T"
if ! find "$ORDNER/llama" -name llama-quantize -type f 2>/dev/null | grep -q .; then
  echo "  Noch zu tun: die App „KAI KI“ einmal mit dem Grundmodell starten — sie lädt das Rechenprogramm (llama.cpp) und den Bildteil."
fi
echo "  Weiter mit: ./trainieren.sh ~/Downloads/kai-ki-training-….jsonl"
