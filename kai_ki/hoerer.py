"""Hören: Sprache → Text mit Whisper (OpenAI, MIT-Lizenz) über mlx-whisper (Apple MLX, rechnet auf der Grafik des Mac).
Für das Mikrofon im KI-Chat: KAI schickt eine kurze WAV-Aufnahme, die App gibt den erkannten Text zurück. Wie der Sprecher in
einer eigenen Python-Umgebung (beim ersten Auftrag eingerichtet, einige Minuten); das Modell (whisper-large-v3-turbo, gut
1,5 GB) kommt beim ersten Mal von Hugging Face. Alles bleibt auf diesem Mac."""
import atexit
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .einstellungen import ORDNER
from .sprecher import UV_ENV, antwort_lesen, ordner_bytes, uv_holen

PAKET = "mlx-whisper==0.4.3"
MODELL = "mlx-community/whisper-large-v3-turbo"
HOERER = ORDNER / "hoerer"
UMGEBUNG = HOERER / "umgebung"
PYTHON = UMGEBUNG / "bin" / "python"
MARKE = HOERER / f"eingerichtet-{PAKET.split('==')[1]}"
LOG = HOERER / "hoerer.log"

# Der Dienst (läuft in der Whisper-Umgebung): eine JSON-Zeile rein ({datei, sprache}), eine JSON-Zeile raus ({ok, text})
DIENST = r'''
import json, os, sys, wave
_aus = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1); sys.stdout = sys.stderr
def melde(d):
    _aus.write(json.dumps(d) + "\n"); _aus.flush()
import numpy as np
import mlx_whisper
from huggingface_hub import snapshot_download
pfad = snapshot_download(sys.argv[1])
melde({"bereit": True})
for zeile in sys.stdin:
    try:
        a = json.loads(zeile)
        with wave.open(a["datei"], "rb") as w:
            sr, ch, roh = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
        x = np.frombuffer(roh, dtype=np.int16).astype(np.float32) / 32768.0
        if ch > 1:
            x = x.reshape(-1, ch).mean(axis=1)
        if sr != 16000:                                   # Whisper rechnet mit 16 kHz
            x = np.interp(np.arange(0, len(x), sr / 16000), np.arange(len(x)), x).astype(np.float32)
        r = mlx_whisper.transcribe(x, path_or_hf_repo=pfad, language=a.get("sprache") or "de", condition_on_previous_text=False)
        melde({"ok": True, "text": (r.get("text") or "").strip(), "sekunden": round(len(x) / 16000, 1)})
    except Exception as e:
        melde({"ok": False, "fehler": f"{e.__class__.__name__}: {e}"[:500]})
'''


class HoererFehler(Exception):
    pass


def _log_ende(n: int = 1500) -> str:
    try:
        return LOG.read_text("utf-8", errors="replace")[-n:]
    except OSError:
        return ""


def einrichten(melden=print) -> None:
    """Python-Umgebung mit mlx-whisper anlegen (einmalig, einige Minuten)."""
    if PYTHON.exists() and MARKE.exists():
        return
    HOERER.mkdir(parents=True, exist_ok=True)
    uv = uv_holen(melden)
    env = {**os.environ, **UV_ENV}
    with open(LOG, "a", encoding="utf-8") as log:
        if not PYTHON.exists():
            melden("Spracherkennung wird eingerichtet: Python 3.11 …")
            if subprocess.run([str(uv), "venv", "--python", "3.11", str(UMGEBUNG)], env=env, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
                raise HoererFehler("Python-Umgebung ließ sich nicht anlegen: " + _log_ende(400))
        melden("Spracherkennung wird eingerichtet: Whisper wird installiert (einige Minuten) …")
        if subprocess.run([str(uv), "pip", "install", "--python", str(PYTHON), PAKET], env=env, stdout=log, stderr=subprocess.STDOUT).returncode != 0:
            raise HoererFehler("Whisper ließ sich nicht installieren: " + _log_ende(600))
    MARKE.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))


class Hoerer:
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
        skript = HOERER / "dienst.py"; skript.write_text(DIENST, "utf-8")
        env = {**os.environ, "HF_HOME": str(HOERER / "hf"), "TOKENIZERS_PARALLELISM": "false"}
        log = open(LOG, "a", encoding="utf-8")
        self.proc = subprocess.Popen([str(PYTHON), str(skript), MODELL], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, env=env, bufsize=1)
        beginn, stopp = time.time(), threading.Event()

        def zeigen():
            while not stopp.wait(5):
                fortschritt(f"Spracherkennung wird geladen … {ordner_bytes(HOERER / 'hf') / 1e9:.1f} GB von ca. 1,6 GB, {int(time.time() - beginn)} s")
        threading.Thread(target=zeigen, daemon=True).start()
        try:
            erste = antwort_lesen(self.proc.stdout)
        finally:
            stopp.set()
        if not erste or not erste.get("bereit"):
            self.stoppen()
            raise HoererFehler("Spracherkennung startet nicht: " + _log_ende(600))

    def hoeren(self, wav: bytes, sprache: str = "de", fortschritt=lambda t: None) -> str:
        with self.lock:
            self.starten(fortschritt)
            datei = Path(tempfile.mkstemp(suffix=".wav", dir=HOERER)[1])
            try:
                datei.write_bytes(wav)
                self.proc.stdin.write(json.dumps({"datei": str(datei), "sprache": sprache}) + "\n"); self.proc.stdin.flush()
                r = antwort_lesen(self.proc.stdout)
                if r is None:
                    self.stoppen(); raise HoererFehler("Spracherkennung wurde beendet: " + _log_ende(600))
                if not r.get("ok"):
                    raise HoererFehler(r.get("fehler") or "Spracherkennung meldet einen Fehler")
                return r.get("text") or ""
            finally:
                datei.unlink(missing_ok=True)

    def stoppen(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate(); self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        self.proc = None
