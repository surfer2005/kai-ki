"""Zugangsdaten der Postfächer im macOS-Schlüsselbund (ab 0.1.22) — nie in Dateien, nie im Protokoll.

Warum das Programm `security` von macOS und nicht das Python-Paket „keyring“ (oder das Security-Framework direkt):
- Ein Schlüsselbund-Eintrag merkt sich, welches Programm ihn angelegt hat, und lässt nur dieses ohne Rückfrage lesen. „KAI KI“ ist
  nicht bei Apple signiert, jede neue Version hat eine andere Unterschrift — über „keyring“ fragte macOS deshalb nach JEDEM Update
  nach dem Mac-Passwort. Angelegt über `/usr/bin/security` (von Apple, ändert sich nicht) gibt es diese Rückfrage nicht.
- `security` gehört zu macOS: nichts Neues im App-Paket, nichts, was PyInstaller beim Bauen vergessen könnte (keyring sucht seine
  Teile über Paket-Metadaten, die im gebauten Paket leicht fehlen).
Preis: der Wert steht für den Bruchteil einer Sekunde in der Befehlszeile des `security`-Aufrufs (base64, nur für Prozesse desselben
Benutzers sichtbar). Fehlermeldungen von `security` werden vom Wert bereinigt, bevor sie irgendwo erscheinen.
"""
import base64
import os
import subprocess
import sys

DIENST = "de.bsb.kai-ki.postfach"
BEZEICHNUNG = "KAI KI – Postfach"
PROGRAMM = "/usr/bin/security"
NICHT_GEFUNDEN = 44                                   # Rückgabewert von `security`, wenn es den Eintrag nicht gibt


class SchluesselbundFehler(Exception):
    pass


def _verpacken(wert: str) -> str:
    return "b64:" + base64.b64encode(wert.encode("utf-8")).decode("ascii")


def _auspacken(text: str) -> str:
    text = text.strip()
    if text.startswith("b64:"):
        return base64.b64decode(text[4:]).decode("utf-8")
    return text


def bereinigen(text: str, *geheimnisse) -> str:
    """Geheimnisse (und ihre base64-Form) aus einem Text entfernen — für Fehlermeldungen."""
    t = str(text or "")
    for g in geheimnisse:
        if not g:
            continue
        for form in (g, _verpacken(g), _verpacken(g)[4:]):
            if form:
                t = t.replace(form, "•••")
    return t


class MacSchluesselbund:
    """Einträge der Art „Generisches Kennwort“, Dienst DIENST, Konto = „<konto-id>/<art>“ (passwort bzw. refresh)."""
    bleibend = True

    def __init__(self, programm: str = PROGRAMM, ausfuehren=subprocess.run):
        self.programm, self.ausfuehren = programm, ausfuehren

    def _lauf(self, argumente: list, geheim: str = ""):
        try:
            return self.ausfuehren([self.programm, *argumente], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as ex:
            raise SchluesselbundFehler(f"Schlüsselbund nicht erreichbar: {bereinigen(ex, geheim)}") from None

    def speichern(self, konto: str, wert: str) -> None:
        if not wert:
            raise SchluesselbundFehler("Leerer Wert wird nicht gespeichert.")
        r = self._lauf(["add-generic-password", "-U", "-a", konto, "-s", DIENST, "-l", BEZEICHNUNG, "-w", _verpacken(wert)], wert)
        if r.returncode != 0:
            raise SchluesselbundFehler(f"Schlüsselbund: Speichern ging nicht ({bereinigen(r.stderr, wert).strip()[:200]})")

    def lesen(self, konto: str) -> str | None:
        r = self._lauf(["find-generic-password", "-a", konto, "-s", DIENST, "-w"])
        if r.returncode == NICHT_GEFUNDEN:
            return None
        if r.returncode != 0:
            raise SchluesselbundFehler(f"Schlüsselbund: Lesen ging nicht ({(r.stderr or '').strip()[:200]})")
        try:
            return _auspacken(r.stdout)
        except ValueError:
            raise SchluesselbundFehler("Schlüsselbund: Eintrag nicht lesbar") from None

    def loeschen(self, konto: str) -> None:
        r = self._lauf(["delete-generic-password", "-a", konto, "-s", DIENST])
        if r.returncode not in (0, NICHT_GEFUNDEN):
            raise SchluesselbundFehler(f"Schlüsselbund: Entfernen ging nicht ({(r.stderr or '').strip()[:200]})")


class Arbeitsspeicher:
    """Nur im Arbeitsspeicher (Tests, Entwicklung unter Linux) — vergisst alles beim Beenden."""
    bleibend = False

    def __init__(self):
        self.werte: dict = {}

    def speichern(self, konto: str, wert: str) -> None:
        if not wert:
            raise SchluesselbundFehler("Leerer Wert wird nicht gespeichert.")
        self.werte[konto] = wert

    def lesen(self, konto: str) -> str | None:
        return self.werte.get(konto)

    def loeschen(self, konto: str) -> None:
        self.werte.pop(konto, None)


def standard():
    """Auf dem Mac der Schlüsselbund, sonst (Entwicklung) nur Arbeitsspeicher."""
    if sys.platform == "darwin" and os.path.exists(PROGRAMM):
        return MacSchluesselbund()
    return Arbeitsspeicher()


def schluessel(konto_id: str, art: str) -> str:
    return f"{konto_id}/{art}"
