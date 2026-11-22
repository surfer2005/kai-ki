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
    assert ordner == ["Doppelt", "Rechnungen/2026", "Versicherungen"]

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
    assert sorted(nachher) == ["Doppelt/kopie von telekom.txt", "Notizen/Merkzettel.txt", "Rechnungen 2026/2026-10 Telekom Rechnung.txt",
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


class DokumenteKI(GespielteKI):
    def json_fragen(self, system, text):
        self.fragen.append(text)
        if "Datei: scan1.txt" in text:
            return '{"ordner": "rechnungen/2026", "name": "2026-10 Telekom Rechnung", "grund": "Telekom-Rechnung"}'
        if "Datei: foto.txt" in text:
            return '{"ordner": "Fotos", "name": "Lindau Urlaub", "grund": "Urlaubsfoto"}'
        if "Datei: zettel.txt" in text:
            return '{"ordner": "unaufgeräumt 3", "name": "Zettel", "grund": "passt zu den alten"}'
        return '{"ordner": null, "name": null, "grund": "unklar"}'


def test_was_aufraeumen_filter_und_kopf_haekchen(tmp_path, app, antworten):
    """Peters Fall: Dokumente mit „unaufgeräumt 1–4“; 1 und 2 aufräumen, 3 und 4 erst später (kein Ziel). Filter „Doppelt“ →
    Kopf „Verschieben“ aus → keine Kopie wird angefasst."""
    from PySide6.QtCore import Qt
    from kai_ki import aufraeumen as af
    from kai_ki.aufraeumfenster import (AW_AUFRAEUMEN, AW_KEIN_ZIEL, LOSE, SP_DATEI, SP_VERSCHIEBEN, AufraeumFenster)
    wurzel, prot = tmp_path / "Dokumente", tmp_path / "protokoll"
    for rel, inhalt in (("Rechnungen/2026/2026-09 Telekom Rechnung.pdf", "Telekom September"),
                        ("Versicherungen/Allianz Police.pdf", "Versicherungsschein"), ("lose.txt", "lose"),
                        ("unaufgeräumt 1/scan1.txt", "Telekom Oktober"), ("unaufgeräumt 1/scan2.txt", "Versicherungsschein"),
                        ("unaufgeräumt 1/Unter/zettel.txt", "Zettel"), ("unaufgeräumt 2/foto.txt", "Foto"),
                        ("unaufgeräumt 2/foto kopie.txt", "Foto"), ("unaufgeräumt 3/alt.txt", "alt"), ("unaufgeräumt 4/alt4.txt", "alt4")):
        (wurzel / rel).parent.mkdir(parents=True, exist_ok=True); (wurzel / rel).write_text(inhalt)
    os.utime(wurzel / "unaufgeräumt 2/foto kopie.txt", (9_999_999_999, 9_999_999_999))
    ki = DokumenteKI()
    f = AufraeumFenster(lambda: ki, prot)
    f.ordner_setzen(wurzel)
    namen = [f.auswahl_baum.topLevelItem(i).text(0) for i in range(f.auswahl_baum.topLevelItemCount())]
    assert namen[0] == "Lose Dateien direkt in „Dokumente“" and namen[1:] == ["Rechnungen", "unaufgeräumt 1", "unaufgeräumt 2",
                                                                             "unaufgeräumt 3", "unaufgeräumt 4", "Versicherungen"]
    assert "ganze Ordner" in f.auswahl_hinweis.text()
    f.auswahl_setzen("unaufgeräumt 1", aufraeumen=True); f.auswahl_setzen("unaufgeräumt 2", aufraeumen=True)
    f.auswahl_setzen("unaufgeräumt 3", kein_ziel=True); f.auswahl_setzen("unaufgeräumt 4", kein_ziel=True)
    assert f.auswahl() == {"lose": False, "ordner": ["unaufgeräumt 1", "unaufgeräumt 2"],
                           "auslassen": ["unaufgeräumt 3", "unaufgeräumt 4"]}
    u1 = f._finden("unaufgeräumt 1", laden=True)
    assert u1.checkState(AW_KEIN_ZIEL) == Qt.Checked                                    # „Aufräumen“ schließt „Kein Ziel“ ein
    unter = f._finden("unaufgeräumt 1/Unter", laden=True)
    assert unter.checkState(AW_AUFRAEUMEN) == Qt.Checked and not (unter.flags() & Qt.ItemIsEnabled)
    f.auswahl_setzen("unaufgeräumt 1", aufraeumen=False)
    assert unter.checkState(AW_AUFRAEUMEN) == Qt.Unchecked and unter.flags() & Qt.ItemIsEnabled   # Unterordner wieder frei
    f.auswahl_setzen("unaufgeräumt 1", aufraeumen=True)
    # gemerkt je Startordner: ein neues Fenster zeigt dieselbe Auswahl
    g = AufraeumFenster(lambda: ki, prot); g.ordner_setzen(wurzel)
    assert g.auswahl() == f.auswahl() and g.auswahl_baum.topLevelItem(0).data(0, Qt.UserRole) == LOSE

    vorher = _bestand(wurzel)
    f.vorschlag_starten(); _warten(app, f)
    pfade = sorted(x["pfad"] for x in f.eintraege)
    assert pfade == ["unaufgeräumt 1/Unter/zettel.txt", "unaufgeräumt 1/scan1.txt", "unaufgeräumt 1/scan2.txt",
                     "unaufgeräumt 2/foto kopie.txt", "unaufgeräumt 2/foto.txt"]
    assert _bestand(wurzel) == vorher
    vor_datei = ki.fragen[0].split("Datei:")[0]
    assert "2026-09 Telekom Rechnung.pdf" in vor_datei and "unaufgeräumt" not in vor_datei
    e = {x["pfad"]: x for x in f.eintraege}
    assert e["unaufgeräumt 1/scan1.txt"]["ordner"] == "Rechnungen/2026"
    assert e["unaufgeräumt 1/scan2.txt"]["gleich_wie"] == "Versicherungen/Allianz Police.pdf"
    assert e["unaufgeräumt 1/Unter/zettel.txt"]["status"] == "unklar"                  # „kein Ziel“ abgelehnt
    neu = {f.ordner_tab.item(r, 0).text(): f.ordner_tab.item(r, 2).text() for r in range(f.ordner_tab.rowCount())}
    assert neu == {"Doppelt": "neu", "Fotos": "neu", "Rechnungen/2026": ""}

    def sichtbar():
        return sorted(f.tabelle.item(r, SP_DATEI).text() for r in range(f.tabelle.rowCount()) if not f.tabelle.isRowHidden(r))
    assert f.filter_knoepfe["doppelt"].text() == "Doppelt (2)" and f.filter_knoepfe["alle"].text() == "Alle (5)"
    assert f.kopf.zustaende[SP_VERSCHIEBEN] == Qt.Checked
    f.filter_knoepfe["doppelt"].click()
    assert sichtbar() == ["unaufgeräumt 1/scan2.txt", "unaufgeräumt 2/foto kopie.txt"]
    f.kopf_geklickt(SP_VERSCHIEBEN)                                                    # Kopf-Häkchen „Verschieben“ aus
    assert not e["unaufgeräumt 1/scan2.txt"]["verschieben"] and not e["unaufgeräumt 2/foto kopie.txt"]["verschieben"]
    assert e["unaufgeräumt 1/scan1.txt"]["verschieben"] and e["unaufgeräumt 2/foto.txt"]["verschieben"]   # unsichtbare bleiben
    assert f.kopf.zustaende[SP_VERSCHIEBEN] == Qt.Unchecked
    f.filter_knoepfe["alle"].click()
    assert f.kopf.zustaende[SP_VERSCHIEBEN] == Qt.PartiallyChecked
    f.suche.setText("foto")
    assert sichtbar() == ["unaufgeräumt 2/foto kopie.txt", "unaufgeräumt 2/foto.txt"]
    # Suche, Filter und Häkchen stehen im gemerkten Vorschlag
    h = AufraeumFenster(lambda: ki, prot)
    assert h.suche.text() == "foto" and h.auswahl() == f.auswahl()
    assert not {x["pfad"]: x for x in h.eintraege}["unaufgeräumt 1/scan2.txt"]["verschieben"]
    f.suche.setText("")

    f.ausfuehren()
    nachher = _bestand(wurzel)
    assert "Rechnungen/2026/scan1.txt" in nachher and "Fotos/foto.txt" in nachher
    assert "unaufgeräumt 1/scan2.txt" in nachher and "unaufgeräumt 2/foto kopie.txt" in nachher     # Kopien nicht angefasst
    assert sorted(nachher.values()) == sorted(vorher.values())
    # die Auswahl bleibt gemerkt; „unaufgeräumt 2“ ist nicht leer (die Kopie liegt noch dort) und bleibt angeboten
    assert f.auswahl()["ordner"] == ["unaufgeräumt 1", "unaufgeräumt 2"]
    f.rueckgaengig()
    assert _bestand(wurzel) == vorher
    assert af.laeufe(prot)[0]["quellen"] == ["unaufgeräumt 1", "unaufgeräumt 2"]


def test_leere_quellordner_werden_genannt_und_nicht_mehr_angeboten(tmp_path, app, antworten):
    from kai_ki.aufraeumfenster import AufraeumFenster
    wurzel, prot = tmp_path / "Dokumente", tmp_path / "protokoll"
    (wurzel / "unaufgeräumt 2").mkdir(parents=True); (wurzel / "unaufgeräumt 2" / "foto.txt").write_text("Foto")
    (wurzel / "Boot").mkdir(); (wurzel / "Boot" / "Vertrag.pdf").write_text("Vertrag")
    ki = DokumenteKI()
    f = AufraeumFenster(lambda: ki, prot); f.ordner_setzen(wurzel)
    f.auswahl_setzen("unaufgeräumt 2", aufraeumen=True)
    f.vorschlag_starten(); _warten(app, f)
    f.ausfuehren()
    assert (wurzel / "unaufgeräumt 2").is_dir() and (wurzel / "Fotos" / "foto.txt").exists()       # nie gelöscht
    assert any("jetzt leer" in t and "unaufgeräumt 2" in t for t in antworten)
    namen = [f.auswahl_baum.topLevelItem(i).data(0, 256) for i in range(f.auswahl_baum.topLevelItemCount())]
    assert "unaufgeräumt 2" not in namen and "Fotos" in namen
    fotos = f._finden("Fotos")
    assert "aus früheren Läufen" in fotos.text(0)
