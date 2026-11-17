"""Der Arbeitsablauf: bei KAI melden, Auftrag holen, Seite vorbereiten, Modell fragen, Ergebnis zurück.
Drei Auftragsarten: „lesen“ (Seite → JSON, Bildmodell), „chat“ (Gespräch aus KAI, Antwort wird beim Schreiben
zurückgemeldet) und „sprechen“ (Text → Tonspur, Chatterbox in sprecher.py)."""
import base64
import threading
import time

from .einstellungen import MODELLE
from .engine import Engine, antwort_ergaenzen, chat_nachrichten
from .kai import Kai, KaiFehler
from .seite import texterkennung, zu_png
from .sprecher import Sprecher
from .hoerer import Hoerer


def aufgabe_mit_texterkennung(aufgabe: str, ocr_text: str) -> str:
    if not ocr_text:
        return aufgabe
    return aufgabe + "\n\nTexterkennung dieser Seite (auf dem Gerät, kann Lesefehler enthalten, nur als Hilfe):\n" + ocr_text[:8000]


class Arbeiter(threading.Thread):
    """Läuft im Hintergrund, solange die App offen ist. `melden(text)` und `erledigt(eintrag)` gehen an die Oberfläche."""

    def __init__(self, kai: Kai, engine: Engine, melden=print, erledigt=lambda e: None, status=lambda s: None):
        super().__init__(daemon=True)
        self.kai, self.engine = kai, engine
        self.halt = threading.Event()
        # Nach „Anhalten“/Modellwechsel läuft dieser Ablauf noch kurz weiter — seine Meldungen dürfen die Oberfläche des
        # neuen Ablaufs nicht mehr verändern (ein später „Fehler“ setzte sonst die Knöpfe zurück, obwohl alles lief)
        lebt = lambda f: (lambda *a, **k: None if self.halt.is_set() else f(*a, **k))  # noqa: E731
        self.melden, self.erledigt, self.status = lebt(melden), lebt(erledigt), lebt(status)
        self.sprecher = Sprecher()
        self.hoerer = Hoerer()

    def melden_kai(self, zustand: str, fortschritt: str | None = None, prozent: int | None = None) -> None:
        """Zustand an KAI (Gerätezeile); ohne Verbindung still weiter — das Laden hängt nicht an KAI."""
        try:
            self.kai.hallo(MODELLE[self.engine.modell_key]["name"], zustand, fortschritt, prozent)
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        letzt = [0.0]

        def fortschritt(text: str, prozent: int) -> None:
            self.status(text)                                  # in der App sofort
            if time.time() - letzt[0] > 15:                    # an KAI alle 15 s
                letzt[0] = time.time(); self.melden_kai("laedt", text, prozent)
        try:
            self.status("startet"); self.melden_kai("laedt", "Rechenprogramm und Modell werden vorbereitet …", 0)
            self.engine.starten(fortschritt=fortschritt)
        except Exception as e:  # noqa: BLE001 — Fehler sichtbar machen, nicht abstürzen
            self.status("fehler"); self.melden(f"Modell konnte nicht starten: {e}")
            self.melden_kai("fehler", f"Modell konnte nicht starten: {e}"[:300])
            return
        letztes_hallo = 0.0
        while not self.halt.is_set():
            try:
                if time.time() - letztes_hallo > 60:
                    self.kai.hallo(MODELLE[self.engine.modell_key]["name"], "bereit"); letztes_hallo = time.time()
                self.status("bereit")
                a = self.kai.auftrag()
                if a:
                    {"sprechen": self.sprechen, "chat": self.chatten, "hoeren": self.hoeren}.get(a.get("art"), self.bearbeiten)(a)
            except KaiFehler as e:
                self.status("getrennt"); self.melden(str(e)); self.halt.wait(15)
            except Exception as e:  # noqa: BLE001
                self.melden(f"Unerwarteter Fehler: {e}"); self.halt.wait(15)

    def sprechen(self, a: dict) -> None:
        """Text → Tonspur. Beim ersten Mal wird der Sprecher eingerichtet (einige Minuten) — der Stand geht an KAI."""
        self.status("spricht")
        beginn, letzt = time.time(), [0.0]

        def fortschritt(text: str) -> None:
            self.status(text)
            if time.time() - letzt[0] > 15:
                letzt[0] = time.time(); self.melden_kai("laedt", text)
        try:
            wav, sekunden = self.sprecher.sprechen(a.get("text") or "", a.get("sprache") or "de", a.get("lebhaft"), a.get("tempo"),
                                                   a.get("stimme"), fortschritt=fortschritt)
            dauer = int((time.time() - beginn) * 1000)
            self.kai.ergebnis(a["id"], text=f"{sekunden:.1f} s Ton", dauer_ms=dauer, ton=base64.b64encode(wav).decode("ascii"))
            self.erledigt({"id": a["id"], "dauer_s": dauer / 1000, "ok": True, "tokens": 0, "art": "sprechen", "ton_s": sekunden})
        except KaiFehler:
            raise
        except Exception as e:  # noqa: BLE001 — Fehler an KAI melden, dort steht er bei der Hörprobe
            self.kai.ergebnis(a["id"], fehler=str(e)[:500], dauer_ms=int((time.time() - beginn) * 1000))
            self.erledigt({"id": a["id"], "dauer_s": time.time() - beginn, "ok": False, "fehler": str(e), "art": "sprechen"})
        finally:
            self.melden_kai("bereit")

    def stoppen(self) -> None:
        self.halt.set(); self.sprecher.stoppen(); self.hoerer.stoppen()

    def hoeren(self, a: dict) -> None:
        """Mikrofon im KI-Chat: Aufnahme (WAV) → Text. Beim ersten Mal wird Whisper eingerichtet — der Stand geht an KAI."""
        self.status("hoert")
        beginn, letzt = time.time(), [0.0]

        def fortschritt(text: str) -> None:
            self.status(text)
            if time.time() - letzt[0] > 3:
                letzt[0] = time.time(); self.kai.zwischenstand(a["id"], text)
        try:
            text = self.hoerer.hoeren(base64.b64decode(a.get("ton") or ""), a.get("sprache") or "de", fortschritt=fortschritt)
            dauer = int((time.time() - beginn) * 1000)
            self.kai.ergebnis(a["id"], text=text, dauer_ms=dauer)
            self.erledigt({"id": a["id"], "dauer_s": dauer / 1000, "ok": True, "art": "hoeren", "zeichen": len(text)})
        except KaiFehler:
            raise
        except Exception as e:  # noqa: BLE001 — Fehler an KAI melden, dort steht er am Mikrofon
            self.kai.ergebnis(a["id"], fehler=str(e)[:500], dauer_ms=int((time.time() - beginn) * 1000))
            self.erledigt({"id": a["id"], "dauer_s": time.time() - beginn, "ok": False, "fehler": str(e), "art": "hoeren"})

    def chatten(self, a: dict) -> None:
        """Gespräch aus KAI: Antwort schreiben, den Zwischenstand alle 0,7 s melden (in KAI erscheint sie beim Schreiben)."""
        self.status("chattet")
        beginn, letzt, weiter = time.time(), [0.0], [True]

        def beim_schreiben(text: str) -> bool:
            if time.time() - letzt[0] > 0.7:
                letzt[0] = time.time(); weiter[0] = self.kai.zwischenstand(a["id"], text)
            return weiter[0]
        try:
            ocr = texterkennung if a.get("ocr") else (lambda png: "")
            nachrichten = chat_nachrichten(a.get("nachrichten") or [], bild=lambda s: zu_png(s["data"], s.get("mime", "image/jpeg")), ocr=ocr)
            text, ein, aus = self.engine.chat(nachrichten, int(a.get("max_tokens") or 1500), float(a.get("temperatur") or 0.3), beim_schreiben)
            dauer = int((time.time() - beginn) * 1000)
            if weiter[0]:
                self.kai.ergebnis(a["id"], text=text, dauer_ms=dauer, tokens_ein=ein, tokens_aus=aus)
            self.erledigt({"id": a["id"], "dauer_s": dauer / 1000, "ok": True, "tokens": ein + aus, "art": "chat", "gestoppt": not weiter[0]})
        except KaiFehler:
            raise
        except Exception as e:  # noqa: BLE001 — Fehler an KAI melden, dort steht er im Chat
            self.kai.ergebnis(a["id"], fehler=str(e)[:500], dauer_ms=int((time.time() - beginn) * 1000))
            self.erledigt({"id": a["id"], "dauer_s": time.time() - beginn, "ok": False, "fehler": str(e), "art": "chat"})

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
