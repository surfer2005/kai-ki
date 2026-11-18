"""Nachtrainieren in der App (Weg 3; Peter 2026-11-18: „Training-Zip mit in die App packen, gut für Laien“).

Ohne Terminal: die App richtet die Werkzeuge selbst ein (wie beim Sprecher: uv → Python → Pakete), holt die Trainingsdaten
über ihre Kopplung direkt aus KAI und startet training/trainieren.py (dieselben Skripte wie in der Trainings-Zip — eine Quelle).
Fortschritt kommt aus den Zeilen, die trainieren.py schreibt („▶ 3/6 …“, „Iter 120: …“, „Fehlerwert …“, „✔“/„✖“).
"""
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import requests

from .einstellungen import ORDNER

TRAINING = ORDNER / "training"
MLX_LM = "mlx-lm==0.32.2"                  # gleiche Fassung wie training/einrichten.sh
STAND = "1"                                  # erhöhen, wenn eine bestehende Einrichtung ergänzt werden muss
MARKE = TRAINING / f"eingerichtet-{STAND}"
LOG = TRAINING / "einrichten.log"
PY_MLX = TRAINING / "venv-mlx" / "bin" / "python"
PY_GGUF = TRAINING / "venv-gguf" / "bin" / "python"
LLAMA_SRC = TRAINING / "llama.cpp"
DATEN = TRAINING / "daten"


class TrainingFehler(Exception):
    pass


def skript_ordner() -> Path:
    """training/ — in der fertigen App unter Contents/Resources (PyInstaller --add-data), beim Entwickeln im Quellordner."""
    basis = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return basis / "training"


def eingerichtet() -> bool:
    return PY_MLX.exists() and PY_GGUF.exists() and (LLAMA_SRC / "convert_hf_to_gguf.py").exists() and MARKE.exists()


def speicher_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return 0


def frei_gb() -> float:
    try:
        ORDNER.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(ORDNER).free / 1e9
    except OSError:
        return 0


def geraet_text(ram: float, frei: float) -> str:
    """Was der Mac kann — in Worten für die Anzeige."""
    if ram >= 30:
        t = f"Arbeitsspeicher {ram:.0f} GB: trainiert mit dem Grundmodell in voller Genauigkeit."
    elif ram >= 15:
        t = f"Arbeitsspeicher {ram:.0f} GB: trainiert mit dem 4-Bit-Grundmodell (langsamer, etwas ungenauer; ab 32 GB volle Genauigkeit)."
    else:
        t = f"Arbeitsspeicher {ram:.0f} GB: für das Training zu wenig (mindestens 16 GB)."
    if frei < 60:
        t += f" Freier Platz {frei:.0f} GB — es werden rund 60 GB gebraucht."
    return t


def _entpacken_ohne_obersten(daten: bytes, ziel: Path) -> None:
    """GitHub-Quellarchiv (llama.cpp-<tag>/…) ohne den obersten Ordner entpacken — wie tar --strip-components 1."""
    ziel.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(daten), mode="r:gz") as t:
        mitglieder = []
        for m in t.getmembers():
            teile = m.name.split("/", 1)
            if len(teile) < 2 or not teile[1]:
                continue
            m.name = teile[1]
            mitglieder.append(m)
        t.extractall(ziel, members=mitglieder, filter="data")


