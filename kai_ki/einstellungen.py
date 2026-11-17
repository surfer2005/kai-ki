"""Einstellungen und Ablage der App (~/Library/Application Support/KAI-KI)."""
import json
import os
from pathlib import Path

ORDNER = Path(os.environ.get("KAI_KI_ORDNER", Path.home() / "Library" / "Application Support" / "KAI-KI"))
DATEI = ORDNER / "einstellungen.json"

# Modelle (Bildmodelle im GGUF-Format, llama.cpp lädt sie beim ersten Start von Hugging Face)
MODELLE = {
    "qwen25vl-7b": {"name": "Qwen2.5-VL 7B (genauer)", "hf": "ggml-org/Qwen2.5-VL-7B-Instruct-GGUF", "groesse": "ca. 6 GB",
                    "bytes": 5_800_000_000},   # Q4_K_M 4,68 GB + Bildteil (mmproj) 0,85–1,35 GB
    "qwen25vl-3b": {"name": "Qwen2.5-VL 3B (schneller)", "hf": "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF", "groesse": "ca. 3 GB",
                    "bytes": 3_000_000_000},   # Q4_K_M 1,93 GB + mmproj 0,84–1,34 GB
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
