"""Das Rechenprogramm für das Modell: llama.cpp (llama-server) läuft als Teil der App, nur auf diesem Mac (127.0.0.1).
Beim ersten Start lädt die App das Programm (offizielle Ausgabe von github.com/ggml-org/llama.cpp, macOS arm64) und
llama.cpp das gewählte Modell von Hugging Face. Danach läuft alles ohne Netz außer der Verbindung zu KAI."""
import io
import json
import atexit
import os
import signal
import stat
import subprocess
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import requests

from .einstellungen import MODELLE, ORDNER

PORT = 18737
PID_DATEI = ORDNER / "llama-server.pid"   # Rechenprogramm dieser App — ein übrig gebliebenes wird beim Start beendet
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


def teil_bytes(p: Path) -> int:
    """Größe angefangener Downloads (llama.cpp: *.downloadInProgress)."""
    try:
        return sum(f.stat().st_size for f in p.rglob("*.downloadInProgress") if f.is_file())
    except OSError:
        return 0


def ordner_bytes(p: Path) -> int:
    """Was im Modell-Ordner liegt (auch halb geladene Dateien) — Verweise nicht doppelt zählen."""
    try:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
    except OSError:
        return 0


def ladestand(neu: int, erwartet: int, laedt: bool, sekunden: float) -> tuple[str, int]:
    """Text + Prozent für die Anzeige. `neu` = seit dem Start hinzugekommene Bytes im Modell-Ordner (dort liegen auch
    andere, schon geladene Modelle — die zählen nicht), `laedt` = die Größe ändert sich noch, `sekunden` seit dem Start."""
    gb = lambda b: f"{b / 1e9:.1f}".replace(".", ",")
    pz = max(0, min(99, int(neu * 100 / erwartet))) if erwartet else 0
    if laedt:
        return f"Download {gb(neu)} von ca. {gb(erwartet)} GB ({pz} %)", pz
    if neu == 0 and sekunden < 20:
        return "Modell wird vorbereitet …", 0
    return "Modell wird in den Arbeitsspeicher geladen …", 99


def _laeuft(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _ist_llama(pid: int) -> bool:
    try:
        name = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True, timeout=5).stdout
        return "llama-server" in name
    except (OSError, subprocess.SubprocessError):
        return False


