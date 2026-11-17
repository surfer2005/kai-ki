"""Der Arbeitsablauf: bei KAI melden, Auftrag holen, Seite vorbereiten, Modell fragen, Ergebnis zurück."""
import threading
import time

from .einstellungen import MODELLE
from .engine import Engine, antwort_ergaenzen
from .kai import Kai, KaiFehler
from .seite import texterkennung, zu_png


def aufgabe_mit_texterkennung(aufgabe: str, ocr_text: str) -> str:
    if not ocr_text:
        return aufgabe
    return aufgabe + "\n\nTexterkennung dieser Seite (auf dem Gerät, kann Lesefehler enthalten, nur als Hilfe):\n" + ocr_text[:8000]


class Arbeiter(threading.Thread):
    """Läuft im Hintergrund, solange die App offen ist. `melden(text)` und `erledigt(eintrag)` gehen an die Oberfläche."""

    def __init__(self, kai: Kai, engine: Engine, melden=print, erledigt=lambda e: None, status=lambda s: None):
        super().__init__(daemon=True)
        self.kai, self.engine = kai, engine
        self.melden, self.erledigt, self.status = melden, erledigt, status
        self.halt = threading.Event()

    def run(self) -> None:
        try:
            self.status("startet")
            self.engine.starten()
        except Exception as e:  # noqa: BLE001 — Fehler sichtbar machen, nicht abstürzen
            self.status("fehler"); self.melden(f"Modell konnte nicht starten: {e}")
            return
        letztes_hallo = 0.0
        while not self.halt.is_set():
            try:
                if time.time() - letztes_hallo > 60:
                    self.kai.hallo(MODELLE[self.engine.modell_key]["name"]); letztes_hallo = time.time()
                self.status("bereit")
                a = self.kai.auftrag()
                if a:
                    self.bearbeiten(a)
            except KaiFehler as e:
                self.status("getrennt"); self.melden(str(e)); self.halt.wait(15)
            except Exception as e:  # noqa: BLE001
                self.melden(f"Unerwarteter Fehler: {e}"); self.halt.wait(15)

    def bearbeiten(self, a: dict) -> None:
        self.status("arbeitet")
        beginn = time.time()
        try:
            seiten = a.get("seiten") or []
            if not seiten:
                raise ValueError("Auftrag ohne Seite")
            png = zu_png(seiten[0]["data"], seiten[0].get("mime", "image/jpeg"))
            ocr = texterkennung(png) if a.get("ocr") else ""
            text, ein, aus = self.engine.fragen(png, aufgabe_mit_texterkennung(a["aufgabe"], ocr), int(a.get("max_tokens") or 3000))
            text = antwort_ergaenzen(text, ocr)
            dauer = int((time.time() - beginn) * 1000)
            self.kai.ergebnis(a["id"], text=text, dauer_ms=dauer, tokens_ein=ein, tokens_aus=aus)
            self.erledigt({"id": a["id"], "dauer_s": dauer / 1000, "ok": True, "tokens": ein + aus})
        except KaiFehler:
            raise
        except Exception as e:  # noqa: BLE001 — Fehler an KAI melden, dort steht er beim Lieferschein
            self.kai.ergebnis(a["id"], fehler=str(e)[:500], dauer_ms=int((time.time() - beginn) * 1000))
            self.erledigt({"id": a["id"], "dauer_s": time.time() - beginn, "ok": False, "fehler": str(e)})
