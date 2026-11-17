"""Sprechen: Text → Tonspur mit Chatterbox Multilingual (Resemble AI, MIT-Lizenz, Deutsch). Läuft getrennt vom Lese-Modell in
einer eigenen Python-Umgebung — PyTorch ist für die App selbst zu groß. Beim ersten Sprechauftrag richtet die App sie ein:
uv (Astral, offizielle Ausgabe von GitHub) → Python 3.11 → chatterbox-tts. Danach läuft ein Sprecher-Dienst als eigener
Prozess, der das Modell einmal lädt (beim ersten Mal von Hugging Face, einige GB) und Aufträge über stdin/stdout bekommt.
Alles bleibt auf diesem Mac."""
import atexit
import json
import os
import re
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import requests

from .einstellungen import ORDNER

UV_VERSION = "0.5.11"
UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-aarch64-apple-darwin.tar.gz"
PAKET = "chatterbox-tts==0.1.7"
# Das Wasserzeichen-Modul von Chatterbox (resemble-perth) braucht pkg_resources — uv legt Umgebungen ohne setuptools an
ZUSATZ = ["setuptools<81"]
STAND = "2"                     # erhöhen, wenn eine bestehende Umgebung ergänzt werden muss
SPRECHER = ORDNER / "sprecher"
UMGEBUNG = SPRECHER / "umgebung"
PYTHON = UMGEBUNG / "bin" / "python"
MARKE = SPRECHER / f"eingerichtet-{PAKET.split('==')[1]}-{STAND}"
LOG = SPRECHER / "sprecher.log"

# Der Dienst (läuft in der Chatterbox-Umgebung): eine JSON-Zeile rein, eine JSON-Zeile raus
DIENST = r'''
import inspect, json, os, sys, wave
# Antworten nur über eine eigene Kopie der Standardausgabe — alles, was Bibliotheken drucken, landet im Log
_aus = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1); sys.stdout = sys.stderr
def melde(d):
    _aus.write(json.dumps(d) + "\n"); _aus.flush()
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
import torch
try:                                  # Wasserzeichen-Modul vorab prüfen — sonst bricht das Laden ohne klare Meldung ab
    import perth
    if getattr(perth, "PerthImplicitWatermarker", None) is None:
        from perth.perth_net.perth_net_implicit.perth_watermarker import PerthImplicitWatermarker  # noqa: F401 — zeigt den echten Fehler
except Exception as e:
    melde({"bereit": False, "fehler": f"Wasserzeichen-Modul (resemble-perth): {e.__class__.__name__}: {e}"}); sys.exit(1)
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
geraet = "mps" if torch.backends.mps.is_available() else "cpu"
def laden(g):
    try:
        return ChatterboxMultilingualTTS.from_pretrained(device=g, t3_model="v3")
    except TypeError:
        return ChatterboxMultilingualTTS.from_pretrained(device=g)
try:
    model = laden(geraet)
except Exception:
    geraet = "cpu"; model = laden("cpu")
param = inspect.signature(model.generate).parameters
melde({"bereit": True, "geraet": geraet, "sr": model.sr})
for zeile in sys.stdin:
    try:
        a = json.loads(zeile)
        teile = []
        for satz in a["saetze"]:
            kw = {"language_id": a.get("sprache", "de")}
            if a.get("stimme") and "audio_prompt_path" in param: kw["audio_prompt_path"] = a["stimme"]
            if a.get("lebhaft") is not None and "exaggeration" in param: kw["exaggeration"] = float(a["lebhaft"])
            if a.get("tempo") is not None and "cfg_weight" in param: kw["cfg_weight"] = float(a["tempo"])
            w = model.generate(satz, **kw).detach().cpu().reshape(-1)
            teile.append(w); teile.append(torch.zeros(int(model.sr * float(a.get("pause", 0.3)))))
        ges = torch.cat(teile).clamp(-1, 1)
        pcm = (ges * 32767).to(torch.int16).numpy().tobytes()
        with wave.open(a["ziel"], "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(int(model.sr)); f.writeframes(pcm)
        melde({"ok": True, "sekunden": round(ges.shape[0] / model.sr, 2)})
    except Exception as e:
        melde({"ok": False, "fehler": f"{e.__class__.__name__}: {e}"[:500]})
'''