def uebrig_gebliebene_beenden(melden=print) -> None:
    """Ein Rechenprogramm, das nicht zu dieser Engine gehört (z. B. von der vorigen App-Version oder nach Cmd+Q übrig),
    beenden — sonst meldete die App „bereit“ mit dem neuen Modellnamen und rechnete mit dem alten Modell weiter
    (17.11.2026: Vergleich lief so versehentlich mit Qwen2.5 statt Qwen3-VL). Nur Prozesse namens llama-server."""
    pids = set()
    try:
        pids.add(int(PID_DATEI.read_text().strip()))
    except (OSError, ValueError):
        pass
    try:   # wer belegt unseren Anschluss?
        out = subprocess.run(["lsof", "-ti", f"tcp:{PORT}", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5).stdout
        pids.update(int(x) for x in out.split() if x.strip().isdigit())
    except (OSError, subprocess.SubprocessError):
        pass
    for pid in pids:
        if pid != os.getpid() and _laeuft(pid) and _ist_llama(pid):
            melden("Altes Rechenprogramm wird beendet …")
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                if not _laeuft(pid):
                    break
                time.sleep(0.2)
            if _laeuft(pid):
                os.kill(pid, signal.SIGKILL)
    PID_DATEI.unlink(missing_ok=True)


class Engine:
    def __init__(self, modell_key: str, melden=print):
        self.modell_key = modell_key if modell_key in MODELLE else next(iter(MODELLE))
        self._start_sperre = threading.Lock()
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

    def starten(self, warten_s: int = 3600, fortschritt=lambda text, prozent: None, versuche: int = 6) -> None:
        """Modell starten. Bricht der Download ab (Netz), startet die App llama-server bis zu `versuche`-mal neu — llama.cpp
        setzt dabei am angefangenen Stück (*.downloadInProgress) fort, statt neu zu beginnen."""
        with self._start_sperre:          # mehrere Verbindungen (Test + Produktion) teilen ein Modell
            return self._starten_versuche(warten_s, fortschritt, versuche)

    def _starten_versuche(self, warten_s: int, fortschritt, versuche: int) -> None:
        self.angehalten = False
        for versuch in range(1, versuche + 1):
            if self.angehalten:           # während der Pause angehalten
                raise EngineFehler("angehalten")
            try:
                return self._starten(warten_s, fortschritt)
            except EngineFehler as e:
                if versuch == versuche or "nicht rechtzeitig" in str(e) or self.angehalten:
                    raise
                self.stoppen(); self.angehalten = False     # eigenes Aufräumen, kein Anhalten durch den Nutzer
                fortschritt(f"Download unterbrochen – neuer Versuch {versuch + 1} von {versuche} (setzt fort) …", None)
                time.sleep(min(60, 10 * versuch))

    def _starten(self, warten_s: int, fortschritt) -> None:
        if self.proc and self.proc.poll() is None and self.bereit():
            return                                  # läuft schon — und zwar unseres, mit unserem Modell
        uebrig_gebliebene_beenden(self.melden)
        server = programm_laden(self.melden)
        MODELL_ORDNER.mkdir(parents=True, exist_ok=True)
        umgebung = {**os.environ, "LLAMA_CACHE": str(MODELL_ORDNER)}
        self.melden(f"{self.modell_name} wird geladen (beim ersten Mal {MODELLE[self.modell_key]['groesse']} Download) …")
        log = open(self.log, "ab")
        self.proc = subprocess.Popen(
            [str(server), "-hf", MODELLE[self.modell_key]["hf"], "--host", "127.0.0.1", "--port", str(PORT),
             "-c", "12288", "-ngl", "99", *MODELLE[self.modell_key].get("args", [])],
            stdout=log, stderr=subprocess.STDOUT, env=umgebung, cwd=str(server.parent))
        try:
            PID_DATEI.write_text(str(self.proc.pid))
        except OSError:
            pass
        atexit.register(self.stoppen)               # auch bei Cmd+Q / Absturz der Oberfläche nicht weiterlaufen lassen
        ende = time.time() + warten_s
        erwartet = MODELLE[self.modell_key].get("bytes", 0)
        # schon angefangene Stücke (abgebrochener Download) zählen als geladen — die Anzeige beginnt nicht wieder bei 0 %
        anfang = ordner_bytes(MODELL_ORDNER) - teil_bytes(MODELL_ORDNER)
        vorher, geaendert, beginn = anfang, 0.0, time.time()
        while time.time() < ende:
            if self.proc.poll() is not None:
                raise EngineFehler(f"Rechenprogramm beendet (Code {self.proc.returncode}) — siehe {self.log}")
            if self.bereit():
                self.melden(f"{self.modell_name} ist bereit.")
                return
            jetzt_b = ordner_bytes(MODELL_ORDNER)
            if jetzt_b != vorher:
                vorher, geaendert = jetzt_b, time.time()
            fortschritt(*ladestand(max(0, jetzt_b - anfang), erwartet, time.time() - geaendert < 10, time.time() - beginn))
            time.sleep(2)
        raise EngineFehler("Modell wurde nicht rechtzeitig bereit")

    angehalten = False             # gewollt angehalten (Anhalten/Modellwechsel) → kein neuer Versuch
    _start_sperre = None

    def stoppen(self) -> None:
        self.angehalten = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.proc:
            PID_DATEI.unlink(missing_ok=True)
        self.proc = None

    def fragen(self, png: bytes, aufgabe: str, max_tokens: int) -> tuple[str, int, int]:
        """Bild + Aufgabe → Antworttext (JSON erzwungen), Tokens ein/aus."""
        import base64
        nachricht = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
            {"type": "text", "text": aufgabe}]}]
        anfrage = {"messages": nachricht, "max_tokens": max_tokens, "temperature": 0.1, "response_format": {"type": "json_object"}}
        if MODELLE[self.modell_key].get("denken_aus"):      # Qwen3.5: kein „Nachdenken“ vor der Antwort (sonst minutenlang)
            anfrage["chat_template_kwargs"] = {"enable_thinking": False}
        r = requests.post(f"http://127.0.0.1:{PORT}/v1/chat/completions", timeout=1800, json=anfrage)
        if r.status_code >= 400:
            raise EngineFehler(f"Modell: {r.text[:300]}")
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        u = j.get("usage") or {}
        return text, int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


    def chat(self, nachrichten: list, max_tokens: int = 1500, temperatur: float = 0.3, beim_schreiben=lambda text: True) -> tuple[str, int, int]:
        """Gespräch (Text, Bilder als image_url) mit gestreamter Antwort. `beim_schreiben(text)` bekommt den bisher
        geschriebenen Text; gibt es False zurück (in KAI gestoppt), hört das Modell auf. → Text, Tokens ein/aus."""
        anfrage = {"messages": nachrichten, "max_tokens": max_tokens, "temperature": temperatur, "stream": True,
                   "stream_options": {"include_usage": True}}
        if MODELLE[self.modell_key].get("denken_aus"):      # Qwen3.5: ohne „Nachdenken“ antworten
            anfrage["chat_template_kwargs"] = {"enable_thinking": False}
        text, ein, aus = "", 0, 0
        with requests.post(f"http://127.0.0.1:{PORT}/v1/chat/completions", json=anfrage, stream=True, timeout=(10, 900)) as r:
            if r.status_code >= 400:
                raise EngineFehler(f"Modell: {r.text[:300]}")
            r.encoding = "utf-8"
            for zeile in r.iter_lines(decode_unicode=True):
                if not zeile or not zeile.startswith("data:"):
                    continue
                daten = zeile[5:].strip()
                if daten == "[DONE]":
                    break
                try:
                    j = json.loads(daten)
                except ValueError:
                    continue
                for c in j.get("choices") or []:
                    stueck = (c.get("delta") or {}).get("content")
                    if stueck:
                        text += stueck
                u = j.get("usage") or {}
                if u:
                    ein, aus = int(u.get("prompt_tokens") or ein), int(u.get("completion_tokens") or aus)
                if not beim_schreiben(text):
                    break
        return text, ein, aus


