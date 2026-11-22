"""Reiter „Aufräumen“ einmal ganz durchgespielt — mit einer gespielten KI, in einem Temp-Ordner: Ordner wählen, Vorschlag
erstellen, Ordner und Namen in der Liste ändern, ausführen, rückgängig. Läuft auf dem Mac (beim Bauen) und unter Linux ohne
Bildschirm (offscreen)."""
import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
if sys.platform != "darwin":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class GespielteKI:
    def __init__(self, laeuft=True):
        self.laeuft, self.fragen = laeuft, []

    def bereit(self):
        return self.laeuft

    def json_fragen(self, system, text):
        self.fragen.append(text)
        if "Datei: telekom.txt" in text:
            return '{"ordner": "Rechnungen/2026", "name": "2026-10 Telekom Rechnung", "grund": "Telekom-Rechnung"}'
        if "Datei: police.txt" in text:
            return '{"ordner": "Versicherungen", "name": "2026 Boot Police", "grund": "Versicherung"}'
        return '{"ordner": null, "name": null, "grund": "unklar"}'


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    return a


@pytest.fixture()
def antworten(monkeypatch):
    """Rückfragen automatisch mit „Ja“ beantworten, Meldungen mitschreiben."""
    from PySide6.QtWidgets import QMessageBox
    gesehen = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: (gesehen.append(a[2]), QMessageBox.Yes)[1])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: gesehen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: gesehen.append(a[2]))
    return gesehen


def _bestand(wurzel: Path) -> dict:
    return {p.relative_to(wurzel).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in wurzel.rglob("*") if p.is_file()}


def _warten(app, fenster, sekunden=20):
    ende = time.time() + sekunden
    while fenster.lauf is not None and time.time() < ende:
        app.processEvents(); time.sleep(0.01)
    app.processEvents()
    assert fenster.lauf is None, "Vorschlag wurde nicht fertig"


def _zeile(f, pfad):
    from kai_ki.aufraeumfenster import SP_DATEI
    return next(r for r in range(f.tabelle.rowCount()) if f.tabelle.item(r, SP_DATEI).text() == pfad)


