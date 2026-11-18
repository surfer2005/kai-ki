"""Oberfläche der App „KAI KI“: koppeln, Modell wählen, Stand und erledigte Aufträge sehen. Läuft weiter im Hintergrund
(Symbol oben in der Menüleiste), solange die App offen ist."""
import sys
from datetime import datetime

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSystemTrayIcon,
                               QTabWidget, QVBoxLayout, QWidget)

from . import __version__
from .arbeiter import Arbeiter
from .chatfenster import ChatFenster
from .einstellungen import MODELLE, VORGABE_MODELL, bezeichnung, laden, modelle_verfuegbar, speichern, verbindungen
from .engine import Engine
from .kai import Kai, KaiFehler, adresse_ordnen

STATUS_TEXT = {"aus": "nicht gestartet", "startet": "Modell wird geladen …", "bereit": "bereit – wartet auf Aufträge",
               "arbeitet": "liest gerade eine Seite …", "spricht": "spricht gerade einen Text …", "chattet": "beantwortet eine Frage aus dem KI-Chat …", "hoert": "erkennt gesprochene Sprache …", "getrennt": "KAI nicht erreichbar", "fehler": "Fehler"}
STATUS_FARBE = {"bereit": "#2e7d5b", "arbeitet": "#1f6e9c", "spricht": "#1f6e9c", "chattet": "#1f6e9c", "hoert": "#1f6e9c", "startet": "#b07a17", "getrennt": "#b3412f", "fehler": "#b3412f", "aus": "#8a8f8c"}


class Bote(QObject):
    """Nachrichten aus dem Arbeits-Thread in die Oberfläche (Qt verlangt das über Signale)."""
    meldung = Signal(str)
    erledigt = Signal(dict)
    status = Signal(str, str)        # Verbindung („Test“/„Produktion“), Status


def punkt(farbe: str) -> QIcon:
    pm = QPixmap(32, 32); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setBrush(QColor(farbe)); p.setPen(Qt.NoPen); p.drawEllipse(6, 6, 20, 20); p.end()
    return QIcon(pm)