def chat_nachrichten(nachrichten: list, bild=lambda seite: b"", ocr=lambda png: "") -> list:
    """Nachrichten aus KAI → Format des Modells. Seiten (Bild/PDF) einer Nachricht werden Bilder, ihre Texterkennung
    kommt als Hilfe dazu. `bild(seite)` → PNG, `ocr(png)` → Text (leer, wenn keine Texterkennung gewünscht)."""
    import base64
    aus = []
    for m in nachrichten or []:
        rolle = m.get("role") if m.get("role") in ("system", "user", "assistant") else "user"
        seiten = m.get("seiten") or []
        if not seiten:
            aus.append({"role": rolle, "content": str(m.get("content") or "")})
            continue
        teile, erkannt = [], []
        for i, s in enumerate(seiten, 1):
            png = bild(s)
            teile.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}})
            t = ocr(png)
            if t:
                erkannt.append(f"Seite {i}:\n{t[:3000]}")
        text = str(m.get("content") or "")
        if erkannt:
            text += "\n\nTexterkennung der angehängten Seiten (auf dem Gerät, kann Lesefehler enthalten, nur als Hilfe):\n" + "\n\n".join(erkannt)
        teile.append({"type": "text", "text": text})
        aus.append({"role": rolle, "content": teile})
    return aus


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
