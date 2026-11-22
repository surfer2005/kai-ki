"""Fensteraufbau im echten macOS-Stil (läuft beim Bauen auf dem Mac-Runner von GitHub).

Peter 2026-11-18: „Anmeldefenster zu klein“ — in 0.1.14 standen KAI-Adresse und Code schmal in der Mitte und wurden in
der Höhe gestaucht, bis der Text abgeschnitten war. Geprüft wird: kein Eingabefeld/Knopf ist niedriger als nötig, die
Felder nutzen die Breite — auch in einem kleinen Fenster (dort scrollt die Seite statt zu stauchen)."""
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Fensteraufbau nur im macOS-Stil prüfbar")


@pytest.fixture()
def fenster(tmp_path, monkeypatch):
    monkeypatch.setenv("KAI_KI_ORDNER", str(tmp_path))
    from kai_ki import einstellungen
    monkeypatch.setattr(einstellungen, "ORDNER", tmp_path)
    monkeypatch.setattr(einstellungen, "DATEI", tmp_path / "einstellungen.json")   # leer = keine Verbindung, nichts startet
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    from kai_ki.app import Fenster
    f = Fenster(); f.show(); app.processEvents()
    yield f, app
    f.tray.hide(); f.hide(); f.deleteLater(); app.processEvents()


def _nicht_gestaucht(f):
    for name in ("adresse", "code", "koppeln_knopf", "entfernen_knopf", "modell", "start_knopf"):
        w = getattr(f, name)
        assert w.height() >= w.minimumSizeHint().height(), f"{name} gestaucht: {w.height()} < {w.minimumSizeHint().height()}"


def test_koppeln_felder_breit_und_lesbar(fenster):
    f, app = fenster
    _nicht_gestaucht(f)
    assert f.adresse.width() >= 350, f"KAI-Adresse zu schmal: {f.adresse.width()}"
    assert f.code.width() == f.adresse.width()


def test_kleines_fenster_scrollt_statt_zu_stauchen(fenster):
    f, app = fenster
    f.resize(560, 480); app.processEvents()
    _nicht_gestaucht(f)


def test_reiter_training_ohne_kopplung(fenster):
    """Reiter „Training“ (0.1.18): ohne Kopplung und ohne Daten ist nur „Einrichten“ möglich, nichts ist gestaucht."""
    f, app = fenster
    reiter = f.centralWidget()
    namen = [reiter.tabText(i) for i in range(reiter.count())]
    assert namen == ["Gerät", "Chat", "Training", "Aufräumen"]
    reiter.setCurrentIndex(2); app.processEvents()
    t = f.training
    assert not t.holen_knopf.isEnabled() and not t.start_knopf.isEnabled() and not t.abbruch_knopf.isEnabled()
    assert "koppeln" in t.daten_text.text()
    for w in (t.einricht_knopf, t.holen_knopf, t.start_knopf, t.quelle):
        assert w.height() >= w.minimumSizeHint().height()


def test_reiter_aufraeumen_ohne_ordner(fenster):
    """Reiter „Aufräumen“ (0.1.20): ohne Ordner und ohne Modell ist nur „Ordner wählen“ möglich, nichts ist gestaucht."""
    f, app = fenster
    reiter = f.centralWidget()
    reiter.setCurrentIndex(3); app.processEvents()
    a = f.aufraeumen
    assert a.ordner_knopf.isEnabled() and not a.start_knopf.isEnabled() and not a.ausfuehren_knopf.isEnabled()
    assert not a.abbruch_knopf.isEnabled() and not a.zurueck_knopf.isEnabled()
    for w in (a.ordner_knopf, a.start_knopf, a.ausfuehren_knopf, a.zurueck_knopf, a.max_dateien, a.seiten):
        assert w.height() >= w.minimumSizeHint().height(), w
    f.resize(560, 480); app.processEvents()
    assert a.tabelle.height() >= 100
