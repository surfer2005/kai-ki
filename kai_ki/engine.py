"""Das Rechenprogramm für das Modell: llama.cpp (llama-server) läuft als Teil der App, nur auf diesem Mac (127.0.0.1).
Beim ersten Start lädt die App das Programm (offizielle Ausgabe von github.com/ggml-org/llama.cpp, macOS arm64) und
llama.cpp das gewählte Modell von Hugging Face. Danach läuft alles ohne Netz außer der Verbindung zu KAI."""
import io
import json
import os
import stat
import subprocess
import tarfile
import time
import zipfile
from pathlib import Path

import requests

from .einstellungen import MODELLE, ORDNER

PORT = 18737
PROGRAMM = ORDNER / "llama"
MODELL_ORDNER = ORDNER / "modelle"


class EngineFehler(Exception):
    pass


def server_pfad() -> Path | None:
    for p in PROGRAMM.rglob("llama-server"):
        if p.is_file():
            return p
    return None


# Rückfall, falls GitHub nicht antwortet (Abruf-Grenze o. ä.): eine geprüfte Ausgabe (2026-11-17)
RUECKFALL = ("b12473", "https://github.com/ggml-org/llama.cpp/releases/download/b12473/llama-b12473-bin-macos-arm64.tar.gz")
ENDUNGEN = ("-bin-macos-arm64.tar.gz", "-bin-macos-arm64.zip")


def ausgabe_waehlen(releases: list) -> tuple[str, str] | None:
    """Neueste Ausgabe mit macOS-arm64-Datei → (Tag, Adresse). llama.cpp veröffentlicht seine Builds als „Vorabversion“
    (die „neueste“ Version hat keine Dateien), früher als .zip, seit Herbst 2026 als .tar.gz — beides wird genommen."""
    for rel in releases or []:
        for a in rel.get("assets", []) or []:
            if a.get("name", "").endswith(ENDUNGEN):
                return rel.get("tag_name", "?"), a["browser_download_url"]
    return None


def entpacken(daten: bytes, name: str, ziel: Path) -> None:
    ziel.mkdir(parents=True, exist_ok=True)
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(daten)) as z:
            z.extractall(ziel)
    else:
        with tarfile.open(fileobj=io.BytesIO(daten), mode="r:gz") as t:
            t.extractall(ziel, filter="data")       # nur innerhalb des Ziels, Verweise (libggml.dylib → …) bleiben


def programm_laden(melden=print) -> Path:
    """Neueste llama.cpp-Ausgabe für macOS (arm64) holen, falls noch nicht da."""
    p = server_pfad()
    if p:
        return p
    melden("Rechenprogramm (llama.cpp) wird geladen …")
    try:
        r = requests.get("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30", timeout=30,
                         headers={"Accept": "application/vnd.github+json", "User-Agent": "KAI-KI"})
        r.raise_for_status()
        wahl = ausgabe_waehlen(r.json()) or RUECKFALL
    except Exception:  # noqa: BLE001 — dann die geprüfte Ausgabe
        wahl = RUECKFALL
    tag, url = wahl
    melden(f"Lade llama.cpp {tag} …")
    d = requests.get(url, timeout=600, headers={"User-Agent": "KAI-KI"})
    d.raise_for_status()
    entpacken(d.content, url, PROGRAMM)
    for f in PROGRAMM.rglob("*"):
        if f.is_file() and not f.is_symlink() and (f.name.startswith("llama-") or f.suffix == ".dylib"):
            f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    (PROGRAMM / "version.txt").write_text(tag)
    p = server_pfad()
    if not p:
        raise EngineFehler(f"llama-server fehlt in der geladenen Ausgabe {tag}")
    return p


class Engine:
    def __init__(self, modell_key: str, melden=print):
        self.modell_key = modell_key if modell_key in MODELLE else next(iter(MODELLE))
        self.melden = melden
        self.proc: subprocess.Popen | None = None
        self.log = ORDNER / "llama-server.log"

    @property
    def modell_name(self) -> str:
        return MODELLE[self.modell_key]["name"]

    def bereit(self) -> bool:
        try:
            return requests.get(f"http://127.0.0.1:{PORT}/health", timeout=3).status_code == 200
        except requests.RequestException:
            return False

    def starten(self, warten_s: int = 3600) -> None:
        if self.bereit():
            return
        server = programm_laden(self.melden)
        MODELL_ORDNER.mkdir(parents=True, exist_ok=True)
        umgebung = {**os.environ, "LLAMA_CACHE": str(MODELL_ORDNER)}
        self.melden(f"{self.modell_name} wird geladen (beim ersten Mal {MODELLE[self.modell_key]['groesse']} Download) …")
        log = open(self.log, "ab")
        self.proc = subprocess.Popen(
            [str(server), "-hf", MODELLE[self.modell_key]["hf"], "--host", "127.0.0.1", "--port", str(PORT),
             "-c", "12288", "-ngl", "99"],
            stdout=log, stderr=subprocess.STDOUT, env=umgebung, cwd=str(server.parent))
        ende = time.time() + warten_s
        while time.time() < ende:
            if self.proc.poll() is not None:
                raise EngineFehler(f"Rechenprogramm beendet (Code {self.proc.returncode}) — siehe {self.log}")
            if self.bereit():
                self.melden(f"{self.modell_name} ist bereit.")
                return
            time.sleep(2)
        raise EngineFehler("Modell wurde nicht rechtzeitig bereit")

    def stoppen(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def fragen(self, png: bytes, aufgabe: str, max_tokens: int) -> tuple[str, int, int]:
        """Bild + Aufgabe → Antworttext (JSON erzwungen), Tokens ein/aus."""
        import base64
        nachricht = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
            {"type": "text", "text": aufgabe}]}]
        r = requests.post(f"http://127.0.0.1:{PORT}/v1/chat/completions", timeout=1800, json={
            "messages": nachricht, "max_tokens": max_tokens, "temperature": 0.1, "response_format": {"type": "json_object"}})
        if r.status_code >= 400:
            raise EngineFehler(f"Modell: {r.text[:300]}")
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        u = j.get("usage") or {}
        return text, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def antwort_ergaenzen(text: str, ocr_text: str) -> str:
    """Volltext der Antwort aus der Texterkennung füllen (das Modell schreibt ihn auf dem Gerät nicht ab)."""
    if not ocr_text:
        return text
    try:
        start, ende = text.index("{"), text.rindex("}") + 1
        daten = json.loads(text[start:ende])
    except ValueError:
        return text
    if isinstance(daten, dict) and not daten.get("volltext"):
        daten["volltext"] = ocr_text
    return json.dumps(daten, ensure_ascii=False)
