"""Reiter „Aufräumen“ der App (Peter 2026-11-22: „Könnte ich meiner KI auf dem Mac sagen: räum die Dokumente auf?“).

Startordner wählen (z. B. Dokumente) → „Was aufräumen?“ ankreuzen (z. B. „unaufgeräumt 1“; nichts angekreuzt = der ganze Ordner)
→ „Vorschlag erstellen“ (die KI liest jede Datei und schlägt Zielordner und Namen vor — es wird NICHTS verändert) → in der Liste
prüfen, suchen, filtern, ändern → „Ausgewählte ausführen“ (verschieben/umbenennen; nie löschen, nie überschreiben) → bei Bedarf
„Letzten Lauf rückgängig machen“. Die Regeln stehen in aufraeumen.py; hier nur Anzeige und Hintergrund-Thread.
"""
import os
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar, QPushButton, QSizePolicy,
                               QSpinBox, QSplitter, QStyle, QStyledItemDelegate, QStyleOptionButton, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import aufraeumen as af
from . import einstellungen

GRUEN = "#2e7d5b"
ROT = "#b3412f"
GELB = "#9a6b0f"
GRAU = "#666"
STATUS = {"vorschlag": ("Vorschlag", None), "unklar": ("unklar", ROT), "doppelt": ("doppelt", GELB),
          "bleibt": ("liegt schon richtig", GRAU), "fehler": ("Fehler", ROT), "hand": ("von dir", GRUEN)}
SP_VERSCHIEBEN, SP_DATEI, SP_ORDNER, SP_UMBENENNEN, SP_NAME, SP_HINWEIS = range(6)
KOPF = {SP_VERSCHIEBEN: "Verschieben", SP_DATEI: "Datei", SP_ORDNER: "Zielordner", SP_UMBENENNEN: "Umbenennen",
        SP_NAME: "Neuer Name", SP_HINWEIS: "Hinweis"}
FELD = {SP_VERSCHIEBEN: "verschieben", SP_UMBENENNEN: "umbenennen"}
AW_NAME, AW_AUFRAEUMEN, AW_KEIN_ZIEL, AW_DATEIEN = range(4)
LOSE = "\x00lose"                 # Kennung der Zeile „Lose Dateien direkt im Startordner“
PLATZHALTER = "\x00platzhalter"   # Unterordner werden erst beim Aufklappen gelesen
GEERBT = Qt.UserRole + 1          # Häkchen kommt vom Ordner darüber
ANDERES = Qt.UserRole + 2         # liegt auf einem anderen Laufwerk
UNGUELTIG_ORDNER = ("Ungültiger Ordnername: nicht mit „/“ oder „~“ beginnen, kein „..“, keine versteckten Ordner, keine Zeichen "
                    "\\ : * ? \" < > |, höchstens 4 Ebenen.")
UNGUELTIG_NAME = "Ungültiger Dateiname: kein „/“, nicht mit „.“ beginnen, keine Zeichen \\ : * ? \" < > |."
ZUSTAND = {"alle": Qt.Checked, "keine": Qt.Unchecked, "teils": Qt.PartiallyChecked, "leer": Qt.Unchecked}


class AufraeumBote(QObject):
    stand = Signal(int, int, str)
    eintrag = Signal(object)
    fertig = Signal(object)