class Fenster(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"KAI KI {__version__}")
        self.cfg = laden()
        # mehrere Verbindungen (Peter 2026-11-18: „Test und Produktion anbinden“) — je Verbindung ein Ablauf,
        # Modell, Sprecher und Hörer gibt es nur einmal auf dem Mac
        self.cfg["verbindungen"] = verbindungen(self.cfg)
        self.ablaeufe: list[Arbeiter] = []
        self.stati: dict = {}
        self.engine: Engine | None = None
        self.bote = Bote()
        self.bote.meldung.connect(self.meldung)
        self.bote.erledigt.connect(self.erledigt)
        self.bote.status.connect(self.status_setzen)

        w = QWidget(); lay = QVBoxLayout(w)
        kopf = QLabel("<b>Eigene KI für KAI</b><br><span style='color:#666'>Rechnet für KAI auf diesem Mac — Belege lesen, KI-Chat, Sprechen, "
                      "Hören — auch für mehrere KAI zugleich (z. B. Test und Produktion). Die App holt die Aufträge ab; nichts verlässt den Mac.</span>")
        kopf.setWordWrap(True); lay.addWidget(kopf)

        g1 = QGroupBox("Verbindungen zu KAI"); v1 = QVBoxLayout(g1)
        self.verb_liste = QListWidget(); self.verb_liste.setMinimumHeight(52); self.verb_liste.setMaximumHeight(96); v1.addWidget(self.verb_liste)
        z1 = QHBoxLayout(); self.entfernen_knopf = QPushButton("Verbindung entfernen"); self.entfernen_knopf.clicked.connect(self.verbindung_entfernen)
        z1.addStretch(); z1.addWidget(self.entfernen_knopf); v1.addLayout(z1)
        g1.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay.addWidget(g1)

        # Koppeln als eigener Block mit breiten Feldern (Peter 2026-11-18: „Anmeldefenster zu klein“ — das Formular im
        # macOS-Stil stand schmal und mittig, im zu knappen Fenster wurden die Felder bis zur Unleserlichkeit gestaucht)
        gk = QGroupBox("Neue Verbindung koppeln"); rk = QGridLayout(gk)
        rk.setColumnStretch(1, 1); rk.setHorizontalSpacing(12); rk.setVerticalSpacing(8)
        self.adresse = QLineEdit(); self.adresse.setPlaceholderText("https://kai-bsb.de  (Produktion)   oder   https://kai-bsb.de/test")
        self.code = QLineEdit(); self.code.setPlaceholderText("XXXX-XXXX")
        for feld in (self.adresse, self.code):
            feld.setMinimumHeight(30); feld.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.code.returnPressed.connect(self.koppeln)
        rk.addWidget(QLabel("KAI-Adresse"), 0, 0, Qt.AlignLeft | Qt.AlignVCenter); rk.addWidget(self.adresse, 0, 1)
        rk.addWidget(QLabel("Code"), 1, 0, Qt.AlignLeft | Qt.AlignVCenter); rk.addWidget(self.code, 1, 1)
        code_hilfe = QLabel("Den Code erzeugt KAI unter Einstellungen → Schnittstellen → KI → „Gerät koppeln“ (30 Minuten gültig).")
        code_hilfe.setWordWrap(True); code_hilfe.setStyleSheet("color:#888"); rk.addWidget(code_hilfe, 2, 1)
        self.koppeln_knopf = QPushButton("Koppeln"); self.koppeln_knopf.setMinimumWidth(120); self.koppeln_knopf.clicked.connect(self.koppeln)
        rk.addWidget(self.koppeln_knopf, 3, 1, Qt.AlignRight)
        self.gekoppelt = QLabel(""); self.gekoppelt.setWordWrap(True); self.gekoppelt.setStyleSheet("color:#888")
        rk.addWidget(self.gekoppelt, 4, 0, 1, 2)
        gk.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay.addWidget(gk)
        self.verbindungen_zeigen()

        g2 = QGroupBox("Modell"); f2 = QFormLayout(g2)
        # links ausgerichtet, Felder füllen die Breite (der macOS-Stil stellt ein Formular sonst schmal in die Mitte)
        f2.setFormAlignment(Qt.AlignLeft | Qt.AlignTop); f2.setLabelAlignment(Qt.AlignLeft)
        f2.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        g2.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.modell = QComboBox()
        auswahl = modelle_verfuegbar()          # das eigene Modell („KAI angepasst“) erst, wenn es trainiert ist
        if self.cfg.get("modell", VORGABE_MODELL) not in auswahl:   # z. B. eigenes Modell gelöscht → Grundmodell
            self.cfg["modell"] = VORGABE_MODELL
        for k, m in auswahl.items():
            self.modell.addItem(f"{m['name']} – {m['groesse']}", k)
        self.modell.setCurrentIndex(max(0, list(auswahl).index(self.cfg["modell"]) if self.cfg["modell"] in auswahl else 0))
        self.modell.currentIndexChanged.connect(self.modell_gewechselt)
        zeile = QHBoxLayout(); self.start_knopf = QPushButton("Starten"); self.start_knopf.clicked.connect(self.starten)
        self.stopp_knopf = QPushButton("Anhalten"); self.stopp_knopf.clicked.connect(self.anhalten); self.stopp_knopf.setEnabled(False)
        zeile.addWidget(self.start_knopf); zeile.addWidget(self.stopp_knopf); zeile.addStretch()
        self.status = QLabel(STATUS_TEXT["aus"])
        f2.addRow("Modell", self.modell); f2.addRow("", zeile); f2.addRow("Status", self.status)
        lay.addWidget(g2)

        g3 = QGroupBox("Erledigte Aufträge"); v3 = QVBoxLayout(g3)
        self.liste = QListWidget(); self.liste.setMinimumHeight(140); v3.addWidget(self.liste)
        self.letzte_meldung = QLabel(""); self.letzte_meldung.setWordWrap(True); self.letzte_meldung.setStyleSheet("color:#666")
        v3.addWidget(self.letzte_meldung)
        lay.addWidget(g3, 1)
        # Ist das Fenster zu niedrig, scrollt die Geräte-Seite — vorher quetschte Qt dann die Eingabefelder zusammen
        rolle = QScrollArea(); rolle.setWidget(w); rolle.setWidgetResizable(True); rolle.setFrameShape(QFrame.NoFrame)
        rolle.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Reiter: „Gerät“ (wie bisher) und „Chat“ (direkt mit dem Modell auf diesem Mac, Peter 2026-11-17)
        reiter = QTabWidget(); reiter.addTab(rolle, "Gerät")
        self.chat = ChatFenster(lambda: self.engine, self.hoerer_holen, self.sprecher_holen, self.cfg, speichern); reiter.addTab(self.chat, "Chat")
        self.setCentralWidget(reiter)
        # Startgröße: so hoch, dass alles ohne Scrollen passt, aber nie höher als der Bildschirm
        bild = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        self.resize(780, min(900, (bild.height() - 40) if bild else 900))
        self.setMinimumSize(560, 480)

        self.tray = QSystemTrayIcon(punkt(STATUS_FARBE["aus"]), self)
        menu = QMenu(); a1 = QAction("Fenster öffnen", self); a1.triggered.connect(self.zeigen); a2 = QAction("Beenden", self); a2.triggered.connect(self.beenden)
        menu.addAction(a1); menu.addAction(a2); self.tray.setContextMenu(menu); self.tray.setToolTip("KAI KI"); self.tray.show()
        if self.cfg["verbindungen"]:
            self.starten()

    def hoerer_holen(self):
        """Whisper: EIN Hörer für alle Verbindungen und den Chat-Reiter (sonst liefe das Modell doppelt)."""
        if not getattr(self, "_hoerer", None):
            from .hoerer import Hoerer
            self._hoerer = Hoerer()
        return self._hoerer

    def sprecher_holen(self):
        """Chatterbox: EIN Sprecher für alle Verbindungen und den Chat-Reiter."""
        if not getattr(self, "_sprecher", None):
            from .sprecher import Sprecher
            self._sprecher = Sprecher()
        return self._sprecher

    # ---------- Aktionen ----------
    def verbindungen_zeigen(self):
        zeilen = [f"{bezeichnung(v['kai_url'])}  –  {v['kai_url']}  –  gekoppelt als „{v.get('name', '')}“  –  "
                  f"{STATUS_TEXT.get(self.stati.get(bezeichnung(v['kai_url'])), self.stati.get(bezeichnung(v['kai_url'])) or 'nicht gestartet')}" for v in self.cfg["verbindungen"]]
        if self.verb_liste.count() == len(zeilen):        # nur Texte erneuern — die Auswahl (zum Entfernen) bleibt
            for i, z in enumerate(zeilen):
                self.verb_liste.item(i).setText(z)
        else:
            self.verb_liste.clear(); self.verb_liste.addItems(zeilen)
        self.gekoppelt.setText("Noch keine Verbindung — KAI-Adresse und Code eintragen, dann „Koppeln“." if not self.cfg["verbindungen"]
                               else "Weitere Verbindung (z. B. Produktion neben Test): Adresse und neuen Code aus dieser KAI eintragen.")

    def koppeln(self):
        adresse, code = adresse_ordnen(self.adresse.text()), self.code.text().strip().upper()
        if not adresse or not code:
            QMessageBox.warning(self, "KAI KI", "Bitte KAI-Adresse und Code eintragen."); return
        try:
            r = Kai(adresse).koppeln(code)
        except KaiFehler as e:
            QMessageBox.warning(self, "KAI KI", str(e)); return
        # gleiche Adresse = Gerät neu gekoppelt (ersetzt), sonst eine weitere Verbindung
        self.cfg["verbindungen"] = [v for v in self.cfg["verbindungen"] if v["kai_url"].rstrip("/") != adresse] + [{"kai_url": adresse, "token": r["token"], "name": r["name"]}]
        for k in ("kai_url", "token", "name"):     # alte Einzel-Felder nicht mehr pflegen
            self.cfg.pop(k, None)
        speichern(self.cfg)
        self.code.clear(); self.adresse.clear(); self.verbindungen_zeigen()
        self.anhalten(); self.starten()

    def verbindung_entfernen(self):
        i = self.verb_liste.currentRow()
        if i < 0 or i >= len(self.cfg["verbindungen"]):
            QMessageBox.information(self, "KAI KI", "Bitte erst eine Verbindung in der Liste auswählen."); return
        v = self.cfg["verbindungen"][i]
        if QMessageBox.question(self, "KAI KI", f"Verbindung „{bezeichnung(v['kai_url'])}“ ({v['kai_url']}) entfernen? Die App holt dort dann keine Aufträge mehr.") != QMessageBox.Yes:
            return
        self.cfg["verbindungen"].pop(i); self.cfg.pop("kai_url", None); self.cfg.pop("token", None); speichern(self.cfg)
        self.anhalten(); self.verbindungen_zeigen()
        if self.cfg["verbindungen"]:
            self.starten()

    def modell_gewechselt(self):
        self.cfg["modell"] = self.modell.currentData(); speichern(self.cfg)
        if self.ablaeufe:
            self.anhalten(); self.starten()

    def laeuft(self) -> bool:
        return any(a.is_alive() for a in self.ablaeufe)

    def starten(self):
        if not self.cfg["verbindungen"]:
            QMessageBox.information(self, "KAI KI", "Erst mit KAI koppeln."); return
        if self.laeuft():
            return
        self.engine = Engine(self.cfg.get("modell", VORGABE_MODELL), melden=self.bote.meldung.emit)
        self.ablaeufe = []
        for v in self.cfg["verbindungen"]:
            q = bezeichnung(v["kai_url"])
            a = Arbeiter(Kai(v["kai_url"], v["token"]), self.engine, melden=lambda t, q=q: self.bote.meldung.emit(f"{q}: {t}"),
                         erledigt=self.bote.erledigt.emit, status=lambda st, q=q: self.bote.status.emit(q, st),
                         sprecher=self.sprecher_holen(), hoerer=self.hoerer_holen(), quelle=q)
            self.ablaeufe.append(a); a.start()
        self.start_knopf.setEnabled(False); self.stopp_knopf.setEnabled(True)

    def anhalten(self):
        for a in self.ablaeufe:
            a.stoppen()
        self.ablaeufe = []
        if self.engine:
            self.engine.stoppen(); self.engine = None
        self.stati = {}
        self.status_setzen("", "aus"); self.start_knopf.setEnabled(True); self.stopp_knopf.setEnabled(False)

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
        if e.get("art") == "sprechen":
            text = f"{e['dauer_s']:.0f} s gerechnet, {e.get('ton_s', 0):.0f} s Ton" if e["ok"] else f"Fehler – {e.get('fehler', '')}"
            self.liste.insertItem(0, f"{zeit}  {e.get('quelle', '')} · Sprechen {e['id']}: {text}")
        elif e.get("art") == "hoeren":
            text = f"{e['dauer_s']:.0f} s, {e.get('zeichen', 0)} Zeichen erkannt" if e["ok"] else f"Fehler – {e.get('fehler', '')}"
            self.liste.insertItem(0, f"{zeit}  {e.get('quelle', '')} · Mikrofon {e['id']}: {text}")
        elif e.get("art") == "chat":
            text = (f"{e['dauer_s']:.0f} s, {e.get('tokens', 0)} Tokens" + (" (in KAI gestoppt)" if e.get("gestoppt") else "")) if e["ok"] else f"Fehler – {e.get('fehler', '')}"
            self.liste.insertItem(0, f"{zeit}  {e.get('quelle', '')} · Chat {e['id']}: {text}")
        else:
            self.liste.insertItem(0, f"{zeit}  {e.get('quelle', '')} · Auftrag {e['id']}: " + (f"{e['dauer_s']:.0f} s, {e.get('tokens', 0)} Tokens" if e["ok"] else f"Fehler – {e.get('fehler', '')}"))
        while self.liste.count() > 200:
            self.liste.takeItem(self.liste.count() - 1)

    def status_setzen(self, quelle: str, s: str):
        if quelle:
            self.stati[quelle] = s
        laeuft = self.laeuft()
        if not self.stati or not laeuft:
            text = STATUS_TEXT.get(s, s); farbe = STATUS_FARBE.get(s, "#b07a17")
        else:
            text = " · ".join(f"{q}: {STATUS_TEXT.get(x, x)}" for q, x in self.stati.items())
            werte = list(self.stati.values())
            farbe = next((STATUS_FARBE[x] for x in ("fehler", "getrennt") if x in werte), None) or \
                next((STATUS_FARBE.get(x, "#b07a17") for x in werte if x != "bereit"), STATUS_FARBE["bereit"])
        self.status.setText(text)
        if not laeuft:                    # kein Ablauf mehr (Fehler beim Start): „Starten“ anbieten
            self.start_knopf.setEnabled(True); self.stopp_knopf.setEnabled(False)
        else:
            self.start_knopf.setEnabled(False); self.stopp_knopf.setEnabled(True)
        self.tray.setIcon(punkt(farbe)); self.tray.setToolTip(f"KAI KI – {text}")
        self.verbindungen_zeigen()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    f = Fenster(); f.show()
    app.aboutToQuit.connect(f.anhalten)    # Cmd+Q / Abmelden: das Rechenprogramm mit beenden (lief sonst weiter)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
