"""Einstellungen und Ablage der App (~/Library/Application Support/KAI-KI)."""
import json
import os
from pathlib import Path

ORDNER = Path(os.environ.get("KAI_KI_ORDNER", Path.home() / "Library" / "Application Support" / "KAI-KI"))
DATEI = ORDNER / "einstellungen.json"

# Modelle (Bildmodelle im GGUF-Format, llama.cpp lädt sie beim ersten Start von Hugging Face)
# „bytes“ = ungefähre Downloadgröße (Modell + Bildteil mmproj) für die Fortschrittsanzeige; „args“ = zusätzliche
# Schalter für llama-server; „denken_aus“ = Modell denkt standardmäßig erst nach (Qwen3.5) → für Belege abschalten.
MODELLE = {
    "qwen35-9b": {"name": "Qwen3.5 9B (empfohlen)", "hf": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M", "groesse": "ca. 6,6 GB",
                  "bytes": 6_600_000_000, "args": ["--reasoning", "off"], "denken_aus": True},
    "qwen3vl-8b": {"name": "Qwen3-VL 8B", "hf": "Qwen/Qwen3-VL-8B-Instruct-GGUF:Q4_K_M", "groesse": "ca. 6 GB",
                   "bytes": 5_800_000_000},   # Q4_K_M 5,03 GB + mmproj 0,75–1,16 GB
    "qwen3vl-8b-q8": {"name": "Qwen3-VL 8B genauer (Q8, langsamer)", "hf": "Qwen/Qwen3-VL-8B-Instruct-GGUF:Q8_0", "groesse": "ca. 9,5 GB",
                      "bytes": 9_500_000_000},
    "qwen25vl-7b": {"name": "Qwen2.5-VL 7B (bisher)", "hf": "ggml-org/Qwen2.5-VL-7B-Instruct-GGUF", "groesse": "ca. 6 GB",
                    "bytes": 5_800_000_000},   # Q4_K_M 4,68 GB + Bildteil (mmproj) 0,85–1,35 GB
    "qwen25vl-3b": {"name": "Qwen2.5-VL 3B (schneller)", "hf": "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF", "groesse": "ca. 3 GB",
                    "bytes": 3_000_000_000},   # Q4_K_M 1,93 GB + mmproj 0,84–1,34 GB
}
# Eigenes, auf KAI nachtrainiertes Modell („Weg 3“, Ordner training/): liegt als Datei im Modell-Ordner, kein Download.
# Erscheint in der Auswahl erst, wenn trainieren.sh die Datei abgelegt hat. Den Bildteil (mmproj) nimmt es vom Grundmodell.
MODELLE["kai-eigen"] = {"name": "KAI angepasst (eigenes Training)", "datei": "kai-eigen.gguf", "basis": "qwen35-9b",
                        "groesse": "liegt auf dem Mac", "bytes": 0, "args": ["--reasoning", "off"], "denken_aus": True}
VORGABE_MODELL = "qwen35-9b"   # Vergleich 17.11.: so genau wie Q8, rund 30 % schneller
EIGEN_ORDNER = ORDNER / "modelle"


def eigenes_modell(key: str) -> Path | None:
    """Datei eines eigenen Modells (nur Einträge mit „datei“), sonst None."""
    m = MODELLE.get(key) or {}
    return EIGEN_ORDNER / m["datei"] if m.get("datei") else None


def eigenes_info() -> dict:
    """Angaben von trainieren.sh zum eigenen Modell (Datum, Beispiele, Grundmodell) — leer, wenn keine."""
    try:
        return json.loads((EIGEN_ORDNER / "kai-eigen.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def modelle_verfuegbar() -> dict:
    """Modelle für die Auswahl: alle zum Herunterladen + eigene, sofern die Datei schon da ist."""
    raus = {}
    for k, m in MODELLE.items():
        if m.get("datei"):
            f = eigenes_modell(k)
            if not (f and f.is_file()):
                continue
            stand = eigenes_info().get("datum", "")
            m = {**m, "name": f"{m['name']}{', Stand ' + stand if stand else ''}"}
        raus[k] = m
    return raus


def verbindungen(cfg: dict) -> list:
    """Verbindungen zu KAI (z. B. Test und Produktion) — ältere Einstellungen mit nur einer werden übernommen."""
    v = cfg.get("verbindungen")
    if v is None and cfg.get("token") and cfg.get("kai_url"):
        v = [{"kai_url": cfg["kai_url"], "token": cfg["token"], "name": cfg.get("name", "")}]
    return [x for x in (v or []) if x.get("kai_url") and x.get("token")]


def bezeichnung(url: str) -> str:
    """Kurzname einer Verbindung: „Test“ für …/test, sonst „Produktion“ bzw. die Adresse."""
    from urllib.parse import urlparse
    u = urlparse(url or "")
    if u.path.rstrip("/").lower().endswith("/test"):
        return "Test"
    return "Produktion" if u.netloc.endswith("kai-bsb.de") else (u.netloc or url)


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
