"""Reiter „Aufräumen“ der App (Peter 2026-11-22: „Könnte ich meiner KI auf dem Mac sagen: räum die Dokumente auf?“).

Ordner wählen → „Vorschlag erstellen“ (die KI liest jede Datei und schlägt Zielordner und Namen vor — es wird NICHTS verändert) →
in der Liste prüfen und ändern → „Ausgewählte ausführen“ (verschieben/umbenennen; nie löschen, nie überschreiben) → bei Bedarf
„Letzten Lauf rückgängig machen“. Die Regeln stehen in aufraeumen.py; hier nur Anzeige und Hintergrund-Thread.
"""
import os
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSpinBox, QSplitter, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import aufraeumen as af
from . import einstellungen

GRUEN = "#2e7d5b"
ROT = "#b3412f"
GELB = "#9a6b0f"
GRAU = "#666"
STATUS = {"vorschlag": ("Vorschlag", None), "unklar": ("unklar", ROT), "doppelt": ("doppelt?", GELB),
          "bleibt": ("liegt schon richtig", GRAU), "fehler": ("Fehler", ROT), "hand": ("von dir", GRUEN)}
SP_VERSCHIEBEN, SP_DATEI, SP_ORDNER, SP_UMBENENNEN, SP_NAME, SP_HINWEIS = range(6)
UNGUELTIG_ORDNER = ("Ungültiger Ordnername: nicht mit „/“ oder „~“ beginnen, kein „..“, keine versteckten Ordner, keine Zeichen "
                    "\\ : * ? \" < > |, höchstens 4 Ebenen.")
UNGUELTIG_NAME = "Ungültiger Dateiname: kein „/“, nicht mit „.“ beginnen, keine Zeichen \\ : * ? \" < > |."


class AufraeumBote(QObject):
    stand = Signal(int, int, str)
    eintrag = Signal(object)
    fertig = Signal(object)