class SprecherFehler(Exception):
    pass


def antwort_lesen(strom) -> dict | None:
    """Nächste JSON-Antwort des Dienstes; andere Zeilen überspringen. None = Dienst beendet."""
    while True:
        zeile = strom.readline()
        if not zeile:
            return None
        try:
            d = json.loads(zeile)
            if isinstance(d, dict):
                return d
        except ValueError:
            continue


def saetze(text: str, laenge: int = 260) -> list[str]:
    """Text in sprechbare Stücke: an Satzenden trennen, kurze Sätze zusammenlegen, überlange an Kommas teilen."""
    roh = [s.strip() for s in re.split(r"(?<=[.!?…:])\s+", re.sub(r"\s+", " ", text or "").strip()) if s.strip()]
    stuecke = []
    for s in roh:
        while len(s) > laenge:                              # sehr lange Sätze an einem Komma vor der Grenze teilen
            k = s.rfind(", ", 0, laenge)
            k = k + 1 if k > 40 else laenge
            stuecke.append(s[:k].strip()); s = s[k:].strip()
        if s:
            stuecke.append(s)
    zusammen = []
    for s in stuecke:
        if zusammen and len(zusammen[-1]) + 1 + len(s) <= laenge and len(zusammen[-1]) < 60:
            zusammen[-1] += " " + s
        else:
            zusammen.append(s)
    return zusammen


def ordner_bytes(p: Path) -> int:
    try:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def _log_ende(n: int = 1500) -> str:
    try:
        return LOG.read_text("utf-8", errors="replace")[-n:]
    except OSError:
        return ""


def uv_holen(melden=print) -> Path:
    """Werkzeug uv (Astral, offizielle Ausgabe) — legt Python-Umgebungen für Sprecher und Spracherkennung an."""
    SPRECHER.mkdir(parents=True, exist_ok=True)
    uv = SPRECHER / "uv" / "uv-aarch64-apple-darwin" / "uv"
    if not uv.exists():
        melden("Werkzeug uv wird geladen …")
        d = requests.get(UV_URL, timeout=300, headers={"User-Agent": "KAI-KI"}); d.raise_for_status()
        ziel = SPRECHER / "uv"; ziel.mkdir(exist_ok=True)
        with tempfile.TemporaryFile() as tf:
            tf.write(d.content); tf.seek(0)
            with tarfile.open(fileobj=tf, mode="r:gz") as t:
                t.extractall(ziel, filter="data")
        uv.chmod(0o755)
    return uv


# uv legt Python und Paket-Zwischenspeicher gemeinsam ab (Sprecher und Spracherkennung teilen sie)
UV_ENV = {"UV_PYTHON_INSTALL_DIR": str(SPRECHER / "python"), "UV_CACHE_DIR": str(SPRECHER / "cache")}


def einrichten(melden=print) -> None:
    """Python-Umgebung mit Chatterbox anlegen (einmalig, einige Minuten)."""
    if PYTHON.exists() and MARKE.exists():
        return
    uv = uv_holen(melden)
    env = {**os.environ, **UV_ENV}
    with open(LOG, "a", encoding="utf-8") as log:
        if not PYTHON.exists():           # bestehende Umgebung nur ergänzen, nicht neu anlegen (PyTorch nicht noch einmal laden)
            melden("Sprecher wird eingerichtet: Python 3.11 …")
            if subprocess.run([str(uv), "venv", "--python", "3.11", str(UMGEBUNG)], env=env, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
                raise SprecherFehler("Python-Umgebung ließ sich nicht anlegen: " + _log_ende(400))
        melden("Sprecher wird eingerichtet: Chatterbox und PyTorch werden installiert (einige Minuten) …")
        if subprocess.run([str(uv), "pip", "install", "--python", str(PYTHON), PAKET, *ZUSATZ], env=env, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
            raise SprecherFehler("Chatterbox ließ sich nicht installieren: " + _log_ende(600))
    MARKE.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))


