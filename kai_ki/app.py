"""Oberfläche der App „KAI KI“: koppeln, Modell wählen, Stand und erledigte Aufträge sehen. Läuft weiter im Hintergrund
(Symbol oben in der Menüleiste), solange die App offen ist."""
import sys
from datetime import datetime

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import __version__
from .arbeiter import Arbeiter
from .einstellungen import MODELLE, VORGABE_MODELL, laden, speichern
from .engine import Engine
from .kai import Kai, KaiFehler

STATUS_TEXT = {"aus": "nicht gestartet", "startet": "Modell wird geladen …", "bereit": "bereit – wartet auf Aufträge",
               "arbeitet": "liest gerade eine Seite …", "getrennt": "KAI nicht erreichbar", "fehler": "Fehler"}
STATUS_FARBE = {"bereit": "#2e7d5b", "arbeitet": "#1f6e9c", "startet": "#b07a17", "getrennt": "#b3412f", "fehler": "#b3412f", "aus": "#8a8f8c"}


class Bote(QObject):
    """Nachrichten aus dem Arbeits-Thread in die Oberfläche (Qt verlangt das über Signale)."""
    meldung = Signal(str)
    erledigt = Signal(dict)
    status = Signal(str)


def punkt(farbe: str) -> QIcon:
    pm = QPixmap(32, 32); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setBrush(QColor(farbe)); p.setPen(Qt.NoPen); p.drawEllipse(6, 6, 20, 20); p.end()
    return QIcon(pm)


class Fenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"KAI KI {__version__}")
        self.cfg = laden()
        self.arbeiter: Arbeiter | None = None
        self.engine: Engine | None = None
        self.bote = Bote()
        self.bote.meldung.connect(self.meldung)
        self.bote.erledigt.connect(self.erledigt)
        self.bote.status.connect(self.status_setzen)

        w = QWidget(); lay = QVBoxLayout(w)
        kopf = QLabel("<b>Eigene KI für KAI</b><br><span style='color:#666'>Liest Belegseiten mit einem Modell auf diesem Mac. "
                      "Die App holt die Aufträge bei KAI ab; die Bilder verlassen den Mac nicht.</span>")
        kopf.setWordWrap(True); lay.addWidget(kopf)

        g1 = QGroupBox("Verbindung zu KAI"); f1 = QFormLayout(g1)
        self.adresse = QLineEdit(self.cfg.get("kai_url", "")); self.adresse.setPlaceholderText("https://kai-bsb.de/test")
        self.code = QLineEdit(); self.code.setPlaceholderText("XXXX-XXXX (in KAI: Einstellungen → Schnittstellen → KI → Gerät koppeln)")
        self.koppeln_knopf = QPushButton("Koppeln"); self.koppeln_knopf.clicked.connect(self.koppeln)
        self.gekoppelt = QLabel(f"gekoppelt als „{self.cfg['name']}“" if self.cfg.get("token") else "noch nicht gekoppelt")
        f1.addRow("KAI-Adresse", self.adresse); f1.addRow("Code", self.code); f1.addRow("", self.koppeln_knopf); f1.addRow("Stand", self.gekoppelt)
        lay.addWidget(g1)

        g2 = QGroupBox("Modell"); f2 = QFormLayout(g2)
        self.modell = QComboBox()
        for k, m in MODELLE.items():
            self.modell.addItem(f"{m['name']} – {m['groesse']}", k)
        self.modell.setCurrentIndex(max(0, list(MODELLE).index(self.cfg.get("modell", VORGABE_MODELL))))
        self.modell.currentIndexChanged.connect(self.modell_gewechselt)
        zeile = QHBoxLayout(); self.start_knopf = QPushButton("Starten"); self.start_knopf.clicked.connect(self.starten)
        self.stopp_knopf = QPushButton("Anhalten"); self.stopp_knopf.clicked.connect(self.anhalten); self.stopp_knopf.setEnabled(False)
        zeile.addWidget(self.start_knopf); zeile.addWidget(self.stopp_knopf); zeile.addStretch()
        self.status = QLabel(STATUS_TEXT["aus"])
        f2.addRow("Modell", self.modell); f2.addRow("", zeile); f2.addRow("Status", self.status)
        lay.addWidget(g2)

        g3 = QGroupBox("Erledigte Aufträge"); v3 = QVBoxLayout(g3)
        self.liste = QListWidget(); v3.addWidget(self.liste)
        self.letzte_meldung = QLabel(""); self.letzte_meldung.setWordWrap(True); self.letzte_meldung.setStyleSheet("color:#666")
        v3.addWidget(self.letzte_meldung)
        lay.addWidget(g3, 1)
        self.setCentralWidget(w); self.resize(560, 620)

        self.tray = QSystemTrayIcon(punkt(STATUS_FARBE["aus"]), self)
        menu = QMenu(); a1 = QAction("Fenster öffnen", self); a1.triggered.connect(self.zeigen); a2 = QAction("Beenden", self); a2.triggered.connect(self.beenden)
        menu.addAction(a1); menu.addAction(a2); self.tray.setContextMenu(menu); self.tray.setToolTip("KAI KI"); self.tray.show()
        if self.cfg.get("token") and self.cfg.get("kai_url"):
            self.starten()

    # ---------- Aktionen ----------
    def koppeln(self):
        adresse, code = self.adresse.text().strip(), self.code.text().strip()
        if not adresse or not code:
            QMessageBox.warning(self, "KAI KI", "Bitte KAI-Adresse und Code eintragen."); return
        try:
            r = Kai(adresse).koppeln(code)
        except KaiFehler as e:
            QMessageBox.warning(self, "KAI KI", str(e)); return
        self.cfg.update({"kai_url": adresse, "token": r["token"], "name": r["name"]}); speichern(self.cfg)
        self.code.clear(); self.gekoppelt.setText(f"gekoppelt als „{r['name']}“")
        self.anhalten(); self.starten()

    def modell_gewechselt(self):
        self.cfg["modell"] = self.modell.currentData(); speichern(self.cfg)
        if self.arbeiter:
            self.anhalten(); self.starten()

    def starten(self):
        if not self.cfg.get("token"):
            QMessageBox.information(self, "KAI KI", "Erst mit KAI koppeln."); return
        if self.arbeiter and self.arbeiter.is_alive():
            return
        self.engine = Engine(self.cfg.get("modell", VORGABE_MODELL), melden=self.bote.meldung.emit)
        self.arbeiter = Arbeiter(Kai(self.cfg["kai_url"], self.cfg["token"]), self.engine,
                                 melden=self.bote.meldung.emit, erledigt=self.bote.erledigt.emit, status=self.bote.status.emit)
        self.arbeiter.start(); self.start_knopf.setEnabled(False); self.stopp_knopf.setEnabled(True)

    def anhalten(self):
        if self.arbeiter:
            self.arbeiter.halt.set(); self.arbeiter = None
        if self.engine:
            self.engine.stoppen(); self.engine = None
        self.status_setzen("aus"); self.start_knopf.setEnabled(True); self.stopp_knopf.setEnabled(False)

    def zeigen(self):
        self.show(); self.raise_(); self.activateWindow()

    def beenden(self):
        self.anhalten(); QApplication.quit()

    def closeEvent(self, ev):          # Fenster schließen = im Hintergrund weiterarbeiten
        ev.ignore(); self.hide()
        self.tray.showMessage("KAI KI", "Läuft im Hintergrund weiter (Symbol oben in der Menüleiste).", QSystemTrayIcon.Information, 3000)

    # ---------- Rückmeldungen ----------
    def meldung(self, text: str):
        self.letzte_meldung.setText(f"{datetime.now():%H:%M:%S}  {text}")

    def erledigt(self, e: dict):
        zeit = f"{datetime.now():%H:%M:%S}"
        self.liste.insertItem(0, f"{zeit}  Auftrag {e['id']}: " + (f"{e['dauer_s']:.0f} s, {e.get('tokens', 0)} Tokens" if e["ok"] else f"Fehler – {e.get('fehler', '')}"))
        while self.liste.count() > 200:
            self.liste.takeItem(self.liste.count() - 1)

    def status_setzen(self, s: str):
        self.status.setText(STATUS_TEXT.get(s, s))
        if s == "fehler":                 # nach einem Fehler gleich wieder „Starten“ anbieten
            self.start_knopf.setEnabled(True); self.stopp_knopf.setEnabled(False)
        self.tray.setIcon(punkt(STATUS_FARBE.get(s, "#b07a17")))   # unbekannt = Ladefortschritt (gelb); self.tray.setToolTip(f"KAI KI – {STATUS_TEXT.get(s, s)}")


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    f = Fenster(); f.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
