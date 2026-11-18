"""Reiter „Training“ der App (Weg 3; Peter 2026-11-18: „Training-Zip mit in die App packen, gut für Laien“).

Vier Schritte untereinander, jeder mit einem Knopf: 1 Einrichten (einmalig) · 2 Trainingsdaten aus KAI holen · 3 Training starten ·
4 Ergebnis verwenden. Die Arbeit läuft in Threads; Rückmeldungen kommen über Signale (Qt verlangt das).
"""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from . import training as tr
from .einstellungen import bezeichnung, verbindungen

GRUEN = "#2e7d5b"
ROT = "#b3412f"
GRAU = "#666"


class TrainingBote(QObject):
    meldung = Signal(str)
    eingerichtet = Signal(str)                 # Fehler (leer = geklappt)
    daten = Signal(str, int, str, str)         # Datei, Anzahl, Quelle, Fehler
    zeile = Signal(str, dict)                  # Ausgabezeile, Stand
    fertig = Signal(dict)


def _gruppe(titel: str) -> tuple[QGroupBox, QVBoxLayout]:
    g = QGroupBox(titel); v = QVBoxLayout(g); g.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    return g, v


def _text(t: str, farbe: str = GRAU) -> QLabel:
    lab = QLabel(t); lab.setWordWrap(True); lab.setStyleSheet(f"color:{farbe}")
    return lab


