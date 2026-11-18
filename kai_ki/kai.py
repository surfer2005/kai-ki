"""Verbindung zu KAI: koppeln, melden, Aufträge holen, Ergebnisse zurückgeben (nur ausgehend, HTTPS)."""
import platform
import subprocess

import requests

from . import __version__


class KaiFehler(Exception):
    pass


def geraete_info() -> dict:
    """Was KAI über das Gerät anzeigen darf: Chip, Arbeitsspeicher, System — keine Seriennummer."""
    info = {"system": f"macOS {platform.mac_ver()[0]}".strip()}
    try:
        info["chip"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5).stdout.strip()
        info["ram_gb"] = round(int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout.strip()) / 1024 ** 3)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return info


def adresse_ordnen(adresse: str) -> str:
    """Eingetippte KAI-Adresse vereinheitlichen: „kai-bsb.de“ → „https://kai-bsb.de“ (Peter 2026-11-18: ohne https:// kam
    nur „KAI nicht erreichbar: MissingSchema“), Leerzeichen und Schrägstrich am Ende weg."""
    a = (adresse or "").strip().rstrip("/")
    if a and "://" not in a:
        a = "https://" + a.lstrip("/")
    return a


class Kai:
    def __init__(self, adresse: str, token: str | None = None):
        self.adresse = adresse_ordnen(adresse)
        self.token = token
        self.s = requests.Session()
        self.s.headers["User-Agent"] = f"KAI-KI/{__version__}"

    def _post(self, pfad: str, daten: dict, timeout: float = 30):
        kopf = {"X-KI-Geraet": self.token} if self.token else {}
        try:
            r = self.s.post(f"{self.adresse}/api/ki-geraet/{pfad}", json=daten, headers=kopf, timeout=timeout)
        except requests.RequestException as e:
            raise KaiFehler(f"KAI nicht erreichbar unter {self.adresse} ({e.__class__.__name__}) — Adresse prüfen, z. B. https://kai-bsb.de "
                            "oder https://kai-bsb.de/test") from e
        if r.status_code == 401:
            raise KaiFehler("Das Gerät ist in KAI nicht (mehr) gekoppelt — bitte neu koppeln.")
        if r.status_code >= 400:
            try:
                msg = r.json().get("error")
            except ValueError:
                msg = None
            raise KaiFehler(msg or f"KAI antwortet mit {r.status_code}")
        return r.json()

    def koppeln(self, code: str) -> dict:
        r = self._post("koppeln", {"code": code, "info": geraete_info()})
        self.token = r["token"]
        return r

    def hallo(self, modell: str, zustand: str | None = None, fortschritt: str | None = None, prozent: int | None = None) -> dict:
        """Lebenszeichen; zustand laedt|bereit|fehler + Fortschritt erscheinen in KAI in der Gerätezeile."""
        info = {**geraete_info(), "zustand": zustand, "fortschritt": fortschritt, "prozent": prozent}
        return self._post("hallo", {"version": __version__, "modell": modell, "info": info})

    def auftrag(self, warten_ms: int = 20000, arten: tuple = ("lesen", "sprechen", "chat", "hoeren")) -> dict | None:
        r = self._post("auftrag", {"warten_ms": warten_ms, "arten": list(arten)}, timeout=warten_ms / 1000 + 30)
        return r if r.get("id") else None

    def zwischenstand(self, auftrag_id: int, text: str) -> bool:
        """Bisher geschriebener Chat-Text an KAI. False = in KAI gestoppt (oder vergeben) → aufhören zu schreiben."""
        try:
            return not self._post("zwischenstand", {"id": auftrag_id, "text": text}, timeout=10).get("stopp")
        except KaiFehler:
            return True                                     # kurz nicht erreichbar: weiterschreiben, das Ergebnis zählt

    def ergebnis(self, auftrag_id: int, text: str | None = None, fehler: str | None = None, dauer_ms: int | None = None,
                 tokens_ein: int | None = None, tokens_aus: int | None = None, ton: str | None = None) -> None:
        """ton = WAV als base64 (Auftragsart „sprechen“)."""
        self._post("ergebnis", {"id": auftrag_id, "text": text, "fehler": fehler, "dauer_ms": dauer_ms,
                                "tokens_ein": tokens_ein, "tokens_aus": tokens_aus, "ton": ton}, timeout=300)