class RechtsKuerzen(QStyledItemDelegate):
    """Hinweis-Spalte: vorne lesbar („unklar – …“), hinten gekürzt (die übrigen Spalten kürzen in der Mitte, damit die Endung bleibt)."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.ElideRight


def _text(t: str, farbe: str = GRAU) -> QLabel:
    lab = QLabel(t); lab.setWordWrap(True); lab.setStyleSheet(f"color:{farbe}")
    return lab


def _kurz(pfad) -> str:
    p, h = str(pfad), str(Path.home())
    return "~" + p[len(h):] if p == h or p.startswith(h + os.sep) else p


class AufraeumFenster(QWidget):
    """engine_holen() → laufende Engine oder None. protokoll_ordner: Protokolle der Läufe + der zuletzt erstellte Vorschlag."""

    def __init__(self, engine_holen, protokoll_ordner: Path | None = None):
        super().__init__()
        self.engine_holen = engine_holen
        self.prot = Path(protokoll_ordner or einstellungen.ORDNER / "aufraeumen")
        self.wurzel: Path | None = None
        self.eintraege: list = []
        self.lauf: af.Vorschlagslauf | None = None
        self._fuellen = False
        self.bote = AufraeumBote()
        self.bote.stand.connect(self._stand); self.bote.eintrag.connect(self._eintrag); self.bote.fertig.connect(self._fertig)

        lay = QVBoxLayout(self)
        lay.addWidget(_text("Die KI auf diesem Mac schlägt vor, wie die Dateien eines Ordners sortiert und benannt werden. Verändert "
                            "wird erst, wenn du „Ausgewählte ausführen“ klickst — dabei wird <b>nie etwas gelöscht oder überschrieben</b>, "
                            "und jeder Lauf lässt sich rückgängig machen. Tipp: zuerst an einer <b>Kopie</b> eines Ordners ausprobieren."))

        z1 = QHBoxLayout()
        self.ordner_knopf = QPushButton("Ordner wählen …"); self.ordner_knopf.clicked.connect(self.ordner_waehlen)
        self.ordner_text = QLabel("Noch kein Ordner gewählt."); self.ordner_text.setStyleSheet(f"color:{GRAU}")
        self.ordner_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        z1.addWidget(self.ordner_knopf); z1.addWidget(self.ordner_text, 1); lay.addLayout(z1)

        z2 = QHBoxLayout()
        self.unterordner = QCheckBox("Unterordner einbeziehen"); self.unterordner.setChecked(True)
        self.inhalt = QCheckBox("Inhalt lesen (Texterkennung)"); self.inhalt.setChecked(True)
        self.inhalt.setToolTip("Aus: nur nach Name, Typ und Datum einordnen — viel schneller, aber ungenauer.")
        z2.addWidget(self.unterordner); z2.addWidget(self.inhalt); z2.addStretch(); lay.addLayout(z2)
        z3 = QHBoxLayout()
        self.seiten = QSpinBox(); self.seiten.setRange(1, 10); self.seiten.setValue(2)
        self.seiten.setToolTip("So viele Seiten liest die App je PDF (Textebene bzw. Texterkennung).")
        self.max_dateien = QSpinBox(); self.max_dateien.setRange(1, 5000); self.max_dateien.setValue(300); self.max_dateien.setSingleStep(50)
        self.max_dateien.setToolTip("Mehr Dateien = längerer Lauf. Die KI braucht je Datei einige Sekunden.")
        z3.addWidget(QLabel("PDF-Seiten lesen:")); z3.addWidget(self.seiten); z3.addSpacing(16)
        z3.addWidget(QLabel("höchstens")); z3.addWidget(self.max_dateien); z3.addWidget(QLabel("Dateien")); z3.addStretch(); lay.addLayout(z3)

        z4 = QHBoxLayout()
        self.start_knopf = QPushButton("Vorschlag erstellen"); self.start_knopf.clicked.connect(self.vorschlag_starten)
        self.abbruch_knopf = QPushButton("Abbrechen"); self.abbruch_knopf.clicked.connect(self.abbrechen)
        self.balken = QProgressBar(); self.balken.setRange(0, 1); self.balken.setValue(0)
        z4.addWidget(self.start_knopf); z4.addWidget(self.abbruch_knopf); z4.addWidget(self.balken, 1); lay.addLayout(z4)
        self.stand_text = _text(""); lay.addWidget(self.stand_text)

        self.tabelle = QTableWidget(0, 6)
        self.tabelle.setHorizontalHeaderLabels(["Verschieben", "Datei", "Zielordner", "Umbenennen", "Neuer Name", "Hinweis"])
        self.tabelle.verticalHeader().setVisible(False)
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        # Häkchen-Spalten so breit wie ihr Titel, die vier Textspalten teilen sich den Rest (kein seitliches Rollen; lange Namen
        # stehen im Tooltip bzw. beim Doppelklick ganz da)
        kopf = self.tabelle.horizontalHeader()
        for sp in (SP_VERSCHIEBEN, SP_UMBENENNEN):
            kopf.setSectionResizeMode(sp, QHeaderView.ResizeToContents)
        for sp in (SP_DATEI, SP_ORDNER, SP_NAME, SP_HINWEIS):
            kopf.setSectionResizeMode(sp, QHeaderView.Stretch)
        self.tabelle.setTextElideMode(Qt.ElideMiddle); self.tabelle.setWordWrap(False)
        self._kuerzen = RechtsKuerzen(self.tabelle); self.tabelle.setItemDelegateForColumn(SP_HINWEIS, self._kuerzen)
        self.tabelle.setMinimumHeight(140)
        self.tabelle.itemChanged.connect(self._zelle_geaendert)
        self.ordner_tab = QTableWidget(0, 2)
        self.ordner_tab.setHorizontalHeaderLabels(["Zielordner", "Dateien"])
        self.ordner_tab.verticalHeader().setVisible(False)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ordner_tab.setToolTip("Doppelklick auf einen Ordner: umbenennen — gilt für alle Dateien, die dorthin sollen.")
        self.ordner_tab.itemChanged.connect(self._ordner_geaendert)
        rechts = QWidget(); rv = QVBoxLayout(rechts); rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.ordner_tab, 1); rv.addWidget(_text("Doppelklick = Ordner umbenennen (für alle Dateien darin)."))
        teiler = QSplitter(Qt.Horizontal); teiler.addWidget(self.tabelle); teiler.addWidget(rechts)
        teiler.setStretchFactor(0, 4); teiler.setStretchFactor(1, 1); teiler.setChildrenCollapsible(False)
        rechts.setMinimumWidth(150); teiler.setSizes([620, 170])
        self.ordner_tab.setWordWrap(False)
        lay.addWidget(teiler, 1)

        z5 = QHBoxLayout()
        self.alle_knopf = QPushButton("Alle Vorschläge an"); self.alle_knopf.clicked.connect(lambda: self.alle(True))
        self.keine_knopf = QPushButton("Alle aus"); self.keine_knopf.clicked.connect(lambda: self.alle(False))
        self.ausfuehren_knopf = QPushButton("Ausgewählte ausführen"); self.ausfuehren_knopf.clicked.connect(self.ausfuehren)
        z5.addWidget(self.alle_knopf); z5.addWidget(self.keine_knopf); z5.addStretch(); z5.addWidget(self.ausfuehren_knopf)
        lay.addLayout(z5)

        g = QGroupBox("Frühere Läufe"); gv = QVBoxLayout(g)
        self.laeufe_liste = QListWidget(); self.laeufe_liste.setMaximumHeight(72); gv.addWidget(self.laeufe_liste)
        z6 = QHBoxLayout()
        self.zurueck_knopf = QPushButton("Letzten Lauf rückgängig machen"); self.zurueck_knopf.clicked.connect(self.rueckgaengig)
        z6.addWidget(_text(f"Protokolle: {_kurz(self.prot)}")); z6.addStretch(); z6.addWidget(self.zurueck_knopf); gv.addLayout(z6)
        g.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay.addWidget(g)

        self._vorschlag_laden()
        self.laeufe_zeigen()
        self._knoepfe()

    # ---------- Zustand ----------
    def _knoepfe(self):
        laeuft = self.lauf is not None
        for w in (self.ordner_knopf, self.unterordner, self.inhalt, self.seiten, self.max_dateien):
            w.setEnabled(not laeuft)
        self.start_knopf.setEnabled(not laeuft and self.wurzel is not None)
        self.abbruch_knopf.setEnabled(laeuft)
        self.alle_knopf.setEnabled(bool(self.eintraege)); self.keine_knopf.setEnabled(bool(self.eintraege))
        self.ausfuehren_knopf.setEnabled(not laeuft and any(e.get("verschieben") or (e.get("umbenennen") and e.get("name")) for e in self.eintraege))
        self.zurueck_knopf.setEnabled(not laeuft and any(not l["rueckgaengig"] for l in af.laeufe(self.prot)))

    def _meldung(self, text: str, farbe: str = GRAU):
        self.stand_text.setText(text); self.stand_text.setStyleSheet(f"color:{farbe}")

    def _speichern(self):
        if self.wurzel is not None:
            try:
                af.vorschlag_speichern(self.prot, self.wurzel, self.eintraege)
            except OSError:
                pass

    def _vorschlag_laden(self):
        v = af.vorschlag_laden(self.prot)
        if not v or not v.get("eintraege"):
            return
        self.wurzel = Path(v["wurzel"]); self.eintraege = v["eintraege"]
        self.ordner_text.setText(_kurz(self.wurzel)); self.ordner_text.setToolTip(str(self.wurzel))
        self.tabelle_fuellen()
        datum = (v.get("datum") or "")[:16].replace("T", " ")
        self._meldung(f"Vorschlag vom {datum} geladen ({len(self.eintraege)} Dateien). Vor dem Ausführen kurz prüfen — "
                      "seitdem geänderte oder verschwundene Dateien werden beim Ausführen übersprungen.")

    # ---------- Ordner ----------
    def ordner_waehlen(self):
        start = self.wurzel or (Path.home() / "Documents")
        pfad = QFileDialog.getExistingDirectory(self, "Ordner zum Aufräumen wählen", str(start))
        if pfad:
            self.ordner_setzen(pfad)

    def ordner_setzen(self, pfad) -> bool:
        fehler = af.ordner_pruefen(pfad, app_ordner=einstellungen.ORDNER)
        if fehler:
            QMessageBox.warning(self, "Aufräumen", fehler)
            return False
        neu = Path(os.path.realpath(pfad))
        if self.eintraege and neu != self.wurzel:
            if QMessageBox.question(self, "Aufräumen", "Den bisherigen Vorschlag verwerfen und einen anderen Ordner wählen?") != QMessageBox.Yes:
                return False
            self.eintraege = []; af.vorschlag_verwerfen(self.prot); self.tabelle_fuellen()
        self.wurzel = neu
        self.ordner_text.setText(_kurz(neu)); self.ordner_text.setToolTip(str(neu))
        self._meldung("Jetzt „Vorschlag erstellen“ — dabei wird noch nichts verändert.")
        self._knoepfe()
        return True

    # ---------- Vorschlag ----------
    def vorschlag_starten(self):
        if self.wurzel is None or self.lauf is not None:
            return
        engine = self.engine_holen()
        if not engine or not engine.bereit():
            self._meldung("Das Modell läuft nicht — im Reiter „Gerät“ auf „Starten“ klicken und warten, bis „bereit“ dasteht. "
                          "Bis dahin wird nichts gelesen und nichts verändert.", ROT)
            return
        if not self.wurzel.is_dir():
            self._meldung(f"Den Ordner „{_kurz(self.wurzel)}“ gibt es nicht mehr.", ROT); return
        if self.eintraege and QMessageBox.question(self, "Aufräumen", "Den bisherigen Vorschlag verwerfen und neu erstellen?") != QMessageBox.Yes:
            return
        self.eintraege = []; self.tabelle_fuellen()
        self.lauf = af.Vorschlagslauf(self.wurzel, lambda s, t: engine.json_fragen(s, t), unterordner=self.unterordner.isChecked(),
                                      max_dateien=self.max_dateien.value(), seiten=self.seiten.value(), inhalt=self.inhalt.isChecked(),
                                      stand=self.bote.stand.emit, eintrag=self.bote.eintrag.emit)
        self._knoepfe(); self._meldung("Startet …")
        lauf = self.lauf

        def arbeit():
            try:
                erg = lauf.laufen()
            except Exception as e:  # noqa: BLE001 — jede Störung als Text in die Oberfläche
                erg = {"eintraege": [], "abgebrochen": False, "zu_viele": False, "gesamt": 0, "fehler": str(e)}
            self.bote.fertig.emit(erg)
        threading.Thread(target=arbeit, daemon=True).start()

    def abbrechen(self):
        if self.lauf:
            self.lauf.abbrechen(); self._meldung("Wird nach der aktuellen Datei angehalten …")

    def _stand(self, i: int, n: int, text: str):
        self.balken.setRange(0, max(1, n)); self.balken.setValue(min(i, max(1, n)))
        if text == "fertig" or not n:
            if not n:
                self._meldung(text)
            return
        self._meldung(f"{i + 1} von {n}: {text}")

    def _eintrag(self, e: dict):
        self.eintraege.append(e)
        self._fuellen = True
        r = self.tabelle.rowCount(); self.tabelle.insertRow(r); self._zeile(r, len(self.eintraege) - 1)
        self._fuellen = False
        self.ordner_fuellen()
        if len(self.eintraege) % 10 == 0:
            self._speichern()

    def _fertig(self, erg: dict):
        self.lauf = None
        zahl = {k: sum(1 for e in self.eintraege if e.get("status") == k) for k in STATUS}
        teile = [f"{zahl['vorschlag']} Vorschläge"] + [f"{zahl[k]} {t}" for k, t in (("unklar", "unklar"), ("doppelt", "doppelt"),
                                                                                    ("bleibt", "liegen schon richtig"), ("fehler", "Fehler")) if zahl[k]]
        satz = ("Abgebrochen — " if erg.get("abgebrochen") else "Fertig — ") + ", ".join(teile) + "."
        if erg.get("zu_viele"):
            satz += f" Es gibt mehr Dateien, als „höchstens“ erlaubt — nur die ersten {self.max_dateien.value()} sind dabei."
        if not erg.get("gesamt") and not erg.get("fehler"):
            satz = "In diesem Ordner gibt es keine Dateien zum Aufräumen (versteckte Dateien, Verweise und Pakete werden ausgelassen)."
        if erg.get("fehler"):
            self._meldung(f"{satz} {erg['fehler']}", ROT)
        else:
            self._meldung(satz + " Jetzt prüfen, bei Bedarf Ordner oder Namen ändern, dann „Ausgewählte ausführen“.", GRUEN if self.eintraege else GRAU)
        self.balken.setValue(self.balken.maximum())
        self._speichern(); self._knoepfe()

    # ---------- Liste ----------
    def tabelle_fuellen(self):
        self._fuellen = True
        self.tabelle.setRowCount(0); self.tabelle.setRowCount(len(self.eintraege))
        for r in range(len(self.eintraege)):
            self._zeile(r, r)
        self._fuellen = False
        self.ordner_fuellen(); self._knoepfe()

    def _zeile(self, r: int, i: int):
        e = self.eintraege[i]
        endung = Path(e["pfad"]).suffix if Path(e["pfad"]).stem else ""
        ohne_ordner = e.get("status") in ("unklar", "fehler") and not e.get("ordner")

        v = QTableWidgetItem(); v.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | (Qt.NoItemFlags if ohne_ordner else Qt.ItemIsEnabled))
        v.setCheckState(Qt.Checked if e.get("verschieben") else Qt.Unchecked)
        datei = QTableWidgetItem(e["pfad"]); datei.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); datei.setData(Qt.UserRole, i)
        datum = datetime.fromtimestamp(e.get("geaendert") or 0).strftime("%d.%m.%Y")
        datei.setToolTip(f"{e['pfad']}\n{e.get('art', '')}, {af.groesse_text(e.get('groesse') or 0)}, geändert am {datum}"
                         + (f"\n\nGelesen:\n{e['text'][:300]}" if e.get("text") else ""))
        ordner = QTableWidgetItem(e.get("ordner") or ""); ordner.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        ordner.setToolTip((f"{ordner.text()}\n\n" if ordner.text() else "") + "Doppelklick zum Ändern. Leer = oberste Ebene des gewählten Ordners.")
        u = QTableWidgetItem(); u.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | (Qt.ItemIsEnabled if e.get("name") else Qt.NoItemFlags))
        u.setCheckState(Qt.Checked if e.get("umbenennen") and e.get("name") else Qt.Unchecked)
        name = QTableWidgetItem(f"{e['name']}{endung}" if e.get("name") else ""); name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        name.setToolTip((f"{name.text()}\n\n" if name.text() else "") + "Doppelklick zum Ändern. Die Endung bleibt immer gleich.")
        titel, farbe = STATUS.get(e.get("status"), (e.get("status", ""), None))
        hinweis = QTableWidgetItem(f"{titel} – {e['grund']}" if e.get("grund") else titel)
        hinweis.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); hinweis.setToolTip(hinweis.text())
        if farbe:
            hinweis.setForeground(QBrush(QColor(farbe)))
        if e.get("ordner_ungueltig"):
            ordner.setText(e["ordner_ungueltig"]); ordner.setBackground(QBrush(QColor("#f6d5cf"))); ordner.setToolTip(UNGUELTIG_ORDNER)
        if e.get("name_ungueltig"):
            name.setText(e["name_ungueltig"]); name.setBackground(QBrush(QColor("#f6d5cf"))); name.setToolTip(UNGUELTIG_NAME)
        for sp, item in ((SP_VERSCHIEBEN, v), (SP_DATEI, datei), (SP_ORDNER, ordner), (SP_UMBENENNEN, u), (SP_NAME, name), (SP_HINWEIS, hinweis)):
            self.tabelle.setItem(r, sp, item)

    def _index(self, r: int) -> int | None:
        it = self.tabelle.item(r, SP_DATEI)
        return it.data(Qt.UserRole) if it else None

    def _zelle_geaendert(self, item: QTableWidgetItem):
        if self._fuellen:
            return
        r, sp = item.row(), item.column()
        i = self._index(r)
        if i is None:
            return
        e = self.eintraege[i]
        if sp == SP_VERSCHIEBEN:
            e["verschieben"] = item.checkState() == Qt.Checked
        elif sp == SP_UMBENENNEN:
            e["umbenennen"] = item.checkState() == Qt.Checked
        elif sp == SP_ORDNER:
            o = af.ordner_normalisieren(item.text(), leer_erlaubt=True)
            if o is None:
                e["ordner_ungueltig"] = item.text(); e["verschieben"] = False
            else:
                e.pop("ordner_ungueltig", None)
                if o != e.get("ordner"):
                    e["ordner"] = o
                    if e.get("status") in ("unklar", "fehler") and o:
                        e["status"], e["grund"] = "hand", "Zielordner von dir"
                    e["verschieben"] = bool(o) or e.get("status") not in ("unklar", "fehler")
                    af.status_auffrischen(e)
        elif sp == SP_NAME:
            text = item.text().strip()
            endung = Path(e["pfad"]).suffix if Path(e["pfad"]).stem else ""
            n = af.name_normalisieren(text, endung) if text else ""
            if n is None:
                e["name_ungueltig"] = text; e["umbenennen"] = False
            else:
                e.pop("name_ungueltig", None)
                if n != e.get("name"):
                    e["name"] = n; e["umbenennen"] = bool(n)
        self._fuellen = True
        self._zeile(r, i)
        self._fuellen = False
        if sp == SP_ORDNER:
            self.ordner_fuellen()
        self._speichern(); self._knoepfe()

    def ordner_fuellen(self):
        self._fuellen = True
        liste = af.ordner_liste(self.eintraege)
        self.ordner_tab.setRowCount(len(liste))
        for r, (o, n) in enumerate(liste):
            a = QTableWidgetItem(o); a.setData(Qt.UserRole, o); a.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            b = QTableWidgetItem(str(n)); b.setFlags(Qt.ItemIsEnabled); b.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.ordner_tab.setItem(r, 0, a); self.ordner_tab.setItem(r, 1, b)
        self._fuellen = False

    def _ordner_geaendert(self, item: QTableWidgetItem):
        if self._fuellen or item.column() != 0:
            return
        alt = item.data(Qt.UserRole)
        neu = af.ordner_normalisieren(item.text())
        if neu is None:
            QMessageBox.warning(self, "Aufräumen", UNGUELTIG_ORDNER)
        elif neu != alt:
            af.ordner_umbenennen(self.eintraege, alt, neu)
            self._speichern()
        self.tabelle_fuellen()

    def alle(self, an: bool):
        for e in self.eintraege:
            if not an:
                e["verschieben"] = e["umbenennen"] = False
            elif e.get("status") in ("vorschlag", "doppelt", "hand") and not e.get("ordner_ungueltig") and e.get("ordner") != af.ordner_von(e["pfad"]):
                e["verschieben"] = True
        self.tabelle_fuellen(); self._speichern()

    # ---------- Ausführen und Rückgängig ----------
    def ausfuehren(self):
        if self.wurzel is None or self.lauf is not None:
            return
        n, ungueltig = 0, 0
        for e in self.eintraege:
            try:
                n += af.aktion(e) is not None
            except af.AufraeumFehler:
                ungueltig += 1
        if not n:
            QMessageBox.information(self, "Aufräumen", "Nichts ausgewählt — Häkchen bei „Verschieben“ bzw. „Umbenennen“ setzen."); return
        frage = (f"{n} Dateien in „{_kurz(self.wurzel)}“ verschieben bzw. umbenennen?\n\n"
                 "Es wird nichts gelöscht und nichts überschrieben — gibt es den Namen schon, kommt „ (2)“ dazu. Jede Aktion steht "
                 "im Protokoll; „Letzten Lauf rückgängig machen“ stellt alles wieder her.")
        if ungueltig:
            frage += f"\n\n{ungueltig} Einträge mit ungültigem Ordner oder Namen werden übersprungen."
        if QMessageBox.question(self, "Aufräumen", frage) != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            erg = af.ausfuehren(self.wurzel, self.eintraege, self.prot)
        except Exception as ex:  # noqa: BLE001 — z. B. Protokoll nicht schreibbar: dann wurde die betroffene Datei NICHT verschoben
            QApplication.restoreOverrideCursor()
            self.laeufe_zeigen()
            QMessageBox.warning(self, "Aufräumen", f"Angehalten: {ex}\n\nOhne Protokoll wird nichts verschoben. Bereits Erledigtes steht "
                                                   "im Protokoll und lässt sich rückgängig machen.")
            return
        QApplication.restoreOverrideCursor()
        erledigt = set(erg["erledigt"])
        self.eintraege = [e for i, e in enumerate(self.eintraege) if i not in erledigt]
        self.tabelle_fuellen(); self._speichern(); self.laeufe_zeigen()
        satz = f"{erg['anzahl']} Dateien erledigt ({erg['verschoben']} verschoben, {erg['umbenannt']} mit neuem Namen"
        satz += f", davon {erg['zusatz']} mit Zusatz „(2)“, weil der Name schon belegt war)." if erg["zusatz"] else ")."
        if erg["fehler"]:
            satz += f"\n\n{len(erg['fehler'])} übersprungen:\n" + "\n".join(f"• {t}" for _p, t in erg["fehler"][:12])
            if len(erg["fehler"]) > 12:
                satz += f"\n… und {len(erg['fehler']) - 12} weitere"
        self._meldung(satz.split("\n")[0], GRUEN if erg["anzahl"] else GRAU)
        QMessageBox.information(self, "Aufräumen", satz)

    def laeufe_zeigen(self):
        self.laeufe_liste.clear()
        for l in af.laeufe(self.prot)[:50]:
            wann = (l["beginn"] or "")[:16].replace("T", " ")
            stand = f"zurückgenommen {l['rueckgaengig'][:16].replace('T', ' ')}" if l["rueckgaengig"] else "kann rückgängig gemacht werden"
            self.laeufe_liste.addItem(f"{wann}  ·  {_kurz(l['wurzel'])}  ·  {l['anzahl']} Dateien  ·  {stand}")
        if not self.laeufe_liste.count():
            self.laeufe_liste.addItem("Noch kein Lauf ausgeführt.")
        self._knoepfe()

    def rueckgaengig(self):
        offen = [l for l in af.laeufe(self.prot) if not l["rueckgaengig"]]
        if not offen:
            return
        l = offen[0]
        wann = (l["beginn"] or "")[:16].replace("T", " ")
        if QMessageBox.question(self, "Rückgängig", f"Lauf vom {wann} in „{_kurz(l['wurzel'])}“ ({l['anzahl']} Dateien) rückgängig machen?\n\n"
                                "Die Dateien kommen an ihren alten Platz und unter ihren alten Namen zurück; dabei angelegte Ordner werden "
                                "entfernt, wenn sie leer sind. Es wird nichts gelöscht oder überschrieben.") != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            erg = af.rueckgaengig(self.prot, l["id"])
        except Exception as ex:  # noqa: BLE001
            QApplication.restoreOverrideCursor(); QMessageBox.warning(self, "Rückgängig", str(ex)); return
        QApplication.restoreOverrideCursor()
        self.laeufe_zeigen()
        satz = f"{erg['zurueck']} Dateien zurückgelegt, {erg['ordner_entfernt']} leere Ordner entfernt."
        if erg["ordner_geblieben"]:
            satz += "\n\nNicht leer, deshalb geblieben: " + ", ".join(erg["ordner_geblieben"][:10])
        if erg["probleme"]:
            satz += "\n\nHinweise:\n" + "\n".join(f"• {t}" for t in erg["probleme"][:12])
        self._meldung(satz.split("\n")[0], GRUEN)
        QMessageBox.information(self, "Rückgängig", satz)