def stimme_vorbereiten(daten: bytes, mime: str) -> str:
    """Stimmprobe als WAV (24 kHz, mono) ablegen — macOS-Bordmittel afconvert wandelt MP3/M4A um."""
    roh = Path(tempfile.mkstemp(suffix={"audio/mpeg": ".mp3", "audio/mp4": ".m4a"}.get(mime, ".wav"), dir=SPRECHER)[1])
    roh.write_bytes(daten)
    ziel = roh.with_suffix(".probe.wav")
    r = subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", str(roh), str(ziel)], capture_output=True)
    roh.unlink(missing_ok=True)
    if r.returncode != 0 or not ziel.exists():
        raise SprecherFehler("Stimmprobe ließ sich nicht umwandeln (afconvert)")
    return str(ziel)


class Sprecher:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        atexit.register(self.stoppen)

    def bereit(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def starten(self, fortschritt=lambda text: None) -> None:
        if self.bereit():
            return
        einrichten(fortschritt)
        skript = SPRECHER / "dienst.py"; skript.write_text(DIENST, "utf-8")
        env = {**os.environ, "HF_HOME": str(SPRECHER / "hf"), "PYTORCH_ENABLE_MPS_FALLBACK": "1", "TOKENIZERS_PARALLELISM": "false"}
        log = open(LOG, "a", encoding="utf-8")
        self.proc = subprocess.Popen([str(PYTHON), str(skript)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, env=env, bufsize=1)
        beginn, stopp = time.time(), threading.Event()

        def zeigen():                                       # Ladefortschritt: was schon von Hugging Face da ist
            while not stopp.wait(10):
                fortschritt(f"Sprechmodell wird geladen … {ordner_bytes(SPRECHER / 'hf') / 1e9:.1f} GB, {int(time.time() - beginn)} s")
        threading.Thread(target=zeigen, daemon=True).start()
        try:
            erste = antwort_lesen(self.proc.stdout)
        finally:
            stopp.set()
        if not erste or not erste.get("bereit"):
            self.stoppen()
            raise SprecherFehler("Sprecher startet nicht: " + ((erste or {}).get("fehler") or _log_ende(600)))

    def sprechen(self, text: str, sprache: str = "de", lebhaft=None, tempo=None, stimme: dict | None = None, fortschritt=lambda t: None) -> tuple[bytes, float]:
        with self.lock:
            self.starten(fortschritt)
            probe = stimme_vorbereiten(__import__("base64").b64decode(stimme["data"]), stimme.get("mime", "audio/wav")) if stimme and stimme.get("data") else None
            ziel = Path(tempfile.mkstemp(suffix=".wav", dir=SPRECHER)[1])
            try:
                auftrag = {"saetze": saetze(text), "sprache": sprache, "lebhaft": lebhaft, "tempo": tempo, "stimme": probe, "ziel": str(ziel)}
                self.proc.stdin.write(json.dumps(auftrag) + "\n"); self.proc.stdin.flush()
                r = antwort_lesen(self.proc.stdout)
                if r is None:
                    self.stoppen(); raise SprecherFehler("Sprecher wurde beendet: " + _log_ende(600))
                if not r.get("ok"):
                    raise SprecherFehler(r.get("fehler") or "Sprecher meldet einen Fehler")
                return ziel.read_bytes(), float(r.get("sekunden") or 0)
            finally:
                ziel.unlink(missing_ok=True)
                if probe:
                    Path(probe).unlink(missing_ok=True)

    def stoppen(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate(); self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        self.proc = None