class RechtsKuerzen(QStyledItemDelegate):
    """Hinweis-Spalte: vorne lesbar („unklar – …“), hinten gekürzt (die übrigen Spalten kürzen in der Mitte, damit die Endung bleibt)."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.textElideMode = Qt.ElideRight


class HaekchenKopf(QHeaderView):
    """Listenkopf mit echten Häkchen in den Spalten „Verschieben“ und „Umbenennen“ (alle / keine / teils) — wirkt auf die gerade
    sichtbaren Zeilen."""
    geklickt = Signal(int)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.zustaende: dict = {}
        self.aktiv: dict = {}
        self.setSectionsClickable(True)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def haekchen_rect(self, rect: QRect) -> QRect:
        g = self.style().pixelMetric(QStyle.PM_IndicatorWidth)
        return QRect(rect.x() + 5, rect.y() + (rect.height() - g) // 2, g, g)

    def paintSection(self, painter, rect, index):
        painter.save()
        super().paintSection(painter, rect, index)
        painter.restore()
        if index not in self.zustaende:
            return
        opt = QStyleOptionButton()
        opt.rect = self.haekchen_rect(rect)
        z = self.zustaende[index]
        opt.state = (QStyle.State_Enabled if self.aktiv.get(index, True) else QStyle.State_None) | (
            QStyle.State_On if z == Qt.Checked else QStyle.State_NoChange if z == Qt.PartiallyChecked else QStyle.State_Off)
        self.style().drawPrimitive(QStyle.PE_IndicatorCheckBox, opt, painter)

    def mousePressEvent(self, ev):
        i = self.logicalIndexAt(ev.position().toPoint())
        if i in self.zustaende and self.aktiv.get(i, True):
            self.geklickt.emit(i)
            return
        super().mousePressEvent(ev)


def _text(t: str, farbe: str = GRAU) -> QLabel:
    lab = QLabel(t); lab.setWordWrap(True); lab.setStyleSheet(f"color:{farbe}")
    return lab


def _kurz(pfad) -> str:
    p, h = str(pfad), str(Path.home())
    return "~" + p[len(h):] if p == h or p.startswith(h + os.sep) else p


class AufraeumFenster(QWidget):
    """engine_holen() → laufende Engine oder None. protokoll_ordner: Protokolle der Läufe, die Auswahl je Startordner und der
    zuletzt erstellte Vorschlag."""

    def __init__(self, engine_holen, protokoll_ordner: Path | None = None):
        super().__init__()
        self.engine_holen = engine_holen
        self.prot = Path(protokoll_ordner or einstellungen.ORDNER / "aufraeumen")
        self.wurzel: Path | None = None
        self.eintraege: list = []
        self.vorhanden: list = []
        self.frueher = {"quellen": [], "befuellt": []}
        self.vorschlag_auswahl = af.auswahl_ordnen({})    # womit der Vorschlag gemacht wurde (gilt fürs Ausführen)
        self.lauf: af.Vorschlagslauf | None = None
        self._fuellen = False
        self._baum_fuellen = False
        self.bote = AufraeumBote()
        self.bote.stand.connect(self._stand); self.bote.eintrag.connect(self._eintrag); self.bote.fertig.connect(self._fertig)

        lay = QVBoxLayout(self)
        lay.addWidget(_text("Die KI auf diesem Mac schlägt vor, wie Dateien sortiert und benannt werden. Verändert wird erst, wenn du "
                            "„Ausgewählte ausführen“ klickst — dabei wird <b>nie etwas gelöscht oder überschrieben</b>, und jeder Lauf lässt "
                            "sich rückgängig machen. Tipp: zuerst an einer <b>Kopie</b> ausprobieren."))

        z1 = QHBoxLayout()
        self.ordner_knopf = QPushButton("Startordner wählen …"); self.ordner_knopf.clicked.connect(self.ordner_waehlen)
        self.ordner_text = QLabel("Noch kein Ordner gewählt."); self.ordner_text.setStyleSheet(f"color:{GRAU}")
        self.ordner_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        z1.addWidget(self.ordner_knopf); z1.addWidget(self.ordner_text, 1); lay.addLayout(z1)

        # Was aufräumen? — je Ordner „Aufräumen“ (bekommt Vorschläge, nie Ziel) oder „Kein Ziel“ (bleibt liegen, die KI sieht ihn nicht)
        g0 = QGroupBox("Was aufräumen?"); v0 = QVBoxLayout(g0)
        self.auswahl_baum = QTreeWidget(); self.auswahl_baum.setColumnCount(4)
        self.auswahl_baum.setHeaderLabels(["Ordner", "Aufräumen", "Kein Ziel", "Dateien"])
        k = self.auswahl_baum.header(); k.setStretchLastSection(False)
        k.setSectionResizeMode(AW_NAME, QHeaderView.Stretch)
        for sp in (AW_AUFRAEUMEN, AW_KEIN_ZIEL, AW_DATEIEN):
            k.setSectionResizeMode(sp, QHeaderView.ResizeToContents)
        self.auswahl_baum.setMinimumHeight(70)
        self.auswahl_baum.itemChanged.connect(self._auswahl_geaendert)
        self.auswahl_baum.itemExpanded.connect(self._aufgeklappt)
        v0.addWidget(self.auswahl_baum)
        self.auswahl_hinweis = _text("")
        v0.addWidget(self.auswahl_hinweis)
        # „Was aufräumen?“ oben, Vorschlagsliste unten — die Trennlinie lässt sich ziehen
        unten = QWidget(); ul = QVBoxLayout(unten); ul.setContentsMargins(0, 0, 0, 0)
        self.hoch_teiler = QSplitter(Qt.Vertical); self.hoch_teiler.addWidget(g0); self.hoch_teiler.addWidget(unten)
        self.hoch_teiler.setChildrenCollapsible(False); self.hoch_teiler.setStretchFactor(0, 1); self.hoch_teiler.setStretchFactor(1, 3)
        self.hoch_teiler.setSizes([250, 450])
        lay.addWidget(self.hoch_teiler, 1)

        z2 = QHBoxLayout()
        self.unterordner = QCheckBox("Unterordner einbeziehen"); self.unterordner.setChecked(True)
        self.inhalt = QCheckBox("Inhalt lesen (Texterkennung)"); self.inhalt.setChecked(True)
        self.inhalt.setToolTip("Aus: nur nach Name, Typ und Datum einordnen — viel schneller, aber ungenauer.")
        self.seiten = QSpinBox(); self.seiten.setRange(1, 10); self.seiten.setValue(2)
        self.seiten.setToolTip("So viele Seiten liest die App je PDF (Textebene bzw. Texterkennung).")
        self.max_dateien = QSpinBox(); self.max_dateien.setRange(1, 5000); self.max_dateien.setValue(300); self.max_dateien.setSingleStep(50)
        self.max_dateien.setToolTip("Gilt nur für die Dateien, die aufgeräumt werden. Die KI braucht je Datei einige Sekunden.")
        z2.addWidget(self.unterordner); z2.addSpacing(12); z2.addWidget(self.inhalt); z2.addStretch()
        ul.addLayout(z2)
        z3 = QHBoxLayout()                                    # eigene Zeile: passt so auch in ein schmales Fenster
        z3.addWidget(QLabel("PDF-Seiten:")); z3.addWidget(self.seiten); z3.addSpacing(12)
        z3.addWidget(QLabel("höchstens")); z3.addWidget(self.max_dateien); z3.addWidget(QLabel("Dateien aufräumen")); z3.addStretch()
        ul.addLayout(z3)

        z4 = QHBoxLayout()
        self.start_knopf = QPushButton("Vorschlag erstellen"); self.start_knopf.clicked.connect(self.vorschlag_starten)
        self.abbruch_knopf = QPushButton("Abbrechen"); self.abbruch_knopf.clicked.connect(self.abbrechen)
        self.balken = QProgressBar(); self.balken.setRange(0, 1); self.balken.setValue(0)
        z4.addWidget(self.start_knopf); z4.addWidget(self.abbruch_knopf); z4.addWidget(self.balken, 1); ul.addLayout(z4)
        self.stand_text = _text(""); ul.addWidget(self.stand_text)

        # Suche + Schnellfilter über der Liste
        zf = QHBoxLayout()
        self.suche = QLineEdit(); self.suche.setPlaceholderText("Suchen: Dateiname, Ordner, neuer Name, Hinweis …")
        self.suche.setClearButtonEnabled(True); self.suche.textChanged.connect(self._filter_geaendert)
        zf.addWidget(self.suche, 1)
        self.filter_gruppe = QButtonGroup(self); self.filter_gruppe.setExclusive(True)
        self.filter_knoepfe: dict = {}
        for schluessel, titel in af.FILTER.items():
            b = QPushButton(titel); b.setCheckable(True); b.setProperty("filter", schluessel)
            self.filter_gruppe.addButton(b); self.filter_knoepfe[schluessel] = b; zf.addWidget(b)
        self.filter_knoepfe["alle"].setChecked(True)
        self.filter_gruppe.buttonClicked.connect(lambda _b: self._filter_geaendert())
        ul.addLayout(zf)

        self.tabelle = QTableWidget(0, 6)
        self.kopf = HaekchenKopf(self.tabelle); self.tabelle.setHorizontalHeader(self.kopf)
        self.kopf.geklickt.connect(self.kopf_geklickt)
        self.tabelle.setHorizontalHeaderLabels([("      " + KOPF[i]) if i in FELD else KOPF[i] for i in range(6)])
        self.kopf.zustaende = {SP_VERSCHIEBEN: Qt.Unchecked, SP_UMBENENNEN: Qt.Unchecked}
        self.tabelle.verticalHeader().setVisible(False)
        self.tabelle.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabelle.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
        for sp in (SP_VERSCHIEBEN, SP_UMBENENNEN):
            self.kopf.setSectionResizeMode(sp, QHeaderView.ResizeToContents)
        for sp in (SP_DATEI, SP_ORDNER, SP_NAME, SP_HINWEIS):
            self.kopf.setSectionResizeMode(sp, QHeaderView.Stretch)
        self.tabelle.setTextElideMode(Qt.ElideMiddle); self.tabelle.setWordWrap(False)
        self._kuerzen = RechtsKuerzen(self.tabelle); self.tabelle.setItemDelegateForColumn(SP_HINWEIS, self._kuerzen)
        self.tabelle.setMinimumHeight(110)
        self.kopf.setToolTip("Häkchen im Listenkopf: setzt bzw. entfernt das Häkchen in allen gerade sichtbaren Zeilen "
                             "(nach Suche und Filter).")
        self.tabelle.itemChanged.connect(self._zelle_geaendert)
        self.ordner_tab = QTableWidget(0, 3)
        self.ordner_tab.setHorizontalHeaderLabels(["Zielordner", "Dateien", ""])
        self.ordner_tab.verticalHeader().setVisible(False)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.ordner_tab.setToolTip("Doppelklick auf einen Ordner: umbenennen — gilt für alle Dateien, die dorthin sollen. "
                                   "„neu“ = wird beim Ausführen angelegt.")
        self.ordner_tab.itemChanged.connect(self._ordner_geaendert)
        rechts = QWidget(); rv = QVBoxLayout(rechts); rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.ordner_tab, 1); rv.addWidget(_text("Doppelklick = umbenennen (für alle Dateien darin). „neu“ = wird angelegt."))
        teiler = QSplitter(Qt.Horizontal); teiler.addWidget(self.tabelle); teiler.addWidget(rechts)
        teiler.setStretchFactor(0, 4); teiler.setStretchFactor(1, 1); teiler.setChildrenCollapsible(False)
        rechts.setMinimumWidth(170); teiler.setSizes([600, 200])
        self.ordner_tab.setWordWrap(False)
        ul.addWidget(teiler, 1)

        z5 = QHBoxLayout()
        z5.addWidget(_text("Häkchen im Listenkopf gelten für die sichtbaren Zeilen."), 1)
        self.ausfuehren_knopf = QPushButton("Ausgewählte ausführen"); self.ausfuehren_knopf.clicked.connect(self.ausfuehren)
        z5.addWidget(self.ausfuehren_knopf)
        ul.addLayout(z5)

        g = QGroupBox("Frühere Läufe"); gv = QVBoxLayout(g)
        self.laeufe_liste = QListWidget(); self.laeufe_liste.setMaximumHeight(52); gv.addWidget(self.laeufe_liste)
        z6 = QHBoxLayout()
        self.zurueck_knopf = QPushButton("Letzten Lauf rückgängig machen"); self.zurueck_knopf.clicked.connect(self.rueckgaengig)
        z6.addWidget(_text(f"Protokolle: {_kurz(self.prot)}"), 1); z6.addWidget(self.zurueck_knopf); gv.addLayout(z6)
        g.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay.addWidget(g)

        self._vorschlag_laden()
        self.laeufe_zeigen()
        self._knoepfe()

    # ---------- Zustand ----------
    def _knoepfe(self):
        laeuft = self.lauf is not None
        for w in (self.ordner_knopf, self.unterordner, self.inhalt, self.seiten, self.max_dateien, self.auswahl_baum):
            w.setEnabled(not laeuft)
        self.start_knopf.setEnabled(not laeuft and self.wurzel is not None)
        self.abbruch_knopf.setEnabled(laeuft)
        self.ausfuehren_knopf.setEnabled(not laeuft and any(e.get("verschieben") or (e.get("umbenennen") and e.get("name")) for e in self.eintraege))
        self.zurueck_knopf.setEnabled(not laeuft and any(not l["rueckgaengig"] for l in af.laeufe(self.prot)))

    def _meldung(self, text: str, farbe: str = GRAU):
        self.stand_text.setText(text); self.stand_text.setStyleSheet(f"color:{farbe}")

    def _filter(self) -> str:
        b = self.filter_gruppe.checkedButton()
        return b.property("filter") if b else "alle"

    def _speichern(self):
        if self.wurzel is not None:
            try:
                af.vorschlag_speichern(self.prot, self.wurzel, self.eintraege,
                                       {"auswahl": self.vorschlag_auswahl, "suche": self.suche.text(), "filter": self._filter()})
            except OSError:
                pass

    def _vorschlag_laden(self):
        v = af.vorschlag_laden(self.prot)
        if not v or not v.get("eintraege"):
            return
        einst = v.get("einstellung") or {}
        self._startordner_uebernehmen(Path(v["wurzel"]))
        self.eintraege = v["eintraege"]
        self.vorschlag_auswahl = af.auswahl_ordnen(einst.get("auswahl"))      # Vorschlag aus 0.1.20: keine → ganzer Ordner
        self._baum_fuellen = True
        self.suche.setText(einst.get("suche") or "")
        self.filter_knoepfe.get(einst.get("filter") or "alle", self.filter_knoepfe["alle"]).setChecked(True)
        self._baum_fuellen = False
        self.tabelle_fuellen()
        datum = (v.get("datum") or "")[:16].replace("T", " ")
        self._meldung(f"Vorschlag vom {datum} geladen ({len(self.eintraege)} Dateien). Vor dem Ausführen kurz prüfen — "
                      "seitdem geänderte oder verschwundene Dateien werden beim Ausführen übersprungen.")

    # ---------- Startordner ----------
    def ordner_waehlen(self):
        start = self.wurzel or (Path.home() / "Documents")
        pfad = QFileDialog.getExistingDirectory(self, "Startordner wählen (z. B. Dokumente)", str(start))
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
        self._startordner_uebernehmen(neu)
        self._meldung("Jetzt ankreuzen, was aufgeräumt wird (oder nichts für den ganzen Ordner), dann „Vorschlag erstellen“ — "
                      "dabei wird noch nichts verändert.")
        self._knoepfe()
        return True

    def _startordner_uebernehmen(self, neu: Path):
        self.wurzel = neu
        self.ordner_text.setText(_kurz(neu)); self.ordner_text.setToolTip(str(neu))
        self.frueher = af.fruehere_laeufe(self.prot, neu)
        self.vorhanden = af.vorhandene_ordner(neu)
        self.auswahl_aufbauen()

    # ---------- Was aufräumen? ----------
    def _zeile_auswahl(self, o: dict) -> QTreeWidgetItem:
        it = QTreeWidgetItem()
        zusatz = []
        if o.get("frueher_befuellt"):
            zusatz.append("aus früheren Läufen")
        if o.get("frueher_quelle"):
            zusatz.append("früher aufgeräumt")
        if o.get("anderes_laufwerk"):
            zusatz.append("anderes Laufwerk — ausgelassen")
        it.setText(AW_NAME, o["name"] + (f"  ({', '.join(zusatz)})" if zusatz else ""))
        it.setData(AW_NAME, Qt.UserRole, o["pfad"])
        it.setToolTip(AW_NAME, o["pfad"])
        it.setText(AW_DATEIEN, "–" if o.get("anderes_laufwerk") else f"{o['dateien']}{'+' if o.get('mehr') else ''}")
        it.setTextAlignment(AW_DATEIEN, Qt.AlignRight | Qt.AlignVCenter)
        if o.get("anderes_laufwerk"):
            it.setFlags(Qt.NoItemFlags); it.setData(AW_NAME, ANDERES, True)
            it.setToolTip(AW_NAME, f"{o['pfad']} liegt auf einem anderen Laufwerk — wird nie angefasst und ist kein Ziel.")
            return it
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        it.setCheckState(AW_AUFRAEUMEN, Qt.Unchecked); it.setCheckState(AW_KEIN_ZIEL, Qt.Unchecked)
        if o.get("hat_unterordner"):
            ph = QTreeWidgetItem([""]); ph.setData(AW_NAME, Qt.UserRole, PLATZHALTER); it.addChild(ph)
        return it

    def auswahl_aufbauen(self):
        """Liste „Was aufräumen?“ für den Startordner; vorbelegt mit der gemerkten Auswahl dieses Ordners."""
        self._baum_fuellen = True
        self.auswahl_baum.clear()
        if self.wurzel is None:
            self._baum_fuellen = False
            return
        lose = QTreeWidgetItem([f"Lose Dateien direkt in „{self.wurzel.name}“", "", "", str(af.lose_dateien_zaehlen(self.wurzel))])
        lose.setData(AW_NAME, Qt.UserRole, LOSE); lose.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        lose.setCheckState(AW_AUFRAEUMEN, Qt.Unchecked); lose.setTextAlignment(AW_DATEIEN, Qt.AlignRight | Qt.AlignVCenter)
        self.auswahl_baum.addTopLevelItem(lose)
        for o in af.ordner_zur_auswahl(self.wurzel, "", self.frueher):
            self.auswahl_baum.addTopLevelItem(self._zeile_auswahl(o))
        gemerkt = af.auswahl_laden(self.prot, self.wurzel)
        lose.setCheckState(AW_AUFRAEUMEN, Qt.Checked if gemerkt["lose"] else Qt.Unchecked)
        for pfad in gemerkt["ordner"] + gemerkt["auslassen"]:
            it = self._finden(pfad, laden=True)
            if it is not None and it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(AW_AUFRAEUMEN if pfad in gemerkt["ordner"] else AW_KEIN_ZIEL, Qt.Checked)
        self._abhaengige_setzen()
        self._baum_fuellen = False
        self._auswahl_hinweis()

    def _finden(self, pfad: str, laden: bool = False):
        teile = pfad.split("/")
        kinder = [self.auswahl_baum.topLevelItem(i) for i in range(self.auswahl_baum.topLevelItemCount())]
        it = None
        for k in range(len(teile)):
            ziel = "/".join(teile[:k + 1])
            it = next((c for c in kinder if c.data(AW_NAME, Qt.UserRole) == ziel), None)
            if it is None:
                return None
            if k < len(teile) - 1:
                if laden:
                    self._kinder_laden(it); it.setExpanded(True)
                kinder = [it.child(i) for i in range(it.childCount())]
        return it

    def _kinder_laden(self, it: QTreeWidgetItem):
        if it.childCount() == 1 and it.child(0).data(AW_NAME, Qt.UserRole) == PLATZHALTER:
            vorher = self._baum_fuellen
            self._baum_fuellen = True
            it.takeChild(0)
            for o in af.ordner_zur_auswahl(self.wurzel, it.data(AW_NAME, Qt.UserRole), self.frueher):
                it.addChild(self._zeile_auswahl(o))
            self._abhaengige_setzen()
            self._baum_fuellen = vorher

    def _aufgeklappt(self, it: QTreeWidgetItem):
        if self.wurzel is not None:
            self._kinder_laden(it)

    def _alle_items(self):
        stapel = [self.auswahl_baum.topLevelItem(i) for i in range(self.auswahl_baum.topLevelItemCount())]
        while stapel:
            it = stapel.pop(0)
            yield it
            stapel[0:0] = [it.child(i) for i in range(it.childCount())]

    def _abhaengige_setzen(self):
        """„Aufräumen“ schließt „Kein Ziel“ ein; unter einem gewählten Ordner gilt dasselbe für alle Unterordner (grau, nicht
        änderbar). Wird der Ordner darüber wieder abgewählt, sind die Unterordner wieder frei (und nicht angekreuzt)."""
        def setzen(it, erbe_auf, erbe_kein):
            p = it.data(AW_NAME, Qt.UserRole)
            if p in (PLATZHALTER, LOSE) or it.data(AW_NAME, ANDERES):
                return
            if erbe_auf or erbe_kein:
                it.setCheckState(AW_AUFRAEUMEN, Qt.Checked if erbe_auf else Qt.Unchecked)
                it.setCheckState(AW_KEIN_ZIEL, Qt.Checked)
                it.setFlags(Qt.ItemIsUserCheckable)                         # sichtbar, aber nicht änderbar
                it.setData(AW_NAME, GEERBT, True)
            else:
                if it.data(AW_NAME, GEERBT):
                    it.setCheckState(AW_AUFRAEUMEN, Qt.Unchecked); it.setCheckState(AW_KEIN_ZIEL, Qt.Unchecked)
                    it.setData(AW_NAME, GEERBT, False)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                if it.checkState(AW_AUFRAEUMEN) == Qt.Checked:
                    it.setCheckState(AW_KEIN_ZIEL, Qt.Checked)
            auf = it.checkState(AW_AUFRAEUMEN) == Qt.Checked
            kein = it.checkState(AW_KEIN_ZIEL) == Qt.Checked
            for i in range(it.childCount()):
                setzen(it.child(i), auf, kein)
        for i in range(self.auswahl_baum.topLevelItemCount()):
            setzen(self.auswahl_baum.topLevelItem(i), False, False)

    def auswahl(self) -> dict:
        """Aktuelle Auswahl aus der Liste: {lose, ordner, auslassen} (nur die obersten angekreuzten Ordner)."""
        a = {"lose": False, "ordner": [], "auslassen": []}

        def lesen(it):
            p = it.data(AW_NAME, Qt.UserRole)
            if p == PLATZHALTER:
                return
            if p == LOSE:
                a["lose"] = it.checkState(AW_AUFRAEUMEN) == Qt.Checked
                return
            if not (it.flags() & Qt.ItemIsEnabled):
                return
            if it.checkState(AW_AUFRAEUMEN) == Qt.Checked:
                a["ordner"].append(p); return
            if it.checkState(AW_KEIN_ZIEL) == Qt.Checked:
                a["auslassen"].append(p); return
            for i in range(it.childCount()):
                lesen(it.child(i))
        for i in range(self.auswahl_baum.topLevelItemCount()):
            lesen(self.auswahl_baum.topLevelItem(i))
        return af.auswahl_ordnen(a)

    def auswahl_setzen(self, pfad: str, aufraeumen: bool | None = None, kein_ziel: bool | None = None):
        """Für Tests und Skripte: einen Ordner (oder LOSE) ankreuzen bzw. abwählen."""
        it = self._finden(pfad, laden=True) if pfad != LOSE else self.auswahl_baum.topLevelItem(0)
        if it is None:
            raise KeyError(pfad)
        if aufraeumen is not None:
            it.setCheckState(AW_AUFRAEUMEN, Qt.Checked if aufraeumen else Qt.Unchecked)
        if kein_ziel is not None:
            it.setCheckState(AW_KEIN_ZIEL, Qt.Checked if kein_ziel else Qt.Unchecked)

    def _auswahl_geaendert(self, it: QTreeWidgetItem, spalte: int):
        if self._baum_fuellen or self.wurzel is None:
            return
        self._baum_fuellen = True
        if spalte == AW_KEIN_ZIEL and it.checkState(AW_KEIN_ZIEL) == Qt.Unchecked:
            it.setCheckState(AW_AUFRAEUMEN, Qt.Unchecked)                  # „Kein Ziel“ ab → auch nicht aufräumen
        if spalte == AW_AUFRAEUMEN and it.checkState(AW_AUFRAEUMEN) == Qt.Unchecked:
            it.setCheckState(AW_KEIN_ZIEL, Qt.Unchecked)                   # „Aufräumen“ ab → wieder normale Ablage
        self._abhaengige_setzen()
        self._baum_fuellen = False
        try:
            af.auswahl_speichern(self.prot, self.wurzel, self.auswahl())
        except OSError:
            pass
        self._auswahl_hinweis()

    def _auswahl_hinweis(self):
        a = self.auswahl()
        if af.ganzer_ordner(a):
            t = ("Nichts angekreuzt = der ganze Ordner wird aufgeräumt. Mit „Aufräumen“ nur diese Ordner einsortieren — der Rest "
                 "ist deine Ablage und bleibt unangetastet.")
        else:
            teile = (["lose Dateien"] if a["lose"] else []) + [f"„{o}“" for o in a["ordner"]]
            t = f"Aufgeräumt: {', '.join(teile)} (nie Ziel). Einsortiert wird in die übrigen Ordner — sie werden nie angefasst."
            if a["auslassen"]:
                t += f" Kein Ziel (bleibt liegen, die KI sieht ihn nicht): {', '.join(a['auslassen'])}."
        self.auswahl_hinweis.setText(t)

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
        self.vorschlag_auswahl = self.auswahl()
        self.frueher = af.fruehere_laeufe(self.prot, self.wurzel)
        self.lauf = af.Vorschlagslauf(self.wurzel, lambda s, t: engine.json_fragen(s, t), auswahl=self.vorschlag_auswahl,
                                      frueher=self.frueher, unterordner=self.unterordner.isChecked(),
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
        self.ordner_fuellen(); self.filter_anwenden()
        if len(self.eintraege) % 10 == 0:
            self._speichern()

    def _fertig(self, erg: dict):
        self.lauf = None
        if erg.get("vorhanden") is not None:
            self.vorhanden = erg["vorhanden"]
        zahl = {k: sum(1 for e in self.eintraege if e.get("status") == k) for k in STATUS}
        teile = [f"{zahl['vorschlag']} Vorschläge"] + [f"{zahl[k]} {t}" for k, t in (("unklar", "unklar"), ("doppelt", "doppelt"),
                                                                                    ("bleibt", "liegen schon richtig"), ("fehler", "Fehler")) if zahl[k]]
        satz = ("Abgebrochen — " if erg.get("abgebrochen") else "Fertig — ") + ", ".join(teile) + "."
        if erg.get("zu_viele"):
            if af.ganzer_ordner(self.vorschlag_auswahl):
                satz += f" Es gibt mehr Dateien, als „höchstens“ erlaubt — nur die ersten {self.max_dateien.value()} sind dabei."
            else:
                satz += " Weitere Dateien übrig — nach dem Ausführen einfach noch einmal „Vorschlag erstellen“."
        if erg.get("meldungen"):
            satz += " " + " · ".join(erg["meldungen"][:3]) + "."
        if not erg.get("gesamt") and not erg.get("fehler"):
            satz = "Hier gibt es keine Dateien zum Aufräumen (versteckte Dateien, Verweise und Pakete werden ausgelassen)."
        if erg.get("fehler"):
            self._meldung(f"{satz} {erg['fehler']}", ROT)
        else:
            self._meldung(satz + " Jetzt prüfen, bei Bedarf Ordner oder Namen ändern, dann „Ausgewählte ausführen“.", GRUEN if self.eintraege else GRAU)
        self.balken.setValue(self.balken.maximum())
        self.ordner_fuellen(); self.filter_anwenden()
        self._speichern(); self._knoepfe()

    # ---------- Liste ----------
    def tabelle_fuellen(self):
        self._fuellen = True
        self.tabelle.setRowCount(0); self.tabelle.setRowCount(len(self.eintraege))
        for r in range(len(self.eintraege)):
            self._zeile(r, r)
        self._fuellen = False
        self.ordner_fuellen(); self.filter_anwenden(); self._knoepfe()

    def _zeile(self, r: int, i: int):
        e = self.eintraege[i]
        endung = Path(e["pfad"]).suffix if Path(e["pfad"]).stem else ""
        v = QTableWidgetItem()
        v.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | (Qt.ItemIsEnabled if af.kann_setzen(e, "verschieben") else Qt.NoItemFlags))
        v.setCheckState(Qt.Checked if e.get("verschieben") else Qt.Unchecked)
        datei = QTableWidgetItem(e["pfad"]); datei.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); datei.setData(Qt.UserRole, i)
        datum = datetime.fromtimestamp(e.get("geaendert") or 0).strftime("%d.%m.%Y")
        datei.setToolTip(f"{e['pfad']}\n{e.get('art', '')}, {af.groesse_text(e.get('groesse') or 0)}, geändert am {datum}"
                         + (f"\nGleiche Datei: {e['gleich_wie']}" if e.get("gleich_wie") else "")
                         + (f"\n\nGelesen:\n{e['text'][:300]}" if e.get("text") else ""))
        ordner = QTableWidgetItem(e.get("ordner") or ""); ordner.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        ordner.setToolTip((f"{ordner.text()}\n\n" if ordner.text() else "") + "Doppelklick zum Ändern. Leer = oberste Ebene des Startordners.")
        u = QTableWidgetItem()
        u.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | (Qt.ItemIsEnabled if af.kann_setzen(e, "umbenennen") else Qt.NoItemFlags))
        u.setCheckState(Qt.Checked if e.get("umbenennen") and e.get("name") else Qt.Unchecked)
        name = QTableWidgetItem(f"{e['name']}{endung}" if e.get("name") else ""); name.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        name.setToolTip((f"{name.text()}\n\n" if name.text() else "") + "Doppelklick zum Ändern. Die Endung bleibt immer gleich.")
        titel, farbe = STATUS.get(e.get("status"), (e.get("status", ""), None))
        hinweis = QTableWidgetItem(f"{titel} – {e['grund']}" if e.get("grund") else titel)
        hinweis.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); hinweis.setToolTip(hinweis.text())
        if farbe:
            hinweis.setForeground(QBrush(QColor(farbe)))
        if e.get("ordner_ungueltig"):
            ordner.setText(e["ordner_ungueltig"]); ordner.setBackground(QBrush(QColor("#f6d5cf")))
            ordner.setToolTip(e.get("ordner_grund") or UNGUELTIG_ORDNER)
        if e.get("name_ungueltig"):
            name.setText(e["name_ungueltig"]); name.setBackground(QBrush(QColor("#f6d5cf"))); name.setToolTip(UNGUELTIG_NAME)
        for sp, item in ((SP_VERSCHIEBEN, v), (SP_DATEI, datei), (SP_ORDNER, ordner), (SP_UMBENENNEN, u), (SP_NAME, name), (SP_HINWEIS, hinweis)):
            self.tabelle.setItem(r, sp, item)

    def _index(self, r: int) -> int | None:
        it = self.tabelle.item(r, SP_DATEI)
        return it.data(Qt.UserRole) if it else None

    def _gesperrt(self) -> list:
        return self.vorschlag_auswahl["ordner"] + self.vorschlag_auswahl["auslassen"]

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
            sperre = af.ziel_gesperrt(o, self._gesperrt()) if o else None
            if o is None or sperre:
                e["ordner_ungueltig"] = item.text(); e["ordner_grund"] = sperre or UNGUELTIG_ORDNER; e["verschieben"] = False
            else:
                e.pop("ordner_ungueltig", None); e.pop("ordner_grund", None)
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
        self.filter_anwenden(); self._speichern(); self._knoepfe()

    # ---------- Suche, Filter, Kopf-Häkchen ----------
    def sichtbare_indizes(self) -> list[int]:
        return af.sichtbare(self.eintraege, self.suche.text(), self._filter(), self.vorhanden)

    def filter_anwenden(self, *_):
        sicht = set(self.sichtbare_indizes())
        for r in range(self.tabelle.rowCount()):
            self.tabelle.setRowHidden(r, self._index(r) not in sicht)
        zahlen = af.filter_zaehlen(self.eintraege, self.suche.text(), self.vorhanden)
        for k, b in self.filter_knoepfe.items():
            b.setText(f"{af.FILTER[k]} ({zahlen[k]})")
        self.kopf_aktualisieren()

    def _filter_geaendert(self, *_):
        self.filter_anwenden()
        if not self._baum_fuellen and self.lauf is None and self.eintraege:
            self._speichern()                       # Suche und Filter gehören zum gespeicherten Vorschlag

    def kopf_aktualisieren(self):
        sicht = self.sichtbare_indizes()
        for sp, feld in FELD.items():
            z = af.kopf_zustand(self.eintraege, sicht, feld)
            self.kopf.zustaende[sp] = ZUSTAND[z]
            self.kopf.aktiv[sp] = z != "leer"
        self.kopf.viewport().update()

    def kopf_geklickt(self, sp: int):
        if sp not in FELD:
            return
        sicht = self.sichtbare_indizes()
        z = af.kopf_zustand(self.eintraege, sicht, FELD[sp])
        if z == "leer":
            return
        af.alle_setzen(self.eintraege, sicht, FELD[sp], z != "alle")       # alle an → alle aus, sonst alle an
        self._fuellen = True
        for r in range(self.tabelle.rowCount()):
            i = self._index(r)
            if i in sicht:
                self._zeile(r, i)
        self._fuellen = False
        self.kopf_aktualisieren(); self._speichern(); self._knoepfe()

    # ---------- Ordnerliste rechts ----------
    def ordner_fuellen(self):
        self._fuellen = True
        liste = af.ordner_liste(self.eintraege, self.vorhanden)
        self.ordner_tab.setRowCount(len(liste))
        for r, (o, n, neu) in enumerate(liste):
            a = QTableWidgetItem(o); a.setData(Qt.UserRole, o); a.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            b = QTableWidgetItem(str(n)); b.setFlags(Qt.ItemIsEnabled); b.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            c = QTableWidgetItem("neu" if neu else ""); c.setFlags(Qt.ItemIsEnabled)
            if neu:
                c.setForeground(QBrush(QColor(GRUEN))); c.setToolTip("Gibt es noch nicht — wird beim Ausführen angelegt.")
            self.ordner_tab.setItem(r, 0, a); self.ordner_tab.setItem(r, 1, b); self.ordner_tab.setItem(r, 2, c)
        self._fuellen = False

    def _ordner_geaendert(self, item: QTableWidgetItem):
        if self._fuellen or item.column() != 0:
            return
        alt = item.data(Qt.UserRole)
        neu = af.ordner_normalisieren(item.text())
        sperre = af.ziel_gesperrt(neu, self._gesperrt()) if neu else None
        if neu is None or sperre:
            QMessageBox.warning(self, "Aufräumen", sperre or UNGUELTIG_ORDNER)
        elif neu != alt:
            af.ordner_umbenennen(self.eintraege, alt, neu)
            self._speichern()
        self.tabelle_fuellen()

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
            erg = af.ausfuehren(self.wurzel, self.eintraege, self.prot, auswahl=self.vorschlag_auswahl)
        except Exception as ex:  # noqa: BLE001 — z. B. Protokoll nicht schreibbar: dann wurde die betroffene Datei NICHT verschoben
            QApplication.restoreOverrideCursor()
            self.laeufe_zeigen()
            QMessageBox.warning(self, "Aufräumen", f"Angehalten: {ex}\n\nOhne Protokoll wird nichts verschoben. Bereits Erledigtes steht "
                                                   "im Protokoll und lässt sich rückgängig machen.")
            return
        QApplication.restoreOverrideCursor()
        erledigt = set(erg["erledigt"])
        self.eintraege = [e for i, e in enumerate(self.eintraege) if i not in erledigt]
        self.vorhanden = af.vorhandene_ordner(self.wurzel)
        self.frueher = af.fruehere_laeufe(self.prot, self.wurzel)
        self.auswahl_aufbauen()
        self.tabelle_fuellen(); self._speichern(); self.laeufe_zeigen()
        satz = f"{erg['anzahl']} Dateien erledigt ({erg['verschoben']} verschoben, {erg['umbenannt']} mit neuem Namen"
        satz += f", davon {erg['zusatz']} mit Zusatz „(2)“, weil der Name schon belegt war)." if erg["zusatz"] else ")."
        if erg.get("leere_ordner"):
            satz += ("\n\nDiese Ordner sind jetzt leer und bleiben stehen (es wird nie gelöscht) — du kannst sie selbst löschen:\n"
                     + "\n".join(f"• {o}" for o in erg["leere_ordner"][:12]))
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
            was = ", ".join((["lose Dateien"] if l.get("lose") else []) + list(l.get("quellen") or []))
            self.laeufe_liste.addItem(f"{wann}  ·  {_kurz(l['wurzel'])}{f' ({was})' if was else ''}  ·  {l['anzahl']} Dateien  ·  {stand}")
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
        if self.wurzel is not None:
            self.vorhanden = af.vorhandene_ordner(self.wurzel)
            self.frueher = af.fruehere_laeufe(self.prot, self.wurzel)
            self.auswahl_aufbauen(); self.ordner_fuellen(); self.filter_anwenden()
        self.laeufe_zeigen()
        satz = f"{erg['zurueck']} Dateien zurückgelegt, {erg['ordner_entfernt']} leere Ordner entfernt."
        if erg["ordner_geblieben"]:
            satz += "\n\nNicht leer, deshalb geblieben: " + ", ".join(erg["ordner_geblieben"][:10])
        if erg["probleme"]:
            satz += "\n\nHinweise:\n" + "\n".join(f"• {t}" for t in erg["probleme"][:12])
        self._meldung(satz.split("\n")[0], GRUEN)
        QMessageBox.information(self, "Rückgängig", satz)