def test_ganz_durchgespielt(tmp_path, app, antworten):
    from PySide6.QtCore import Qt
    from kai_ki import aufraeumen as af
    from kai_ki.aufraeumfenster import SP_NAME, SP_ORDNER, SP_UMBENENNEN, SP_VERSCHIEBEN, AufraeumFenster
    wurzel, prot = tmp_path / "Dokumente", tmp_path / "protokoll"
    wurzel.mkdir()
    (wurzel / "telekom.txt").write_text("Telekom Deutschland GmbH, Rechnung Oktober 2026")
    (wurzel / "kopie von telekom.txt").write_text("Telekom Deutschland GmbH, Rechnung Oktober 2026")
    (wurzel / "police.txt").write_text("Versicherungsschein Boot")
    (wurzel / "notiz.txt").write_text("irgendwas")
    os.utime(wurzel / "kopie von telekom.txt", (9_999_999_999, 9_999_999_999))
    vorher = _bestand(wurzel)
    ki = GespielteKI()
    f = AufraeumFenster(lambda: ki, prot)
    assert not f.start_knopf.isEnabled()
    assert f.ordner_setzen(wurzel) and f.start_knopf.isEnabled()

    f.vorschlag_starten(); _warten(app, f)
    assert f.tabelle.rowCount() == 4 and len(ki.fragen) == 3                 # die Kopie fragt die KI nicht
    e = {x["pfad"]: x for x in f.eintraege}
    assert e["kopie von telekom.txt"]["status"] == "doppelt" and e["notiz.txt"]["status"] == "unklar"
    assert f.tabelle.item(_zeile(f, "notiz.txt"), SP_VERSCHIEBEN).checkState() == Qt.Unchecked
    assert not (f.tabelle.item(_zeile(f, "notiz.txt"), SP_VERSCHIEBEN).flags() & Qt.ItemIsEnabled)   # ohne Ordner nicht wählbar
    assert f.tabelle.item(_zeile(f, "telekom.txt"), SP_UMBENENNEN).checkState() == Qt.Unchecked     # Umbenennen: Vorgabe aus
    assert _bestand(wurzel) == vorher                                         # der Vorschlag verändert nichts
    ordner = [f.ordner_tab.item(r, 0).text() for r in range(f.ordner_tab.rowCount())]
    assert ordner == ["Doppelt?", "Rechnungen/2026", "Versicherungen"]

    # Ordner in der Liste rechts umbenennen → gilt für alle Dateien dorthin
    f.ordner_tab.item(1, 0).setText("Rechnungen 2026"); app.processEvents()
    assert f.eintraege[[x["pfad"] for x in f.eintraege].index("telekom.txt")]["ordner"] == "Rechnungen 2026"
    # Namen vorschlag übernehmen (Häkchen), Police: böser Ordner von Hand → ungültig, nicht verschoben
    f.tabelle.item(_zeile(f, "telekom.txt"), SP_UMBENENNEN).setCheckState(Qt.Checked)
    f.tabelle.item(_zeile(f, "police.txt"), SP_ORDNER).setText("../../draussen")
    assert f.tabelle.item(_zeile(f, "police.txt"), SP_VERSCHIEBEN).checkState() == Qt.Unchecked
    # unklare Notiz: Ordner von Hand → wird wählbar und gewählt, eigener Name
    f.tabelle.item(_zeile(f, "notiz.txt"), SP_ORDNER).setText("Notizen")
    f.tabelle.item(_zeile(f, "notiz.txt"), SP_NAME).setText("Merkzettel")
    assert f.tabelle.item(_zeile(f, "notiz.txt"), SP_VERSCHIEBEN).checkState() == Qt.Checked
    assert f.tabelle.item(_zeile(f, "notiz.txt"), SP_UMBENENNEN).checkState() == Qt.Checked

    # gemerkt: ein neues Fenster lädt denselben Vorschlag
    assert len(AufraeumFenster(lambda: ki, prot).eintraege) == 4

    f.ausfuehren()
    nachher = _bestand(wurzel)
    assert sorted(nachher) == ["Doppelt?/kopie von telekom.txt", "Notizen/Merkzettel.txt", "Rechnungen 2026/2026-10 Telekom Rechnung.txt",
                               "police.txt"]
    assert sorted(nachher.values()) == sorted(vorher.values())               # nichts gelöscht
    assert not (tmp_path / "draussen").exists()
    assert [x["pfad"] for x in f.eintraege] == ["police.txt"]                  # Erledigtes verschwindet aus der Liste
    assert f.zurueck_knopf.isEnabled() and "kann rückgängig" in f.laeufe_liste.item(0).text()

    f.rueckgaengig()
    assert _bestand(wurzel) == vorher
    assert sorted(p.name for p in wurzel.iterdir()) == sorted(vorher)         # angelegte Ordner wieder weg
    assert "zurückgenommen" in f.laeufe_liste.item(0).text() and not f.zurueck_knopf.isEnabled()
    assert af.laeufe(prot)[0]["rueckgaengig"]


def test_ohne_modell_passiert_nichts(tmp_path, app, antworten):
    from kai_ki.aufraeumfenster import AufraeumFenster
    (tmp_path / "D").mkdir(); (tmp_path / "D" / "a.txt").write_text("a")
    ki = GespielteKI(laeuft=False)
    for holen in (lambda: None, lambda: ki):
        f = AufraeumFenster(holen, tmp_path / "p")
        f.ordner_setzen(tmp_path / "D")
        f.vorschlag_starten()
        assert f.lauf is None and f.tabelle.rowCount() == 0 and "Modell läuft nicht" in f.stand_text.text()
    assert ki.fragen == [] and (tmp_path / "D" / "a.txt").read_text() == "a"


def test_verbotene_ordner_werden_abgelehnt(tmp_path, app, antworten):
    from kai_ki.aufraeumfenster import AufraeumFenster
    f = AufraeumFenster(lambda: None, tmp_path / "p")
    assert not f.ordner_setzen(Path.home()) and not f.ordner_setzen("/")
    assert f.wurzel is None and len(antworten) == 2
