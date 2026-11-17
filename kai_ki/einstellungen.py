"""Einstellungen und Ablage der App (~/Library/Application Support/KAI-KI)."""
import json
import os
from pathlib import Path

ORDNER = Path(os.environ.get("KAI_KI_ORDNER", Path.home() / "Library" / "Application Support" / "KAI-KI"))
DATEI = ORDNER / "einstellungen.json"

# Modelle (Bildmodelle im GGUF-Format, llama.cpp lädt sie beim ersten Start von Hugging Face)
MODELLE = {
    "qwen25vl-7b": {"name": "Qwen2.5-VL 7B (genauer)", "hf": "ggml-org/Qwen2.5-VL-7B-Instruct-GGUF", "groesse": "ca. 6 GB"},
    "qwen25vl-3b": {"name": "Qwen2.5-VL 3B (schneller)", "hf": "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF", "groesse": "ca. 3 GB"},
}
VORGABE_MODELL = "qwen25vl-7b"


def laden() -> dict:
    try:
        return json.loads(DATEI.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def speichern(daten: dict) -> None:
    ORDNER.mkdir(parents=True, exist_ok=True)
    tmp = DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), "utf-8")
    os.chmod(tmp, 0o600)          # enthält den Geräte-Schlüssel
    tmp.replace(DATEI)