def einrichten(melden=print) -> None:
    """Werkzeuge für das Training anlegen (einmalig, einige Minuten, ca. 2 GB): Python + mlx-lm, Umwandler aus llama.cpp."""
    from .engine import PROGRAMM, RUECKFALL, programm_laden
    from .sprecher import UV_ENV, uv_holen
    TRAINING.mkdir(parents=True, exist_ok=True)
    uv = uv_holen(melden)
    env = {**os.environ, **UV_ENV}
    with open(LOG, "a", encoding="utf-8") as log:
        def lauf(befehl, text):
            melden(text)
            if subprocess.run([str(x) for x in befehl], env=env, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
                raise TrainingFehler(f"{text.rstrip(' …')} hat nicht geklappt — Einzelheiten in {LOG}")
        if not PY_MLX.exists():
            lauf([uv, "venv", "--python", "3.11", TRAINING / "venv-mlx"], "Training wird eingerichtet: Python …")
        lauf([uv, "pip", "install", "--python", PY_MLX, MLX_LM], "Training wird eingerichtet: mlx-lm (einige Minuten) …")
        programm_laden(melden)                     # llama-quantize kommt aus dem Rechenprogramm der App
        try:
            tag = (PROGRAMM / "version.txt").read_text().strip() or RUECKFALL[0]
        except OSError:
            tag = RUECKFALL[0]
        try:
            vorhanden = (LLAMA_SRC / ".kai-tag").read_text().strip()
        except OSError:
            vorhanden = ""
        if vorhanden != tag:
            melden(f"Training wird eingerichtet: Umwandler aus llama.cpp {tag} …")
            d = requests.get(f"https://github.com/ggml-org/llama.cpp/archive/refs/tags/{tag}.tar.gz", timeout=600,
                             headers={"User-Agent": "KAI-KI"})
            d.raise_for_status()
            shutil.rmtree(LLAMA_SRC, ignore_errors=True)
            _entpacken_ohne_obersten(d.content, LLAMA_SRC)
            (LLAMA_SRC / ".kai-tag").write_text(tag)
        if not PY_GGUF.exists():
            lauf([uv, "venv", "--python", "3.11", TRAINING / "venv-gguf"], "Training wird eingerichtet: zweite Python-Umgebung …")
        lauf([uv, "pip", "install", "--python", PY_GGUF, "-r", LLAMA_SRC / "requirements" / "requirements-convert_hf_to_gguf.txt"],
             "Training wird eingerichtet: Umwandler (einige Minuten) …")
    MARKE.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    melden("Training ist eingerichtet.")


def daten_ablegen(antwort: dict, quelle: str) -> tuple[Path, int]:
    """Trainingsdaten aus KAI als Datei ablegen (nur für diesen Benutzer lesbar). Gibt Pfad und Anzahl der Beispiele zurück."""
    zeilen = [z for z in (antwort.get("zeilen") or []) if z]
    DATEN.mkdir(parents=True, exist_ok=True)
    for alt in DATEN.glob("*.jsonl"):           # immer nur der letzte Stand liegt hier
        alt.unlink(missing_ok=True)
    name = re.sub(r"[^A-Za-z0-9-]", "", quelle) or "kai"
    datei = DATEN / f"kai-ki-training-{name}-{time.strftime('%Y%m%d-%H%M')}.jsonl"
    datei.write_text("\n".join(zeilen) + "\n", "utf-8")
    os.chmod(datei, 0o600)
    return datei, len(zeilen)


# ---------- Fortschritt aus den Zeilen von trainieren.py (rein, getestet) ----------
SCHRITT_ANFANG = {1: 0, 2: 2, 3: 10, 4: 85, 5: 92, 6: 99}
SCHRITT_NAME = {1: "Daten prüfen", 2: "Grundmodell laden und messen", 3: "Training", 4: "Zusammenführen",
                5: "Für die App umwandeln", 6: "In der App ablegen"}


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def sauber(zeile: str) -> str:
    """Farbcodes und Rahmenzeichen weg — so erscheint die Zeile in der App."""
    return ANSI.sub("", zeile).rstrip()


def zeile_auswerten(zeile: str, stand: dict) -> dict:
    z = sauber(zeile).strip()
    m = re.match(r"^▶ (\d)/6", z)
    if m:
        stand["schritt"] = int(m.group(1))
    m = re.search(r"·\s*(\d+) Schritte\s*·", z)
    if m:
        stand["iters"] = int(m.group(1))
    # mlx-lm 0.32: „  120    1.234 ▼    850    96.0k“ (Training) bzw. „  100    val 1.300    2.10s“; ältere Fassungen „Iter 120: …“
    m = re.match(r"^(\d+)\s+(?:[0-9.]+\s+[▼▲]|val\s)", z) or re.match(r"^Iter (\d+):", z)
    if m and stand.get("schritt") == 3:
        stand["iter"] = int(m.group(1))
    m = re.match(r"^Fehlerwert vorher: ([0-9.]+)", z)
    if m:
        stand["vorher"] = float(m.group(1))
    m = re.match(r"^Fehlerwert nachher: ([0-9.]+)", z)
    if m:
        stand["nachher"] = float(m.group(1))
    if z.startswith("✔"):
        stand["fertig"] = True
    if z.startswith("✖"):
        stand["fehler"] = z.lstrip("✖ ").strip()
    return stand


def prozent(stand: dict) -> int:
    s = stand.get("schritt", 0)
    if stand.get("fertig"):
        return 100
    if not s:
        return 0
    p = SCHRITT_ANFANG.get(s, 0)
    if s == 3 and stand.get("iters"):
        p += int(75 * min(1.0, stand.get("iter", 0) / stand["iters"]))
    return min(99, p)


def schritt_text(stand: dict) -> str:
    s = stand.get("schritt", 0)
    if stand.get("fertig"):
        return "Fertig"
    if not s:
        return "Startet …"
    t = f"Schritt {s} von 6: {SCHRITT_NAME.get(s, '')}"
    if s == 2 and stand.get("vorher") is None:
        t += " (beim ersten Mal ca. 19 GB Download)"
    if s == 3 and stand.get("iters"):
        t += f" — {stand.get('iter', 0)} von {stand['iters']}"
    return t


class Trainingslauf:
    """trainieren.py als eigener Prozess (eigene Prozessgruppe → Abbrechen beendet auch mlx-lm/llama.cpp darunter)."""

    def __init__(self, datei: Path, zeile=print, zusatz: list | None = None):
        self.datei = Path(datei)
        self.zusatz = list(zusatz or [])               # weitere Schalter für trainieren.py (Prüflauf: --basis, --iters)
        self.zeile = zeile
        self.proc = None
        self.abgebrochen = False

    def laufen(self) -> dict:
        stand = {}
        befehl = [str(PY_MLX), str(skript_ordner() / "trainieren.py"), str(self.datei), *self.zusatz]
        if shutil.which("caffeinate"):
            befehl = ["caffeinate", "-i", *befehl]           # der Mac schläft während des Trainings nicht ein
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "KAI_KI_ORDNER": str(ORDNER), "NO_COLOR": "1"}
        self.proc = subprocess.Popen(befehl, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
                                     start_new_session=True)
        for z in self.proc.stdout:
            zeile_auswerten(z, stand)
            self.zeile(z.rstrip("\n"), dict(stand))
        self.proc.wait()
        if self.abgebrochen:
            stand["fehler"] = "abgebrochen"
        elif self.proc.returncode != 0 and not stand.get("fehler"):
            stand["fehler"] = f"Training beendet mit Code {self.proc.returncode}"
        return stand

    def abbrechen(self) -> None:
        self.abgebrochen = True
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except OSError:
                pass


def eigenes_info() -> dict:
    try:
        return json.loads((ORDNER / "modelle" / "kai-eigen.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