class TrainingFenster(QScrollArea):
    """modell_verwenden(key): Modell in der App wählen und starten · ki_laeuft()/ki_anhalten(): das Lese-Modell braucht sonst den Speicher."""

    def __init__(self, cfg: dict, ki_laeuft, ki_anhalten, modell_verwenden):
        super().__init__()
        self.cfg, self.ki_laeuft, self.ki_anhalten, self.modell_verwenden = cfg, ki_laeuft, ki_anhalten, modell_verwenden
        self.bote = TrainingBote()
        self.bote.meldung.connect(self._meldung); self.bote.eingerichtet.connect(self._eingerichtet)
        self.bote.daten.connect(self._daten); self.bote.zeile.connect(self._zeile); self.bote.fertig.connect(self._fertig)
        self.datei: Path | None = None
        self.lauf: tr.Trainingslauf | None = None

        w = QWidget(); lay = QVBoxLayout(w)
        lay.addWidget(_text("Hier lernt die KI aus den Beispielen, die ihr in KAI gesammelt habt (Administration → KI → Protokoll: "
                            "„für Training freigeben“), welche Abfrage zu welcher Frage gehört und wie eine gute Antwort aussieht. "
                            "Die Zahlen selbst lernt sie nicht — die fragt sie weiter bei KAI ab. Alles bleibt auf diesem Mac."))

        g1, v1 = _gruppe("1  Einrichten (einmalig)")
        self.einricht_text = _text(""); v1.addWidget(self.einricht_text)
        z1 = QHBoxLayout(); self.einricht_knopf = QPushButton("Einrichten"); self.einricht_knopf.clicked.connect(self.einrichten)
        z1.addWidget(self.einricht_knopf); z1.addStretch(); v1.addLayout(z1)
        lay.addWidget(g1)

        g2, v2 = _gruppe("2  Trainingsdaten aus KAI")
        z2 = QHBoxLayout(); self.quelle = QComboBox(); self.quelle.setMinimumWidth(220)
        self.holen_knopf = QPushButton("Aus KAI holen"); self.holen_knopf.clicked.connect(self.holen)
        z2.addWidget(self.quelle, 1); z2.addWidget(self.holen_knopf); v2.addLayout(z2)
        self.daten_text = _text("Noch keine Trainingsdaten geholt."); v2.addWidget(self.daten_text)
        datei_knopf = QPushButton("Stattdessen eine Datei wählen …"); datei_knopf.setFlat(True); datei_knopf.setStyleSheet(f"color:{GRAU}; text-align:left")
        datei_knopf.clicked.connect(self.datei_waehlen); v2.addWidget(datei_knopf, 0, Qt.AlignLeft)
        lay.addWidget(g2)

        g3, v3 = _gruppe("3  Training")
        self.geraet_text = _text(tr.geraet_text(tr.speicher_gb(), tr.frei_gb())); v3.addWidget(self.geraet_text)
        z3 = QHBoxLayout(); self.start_knopf = QPushButton("Training starten"); self.start_knopf.clicked.connect(self.starten)
        self.abbruch_knopf = QPushButton("Abbrechen"); self.abbruch_knopf.clicked.connect(self.abbrechen); self.abbruch_knopf.setEnabled(False)
        z3.addWidget(self.start_knopf); z3.addWidget(self.abbruch_knopf); z3.addStretch(); v3.addLayout(z3)
        self.balken = QProgressBar(); self.balken.setRange(0, 100); self.balken.setValue(0); v3.addWidget(self.balken)
        self.schritt = _text("Dauert je nach Menge 20 bis 90 Minuten. Netzteil anschließen — der Mac schläft solange nicht ein.")
        v3.addWidget(self.schritt)
        self.protokoll = QPlainTextEdit(); self.protokoll.setReadOnly(True); self.protokoll.setMaximumBlockCount(400)
        self.protokoll.setMinimumHeight(120); self.protokoll.setStyleSheet("font-family: Menlo, monospace; font-size: 11px")
        v3.addWidget(self.protokoll)
        lay.addWidget(g3)

        g4, v4 = _gruppe("4  Ergebnis")
        self.ergebnis = _text(""); v4.addWidget(self.ergebnis)
        z4 = QHBoxLayout()
        self.eigen_knopf = QPushButton("Angepasstes Modell verwenden"); self.eigen_knopf.clicked.connect(lambda: self._verwenden("kai-eigen"))
        self.basis_knopf = QPushButton("Zurück zum Grundmodell"); self.basis_knopf.clicked.connect(lambda: self._verwenden(None))
        z4.addWidget(self.eigen_knopf); z4.addWidget(self.basis_knopf); z4.addStretch(); v4.addLayout(z4)
        v4.addWidget(_text("Danach in KAI unter Administration → KI → Systemcheck „Mit Modell prüfen“ und mit dem letzten Lauf des "
                           "Grundmodells vergleichen. Ist es schlechter, hier „Zurück zum Grundmodell“."))
        lay.addWidget(g4)
        lay.addStretch()

        self.setWidget(w); self.setWidgetResizable(True); self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.auffrischen()

    # ---------- Anzeige ----------
    def auffrischen(self):
        """Verbindungen, Einrichtung und Ergebnis neu anzeigen (auch nach dem Koppeln)."""
        aktuell = self.quelle.currentData()
        self.quelle.clear()
        for v in verbindungen(self.cfg):
            self.quelle.addItem(f"KAI {bezeichnung(v['kai_url'])}", v)
        if aktuell:
            i = next((i for i in range(self.quelle.count()) if self.quelle.itemData(i) == aktuell), 0)
            self.quelle.setCurrentIndex(i)
        if tr.eingerichtet():
            self.einricht_text.setText("Eingerichtet."); self.einricht_text.setStyleSheet(f"color:{GRUEN}")
            self.einricht_knopf.setText("Erneut einrichten")
        else:
            self.einricht_text.setText("Lädt die Werkzeuge für das Training (einige Minuten, ca. 2 GB). Das Grundmodell (ca. 19 GB) "
                                       "lädt das Training beim ersten Lauf selbst.")
            self.einricht_text.setStyleSheet(f"color:{GRAU}")
        self._knoepfe()
        info = tr.eigenes_info()
        if info:
            vn = info.get("fehlerwert_vorher"); nn = info.get("fehlerwert_nachher")
            besser = f" — Fehlerwert {self._zahl(vn)} → {self._zahl(nn)}" if vn is not None and nn is not None else ""
            self.ergebnis.setText(f"Angepasstes Modell vom {info.get('datum', '?')} aus {info.get('beispiele', '?')} Beispielen{besser}.")
        else:
            self.ergebnis.setText("Noch kein angepasstes Modell.")

    @staticmethod
    def _zahl(x):
        return f"{x:.2f}".replace(".", ",") if isinstance(x, (int, float)) else "?"

    def _knoepfe(self):
        laeuft = bool(self.lauf)
        bereit = tr.eingerichtet()
        self.einricht_knopf.setEnabled(not laeuft)
        self.holen_knopf.setEnabled(not laeuft and self.quelle.count() > 0)
        self.start_knopf.setEnabled(not laeuft and bereit and self.datei is not None)
        self.abbruch_knopf.setEnabled(laeuft)
        da = bool(tr.eigenes_info())
        self.eigen_knopf.setEnabled(not laeuft and da); self.basis_knopf.setEnabled(not laeuft and da)
        if self.quelle.count() == 0:
            self.daten_text.setText("Erst im Reiter „Gerät“ mit KAI koppeln.")

    def _meldung(self, t: str):
        self.schritt.setText(t)

    # ---------- 1 Einrichten ----------
    def einrichten(self):
        self.einricht_knopf.setEnabled(False)

        def arbeit():
            try:
                tr.einrichten(self.bote.meldung.emit); self.bote.eingerichtet.emit("")
            except Exception as e:  # noqa: BLE001 — jede Störung als Text in die Oberfläche
                self.bote.eingerichtet.emit(str(e))
        threading.Thread(target=arbeit, daemon=True).start()

    def _eingerichtet(self, fehler: str):
        if fehler:
            self.einricht_text.setText(f"Einrichten hat nicht geklappt: {fehler}"); self.einricht_text.setStyleSheet(f"color:{ROT}")
            self.einricht_knopf.setEnabled(True)
            return
        self.schritt.setText("Bereit — jetzt die Trainingsdaten holen.")
        self.auffrischen()

    # ---------- 2 Trainingsdaten ----------
    def holen(self):
        v = self.quelle.currentData()
        if not v:
            return
        self.holen_knopf.setEnabled(False); self.daten_text.setText("Trainingsdaten werden geholt …"); self.daten_text.setStyleSheet(f"color:{GRAU}")
        quelle = bezeichnung(v["kai_url"])

        def arbeit():
            from .kai import Kai
            try:
                antwort = Kai(v["kai_url"], v["token"]).training()
                datei, n = tr.daten_ablegen(antwort, quelle)
                self.bote.daten.emit(str(datei), n, f"KAI {quelle}", "")
            except Exception as e:  # noqa: BLE001
                self.bote.daten.emit("", 0, f"KAI {quelle}", str(e))
        threading.Thread(target=arbeit, daemon=True).start()

    def datei_waehlen(self):
        pfad, _ = QFileDialog.getOpenFileName(self, "Trainingsdatei wählen", str(Path.home() / "Downloads"), "Trainingsdatei (*.jsonl)")
        if pfad:
            n = sum(1 for z in Path(pfad).read_text("utf-8").splitlines() if z.strip())
            self._daten(pfad, n, Path(pfad).name, "")

    def _daten(self, datei: str, n: int, quelle: str, fehler: str):
        if fehler:
            self.datei = None
            self.daten_text.setText(f"Holen hat nicht geklappt: {fehler}"); self.daten_text.setStyleSheet(f"color:{ROT}")
        else:
            self.datei = Path(datei)
            hinweis = " — das ist wenig, die Wirkung bleibt klein (ab etwa 300 lohnt es sich deutlich)." if n < 300 else "."
            if n < 20:
                hinweis = " — für ein Training zu wenig. In KAI erst weitere Antworten „für Training freigeben“."
            self.daten_text.setText(f"{n} Beispiele aus {quelle}{hinweis}")
            self.daten_text.setStyleSheet(f"color:{ROT if n < 20 else GRUEN}")
            if n < 20:
                self.datei = None
        self._knoepfe()

    # ---------- 3 Training ----------
    def starten(self):
        if not self.datei:
            return
        if self.ki_laeuft():
            frage = QMessageBox.question(self, "Training starten",
                                         "Für das Training wird die KI angehalten — sie braucht den Arbeitsspeicher. Aufträge aus KAI "
                                         "warten so lange. Jetzt anhalten und das Training starten?")
            if frage != QMessageBox.Yes:
                return
            self.ki_anhalten()
        self.protokoll.clear(); self.balken.setValue(0); self.schritt.setText("Startet …"); self.schritt.setStyleSheet(f"color:{GRAU}")
        self.lauf = tr.Trainingslauf(self.datei, zeile=lambda z, st: self.bote.zeile.emit(z, st))
        self._knoepfe()

        def arbeit():
            try:
                stand = self.lauf.laufen()
            except Exception as e:  # noqa: BLE001
                stand = {"fehler": str(e)}
            self.bote.fertig.emit(stand)
        threading.Thread(target=arbeit, daemon=True).start()

    def abbrechen(self):
        if self.lauf:
            self.lauf.abbrechen()

    def _zeile(self, zeile: str, stand: dict):
        z = tr.sauber(zeile)
        if z.strip() and not set(z.strip()) <= set("─│╭╮╰╯ "):
            self.protokoll.appendPlainText(z)
        self.balken.setValue(tr.prozent(stand)); self.schritt.setText(tr.schritt_text(stand))

    def _fertig(self, stand: dict):
        self.lauf = None
        if stand.get("fertig"):
            self.balken.setValue(100)
            vn, nn = stand.get("vorher"), stand.get("nachher")
            satz = "Fertig — das angepasste Modell liegt bereit."
            if vn is not None and nn is not None:
                satz += f" Fehlerwert {self._zahl(vn)} → {self._zahl(nn)} ({'besser' if nn < vn else 'nicht besser — im Systemcheck prüfen'})."
            self.schritt.setText(satz); self.schritt.setStyleSheet(f"color:{GRUEN}")
            if self.datei and tr.DATEN in self.datei.parents:       # aus KAI geholte Daten nicht liegen lassen
                self.datei.unlink(missing_ok=True); self.datei = None
                self.daten_text.setText("Trainingsdaten nach dem Training gelöscht.")
        else:
            self.schritt.setText(f"Training nicht fertig: {stand.get('fehler') or 'unbekannter Fehler'}"); self.schritt.setStyleSheet(f"color:{ROT}")
        self.auffrischen()

    # ---------- 4 Ergebnis ----------
    def _verwenden(self, key):
        self.modell_verwenden(key)
