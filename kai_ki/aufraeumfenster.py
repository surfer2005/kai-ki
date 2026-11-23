"""Reiter „Aufräumen“ der App (Peter 2026-11-22: „Könnte ich meiner KI auf dem Mac sagen: räum die Dokumente auf?“).

Zwei Quellen mit derselben Bedienung:
- „Ordner auf dem Mac“: Startordner wählen (z. B. Dokumente) → „Was aufräumen?“ ankreuzen (z. B. „unaufgeräumt 1“; nichts angekreuzt
  = der ganze Ordner) → „Vorschlag erstellen“ (die KI liest jede Datei und schlägt Zielordner und Namen vor — es wird NICHTS verändert)
  → in der Liste prüfen, suchen, filtern, ändern → „Ausgewählte ausführen“ (verschieben/umbenennen; nie löschen, nie überschreiben)
  → bei Bedarf „Letzten Lauf rückgängig machen“. Regeln in aufraeumen.py.
- „Postfach“ (ab 0.1.22, Peter 2026-11-23): E-Mail-Konto (iCloud, web.de, Outlook.com, anderer IMAP-Server) → Ordner im Konto →
  „Vorschlag erstellen“ (Mails nur lesen, nichts wird als gelesen markiert) → dieselbe Liste → „Ausgewählte ausführen“ verschiebt im
  Konto (nie löschen) → Rückgängig. Regeln in postfach.py, Zugangsdaten nur im Schlüsselbund (schluesselbund.py).
Hier nur Anzeige und Hintergrund-Threads.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QProgressBar, QPushButton, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyle,
                               QStyledItemDelegate, QStyleOptionButton, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import aufraeumen as af
from . import einstellungen, microsoft
from . import postfach as pf
from . import schluesselbund as sbund

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
ORDNER, POSTFACH = "ordner", "postfach"


class AufraeumBote(QObject):
    stand = Signal(int, int, str)
    eintrag = Signal(object)
    fertig = Signal(object)
    erledigt = Signal(object)          # Funktion, die nach einer Hintergrundarbeit im Hauptthread läuft


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


class KontoDialog(QDialog):
    """Postfach verbinden: Anbieter, Adresse, Passwort (iCloud: app-spezifisch) bzw. Microsoft-Anmeldung im Browser. „Prüfen und
    speichern“ meldet sich einmal an und liest die Ordnerliste — erst dann landet das Konto in der Liste, das Geheimnis im
    Schlüsselbund."""

    def __init__(self, fenster: "AufraeumFenster", konto: dict | None = None):
        super().__init__(fenster)
        self.fenster, self.konto_alt, self.ergebnis = fenster, konto, None
        self._abbruch = threading.Event()
        self.bote = AufraeumBote(); self.bote.erledigt.connect(lambda f: f())
        self.setWindowTitle("Postfach verbinden" if konto is None else "Postfach ändern")
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        self.form = QFormLayout(); lay.addLayout(self.form)
        self.anbieter = QComboBox()
        for k, a in pf.ANBIETER.items():
            self.anbieter.addItem(a["name"], k)
        self.adresse = QLineEdit(); self.adresse.setPlaceholderText("name@icloud.com")
        self.benutzer = QLineEdit(); self.benutzer.setPlaceholderText("(wie die Adresse)")
        self.passwort = QLineEdit(); self.passwort.setEchoMode(QLineEdit.Password)
        self.host = QLineEdit(); self.host.setPlaceholderText("imap.beispiel.de")
        self.port = QSpinBox(); self.port.setRange(1, 65535); self.port.setValue(993)
        self.sicherheit = QComboBox(); self.sicherheit.addItem("SSL/TLS (meist Port 993)", "ssl"); self.sicherheit.addItem("STARTTLS (meist 143)", "starttls")
        self.client_id = QLineEdit(); self.client_id.setPlaceholderText("z. B. 1a2b3c4d-… (siehe README)")
        self.form.addRow("Anbieter:", self.anbieter)
        self.form.addRow("E-Mail-Adresse:", self.adresse)
        self.form.addRow("Benutzername:", self.benutzer)
        self.passwort_titel = QLabel("Passwort:")
        self.form.addRow(self.passwort_titel, self.passwort)
        self.form.addRow("IMAP-Server:", self.host)
        self.form.addRow("Port:", self.port)
        self.form.addRow("Verschlüsselung:", self.sicherheit)
        self.form.addRow("Client-ID (Microsoft):", self.client_id)
        self.hinweis = QLabel(); self.hinweis.setWordWrap(True); self.hinweis.setTextFormat(Qt.RichText)
        self.hinweis.setOpenExternalLinks(True); self.hinweis.setStyleSheet(f"color:{GRAU}")
        lay.addWidget(self.hinweis)
        self.status = _text(""); lay.addWidget(self.status)
        z = QHBoxLayout(); z.addStretch()
        self.abbruch_knopf = QPushButton("Abbrechen"); self.abbruch_knopf.clicked.connect(self.reject)
        self.ok_knopf = QPushButton("Prüfen und speichern"); self.ok_knopf.setDefault(True); self.ok_knopf.clicked.connect(self.pruefen)
        z.addWidget(self.abbruch_knopf); z.addWidget(self.ok_knopf); lay.addLayout(z)
        self.anbieter.currentIndexChanged.connect(self._anbieter_geaendert)
        if konto:
            self.anbieter.setCurrentIndex(max(0, self.anbieter.findData(konto.get("anbieter"))))
            self.adresse.setText(konto.get("adresse") or "")
            if konto.get("benutzer") and konto.get("benutzer") != konto.get("adresse"):
                self.benutzer.setText(konto["benutzer"])
            self.host.setText(konto.get("host") or ""); self.port.setValue(int(konto.get("port") or 993))
            self.sicherheit.setCurrentIndex(max(0, self.sicherheit.findData(konto.get("sicherheit"))))
            self.client_id.setText(konto.get("client_id") or "")
            self.passwort.setPlaceholderText("leer lassen = gespeichertes Passwort behalten")
        self._anbieter_geaendert()

    def _anbieter_geaendert(self, *_):
        k = self.anbieter.currentData()
        a = pf.ANBIETER[k]
        oauth, anders = a["anmeldung"] == "oauth", k == "anders"
        for feld, sichtbar in ((self.benutzer, anders), (self.passwort, not oauth), (self.host, anders), (self.port, anders),
                               (self.sicherheit, anders), (self.client_id, oauth)):
            self.form.setRowVisible(feld, sichtbar)
        self.passwort_titel.setText(f"{a.get('passwort_titel', 'Passwort')}:")
        self.adresse.setPlaceholderText({"icloud": "name@icloud.com", "webde": "name@web.de", "outlook": "name@outlook.de"}.get(k, "name@beispiel.de"))
        self.hinweis.setText(a["hinweis"])
        self.ok_knopf.setText("Bei Microsoft anmelden und speichern" if oauth else "Prüfen und speichern")

    def konto_daten(self) -> dict:
        d = {"anbieter": self.anbieter.currentData(), "adresse": self.adresse.text(), "benutzer": self.benutzer.text(),
             "host": self.host.text(), "port": self.port.value(), "sicherheit": self.sicherheit.currentData(),
             "client_id": self.client_id.text()}
        if self.konto_alt:
            d["id"] = self.konto_alt["id"]
        return d

    def _status(self, text, farbe=GRAU):
        self.status.setText(text); self.status.setStyleSheet(f"color:{farbe}")

    def pruefen(self):
        try:
            konto = pf.konto_ordnen(self.konto_daten())
        except pf.PostfachFehler as ex:
            self._status(str(ex), ROT); return
        oauth = konto["anmeldung"] == "oauth"
        pw = self.passwort.text()
        behalten = bool(self.konto_alt) and not oauth and not pw and self.konto_alt.get("anbieter") == konto["anbieter"]
        if not oauth and not pw and not behalten:
            self._status("Bitte das Passwort eintragen.", ROT); return
        f = self.fenster
        self._abbruch.clear()
        self.ok_knopf.setEnabled(False)
        self._status("Browser geöffnet — bitte bei Microsoft anmelden und zustimmen. Danach geht es hier von selbst weiter …" if oauth
                     else "Verbinde und melde an …")

        def arbeit():
            token = None
            if oauth:
                token = f.ms_anmelden(konto["client_id"], konto["adresse"], abbruch=self._abbruch)
                if not token.get("refresh_token"):
                    raise pf.PostfachFehler("Microsoft hat keinen Erneuerungsschlüssel geschickt (Berechtigung „offline_access“ fehlt?).")
                p = pf.verbinden(konto, f.sb, oeffnen=f.imap_oeffnen, zugang=token["access_token"])
            else:
                p = pf.verbinden(konto, f.sb, oeffnen=f.imap_oeffnen, zugang=pw or None)
            try:
                n = len([o for o in p.ordner() if o["waehlbar"]])
            finally:
                p.abmelden()
            return konto, (token["refresh_token"] if oauth else pw), n, token

        def lauf():
            try:
                erg, fehler = arbeit(), None
            except Exception as ex:  # noqa: BLE001
                erg, fehler = None, ex
            self.bote.erledigt.emit(lambda: self._fertig(erg, fehler))
        threading.Thread(target=lauf, daemon=True).start()

    def _fertig(self, erg, fehler):
        self.ok_knopf.setEnabled(True)
        if fehler is not None:
            self._status(sbund.bereinigen(fehler, self.passwort.text()), ROT); return
        konto, geheim, n, token = erg
        try:
            if geheim:
                pf.konto_hinzufuegen(self.fenster.pf_prot, konto, self.fenster.sb, geheim)
            else:
                pf.konten_speichern(self.fenster.pf_prot, [x for x in pf.konten_laden(self.fenster.pf_prot) if x["id"] != konto["id"]] + [konto])
        except (pf.PostfachFehler, sbund.SchluesselbundFehler, OSError) as ex:
            self._status(f"Speichern ging nicht: {ex}", ROT); return
        if token:
            pf._TOKENS[konto["id"]] = {"access_token": token["access_token"], "laeuft_ab": token["laeuft_ab"]}  # noqa: SLF001
        self.passwort.clear()
        self.ergebnis = {**konto, "ordner_anzahl": n}
        self.accept()

    def reject(self):
        self._abbruch.set()
        super().reject()


class AufraeumFenster(QWidget):
    """engine_holen() → laufende Engine oder None. protokoll_ordner: Protokolle der Läufe, die Auswahl je Startordner und der
    zuletzt erstellte Vorschlag (Postfach: Unterordner „postfach“ mit Konten ohne Geheimnisse, Vorschlag und Läufen).
    Für Tests: schluesselbund, imap_oeffnen(konto) → imaplib-Objekt, ms_anmelden(client_id, adresse, abbruch=…), ms_post."""

    def __init__(self, engine_holen, protokoll_ordner: Path | None = None, schluesselbund=None, imap_oeffnen=None, ms_anmelden=None,
                 ms_post=None):
        super().__init__()
        self.engine_holen = engine_holen
        self.prot = Path(protokoll_ordner or einstellungen.ORDNER / "aufraeumen")
        self.pf_prot = self.prot / "postfach"
        self.sb = schluesselbund or sbund.standard()
        self.imap_oeffnen, self.ms_post = imap_oeffnen, ms_post
        self.ms_anmelden = ms_anmelden or microsoft.anmelden
        self.wurzel: Path | None = None
        self.eintraege: list = []
        self.vorhanden: list = []
        self.frueher = {"quellen": [], "befuellt": []}
        self.vorschlag_auswahl = af.auswahl_ordnen({})    # womit der Vorschlag gemacht wurde (gilt fürs Ausführen)
        self.lauf = None                                  # Vorschlagslauf (Dateien oder Mails)
        self.arbeit: str | None = None                    # andere Hintergrundarbeit (Ordner laden, Mails verschieben …)
        self.quelle = ORDNER
        self._je_quelle: dict = {}
        self.konten = pf.konten_laden(self.pf_prot)
        self.pf_ordner: list = []
        self.pf_meta: dict = {}                           # womit der Mail-Vorschlag gemacht wurde
        self.pf_vorhanden: list = []
        self.pf_archiv: Path | None = None
        self._fuellen = False
        self._baum_fuellen = False
        self.bote = AufraeumBote()
        self.bote.stand.connect(self._stand); self.bote.eintrag.connect(self._eintrag); self.bote.fertig.connect(self._fertig)
        self.bote.erledigt.connect(lambda f: f())

        lay = QVBoxLayout(self)
        lay.addWidget(_text("Die KI auf diesem Mac schlägt vor, wie Dateien oder E-Mails sortiert werden. Verändert wird erst, wenn du "
                            "„Ausgewählte ausführen“ klickst — dabei wird <b>nie etwas gelöscht oder überschrieben</b>, und jeder Lauf lässt "
                            "sich rückgängig machen. Tipp: zuerst an einer <b>Kopie</b> bzw. einem Testordner ausprobieren."))
        zq = QHBoxLayout(); zq.addWidget(QLabel("Quelle:"))
        self.quelle_gruppe = QButtonGroup(self); self.quelle_gruppe.setExclusive(True)
        self.quelle_knoepfe: dict = {}
        for k, t in ((ORDNER, "Ordner auf dem Mac"), (POSTFACH, "Postfach")):
            b = QPushButton(t); b.setCheckable(True); b.setProperty("quelle", k)
            self.quelle_gruppe.addButton(b); self.quelle_knoepfe[k] = b; zq.addWidget(b)
        self.quelle_knoepfe[ORDNER].setChecked(True)
        self.quelle_gruppe.buttonClicked.connect(lambda b: self.quelle_setzen(b.property("quelle")))
        zq.addStretch(); lay.addLayout(zq)

        self.ordner_zeile = QWidget(); z1 = QHBoxLayout(self.ordner_zeile); z1.setContentsMargins(0, 0, 0, 0)
        self.ordner_knopf = QPushButton("Startordner wählen …"); self.ordner_knopf.clicked.connect(self.ordner_waehlen)
        self.ordner_text = QLabel("Noch kein Ordner gewählt."); self.ordner_text.setStyleSheet(f"color:{GRAU}")
        self.ordner_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        z1.addWidget(self.ordner_knopf); z1.addWidget(self.ordner_text, 1); lay.addWidget(self.ordner_zeile)

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
        self.oben_stapel = QStackedWidget(); self.oben_stapel.addWidget(g0); self.oben_stapel.addWidget(self._postfach_box())
        self._seite_zeigen(0)
        # „Was aufräumen?“ bzw. Postfach oben, Vorschlagsliste unten — die Trennlinie lässt sich ziehen
        unten = QWidget(); ul = QVBoxLayout(unten); ul.setContentsMargins(0, 0, 0, 0)
        self.hoch_teiler = QSplitter(Qt.Vertical); self.hoch_teiler.addWidget(self.oben_stapel); self.hoch_teiler.addWidget(unten)
        self.hoch_teiler.setChildrenCollapsible(False); self.hoch_teiler.setStretchFactor(0, 1); self.hoch_teiler.setStretchFactor(1, 3)
        self.hoch_teiler.setSizes([250, 450])
        lay.addWidget(self.hoch_teiler, 1)

        self.datei_optionen = QWidget(); dv = QVBoxLayout(self.datei_optionen); dv.setContentsMargins(0, 0, 0, 0)
        z2 = QHBoxLayout()
        self.unterordner = QCheckBox("Unterordner einbeziehen"); self.unterordner.setChecked(True)
        self.inhalt = QCheckBox("Inhalt lesen (Texterkennung)"); self.inhalt.setChecked(True)
        self.inhalt.setToolTip("Aus: nur nach Name, Typ und Datum einordnen — viel schneller, aber ungenauer.")
        self.seiten = QSpinBox(); self.seiten.setRange(1, 10); self.seiten.setValue(2)
        self.seiten.setToolTip("So viele Seiten liest die App je PDF (Textebene bzw. Texterkennung).")
        self.max_dateien = QSpinBox(); self.max_dateien.setRange(1, 5000); self.max_dateien.setValue(300); self.max_dateien.setSingleStep(50)
        self.max_dateien.setToolTip("Gilt nur für die Dateien, die aufgeräumt werden. Die KI braucht je Datei einige Sekunden.")
        z2.addWidget(self.unterordner); z2.addSpacing(12); z2.addWidget(self.inhalt); z2.addStretch()
        dv.addLayout(z2)
        z3 = QHBoxLayout()                                    # eigene Zeile: passt so auch in ein schmales Fenster
        z3.addWidget(QLabel("PDF-Seiten:")); z3.addWidget(self.seiten); z3.addSpacing(12)
        z3.addWidget(QLabel("höchstens")); z3.addWidget(self.max_dateien); z3.addWidget(QLabel("Dateien aufräumen")); z3.addStretch()
        dv.addLayout(z3)
        ul.addWidget(self.datei_optionen)

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
        self._kopf_beschriften()
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
        self.ordner_tab.setHorizontalHeaderLabels(["Zielordner", "Anzahl", ""])
        self.ordner_tab.verticalHeader().setVisible(False)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ordner_tab.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.ordner_tab.setToolTip("Doppelklick auf einen Ordner: umbenennen — gilt für alle Einträge, die dorthin sollen. "
                                   "„neu“ = wird beim Ausführen angelegt.")
        self.ordner_tab.itemChanged.connect(self._ordner_geaendert)
        rechts = QWidget(); rv = QVBoxLayout(rechts); rv.setContentsMargins(0, 0, 0, 0)
        rv.addWidget(self.ordner_tab, 1); rv.addWidget(_text("Doppelklick = umbenennen (für alle Einträge darin). „neu“ = wird angelegt."))
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
        self.prot_text = _text(f"Protokolle: {_kurz(self.prot)}")
        z6.addWidget(self.prot_text, 1); z6.addWidget(self.zurueck_knopf); gv.addLayout(z6)
        g.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        lay.addWidget(g)

        self._aufgebaut = True
        self._vorschlag_laden()
        self._postfach_vorschlag_laden()
        self.laeufe_zeigen()
        self._knoepfe()
        if self._pf_einstellung().get("quelle") == POSTFACH:
            self.quelle_setzen(POSTFACH, laden=False)            # beim App-Start nichts übers Netz — erst auf Knopfdruck

    # ---------- Postfach-Bereich ----------
    def _postfach_box(self) -> QGroupBox:
        g = QGroupBox("Postfach"); v = QVBoxLayout(g)
        z = QHBoxLayout(); z.addWidget(QLabel("Konto:"))
        self.konto_wahl = QComboBox(); self.konto_wahl.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.konto_wahl.setMinimumContentsLength(24)
        self.konto_wahl.currentIndexChanged.connect(self._konto_gewechselt)
        self.konto_neu_knopf = QPushButton("Konto hinzufügen …"); self.konto_neu_knopf.clicked.connect(lambda: self.konto_dialog())
        self.konto_aendern_knopf = QPushButton("Ändern …"); self.konto_aendern_knopf.clicked.connect(lambda: self.konto_dialog(self._konto()))
        self.konto_aendern_knopf.setToolTip("Passwort erneuern bzw. bei Microsoft neu anmelden, Client-ID ändern …")
        self.konto_weg_knopf = QPushButton("Entfernen"); self.konto_weg_knopf.clicked.connect(self.konto_entfernen)
        z.addWidget(self.konto_wahl, 1); z.addWidget(self.konto_neu_knopf); z.addWidget(self.konto_aendern_knopf); z.addWidget(self.konto_weg_knopf)
        v.addLayout(z)
        z = QHBoxLayout(); z.addWidget(QLabel("Ordner im Konto:"))
        self.pf_ordner_wahl = QComboBox(); self.pf_ordner_wahl.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.pf_ordner_wahl.setMinimumContentsLength(20)
        self.pf_ordner_wahl.currentIndexChanged.connect(lambda _i: self._knoepfe())
        self.pf_ordner_knopf = QPushButton("Ordner neu laden"); self.pf_ordner_knopf.clicked.connect(self.ordner_laden)
        z.addWidget(self.pf_ordner_wahl, 1); z.addWidget(self.pf_ordner_knopf); v.addLayout(z)
        z = QHBoxLayout()
        self.pf_max = QSpinBox(); self.pf_max.setRange(1, 5000); self.pf_max.setValue(300); self.pf_max.setSingleStep(50)
        self.pf_max.setToolTip("Die KI braucht je Mail einige Sekunden.")
        self.pf_reihenfolge = QComboBox(); self.pf_reihenfolge.addItem("neueste zuerst", True); self.pf_reihenfolge.addItem("älteste zuerst", False)
        self.pf_tage = QSpinBox(); self.pf_tage.setRange(0, 36500); self.pf_tage.setValue(0); self.pf_tage.setSpecialValueText("alle")
        self.pf_tage.setToolTip("Nur Mails der letzten … Tage (0 = alle).")
        z.addWidget(QLabel("höchstens")); z.addWidget(self.pf_max); z.addWidget(QLabel("Mails,")); z.addWidget(self.pf_reihenfolge)
        z.addSpacing(10); z.addWidget(QLabel("aus den letzten")); z.addWidget(self.pf_tage); z.addWidget(QLabel("Tagen")); z.addStretch()
        v.addLayout(z)
        z = QHBoxLayout()
        self.pf_ungelesen = QCheckBox("Ungelesene nicht anfassen"); self.pf_ungelesen.setChecked(True)
        self.pf_ungelesen.setToolTip("Ungelesene Mails bekommen keinen Vorschlag und bleiben, wo sie sind.")
        self.pf_archiv_haken = QCheckBox("zusätzlich als .eml auf dem Mac ablegen:")
        self.pf_archiv_haken.setToolTip("Vor dem Verschieben wird jede Mail als Datei (.eml) in den gewählten Ordner kopiert — "
                                        "immer ein neuer Dateiname, nie überschrieben.")
        self.pf_archiv_knopf = QPushButton("Ordner wählen …"); self.pf_archiv_knopf.clicked.connect(self.archiv_waehlen)
        self.pf_archiv_text = QLabel("—"); self.pf_archiv_text.setStyleSheet(f"color:{GRAU}")
        self.pf_archiv_text.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        z.addWidget(self.pf_ungelesen); z.addSpacing(10); z.addWidget(self.pf_archiv_haken); z.addWidget(self.pf_archiv_knopf)
        z.addWidget(self.pf_archiv_text, 1); v.addLayout(z)
        self.pf_hinweis = _text("Gelesen wird nur (keine Mail wird dabei als gelesen markiert). Verschoben wird erst nach „Ausgewählte "
                                "ausführen“ — nie gelöscht, nie in Papierkorb, Spam, Gesendet oder Entwürfe. Zugangsdaten liegen nur im "
                                "Schlüsselbund.")
        v.addWidget(self.pf_hinweis); v.addStretch()
        e = self._pf_einstellung()
        self.pf_max.setValue(int(e.get("max") or 300)); self.pf_tage.setValue(int(e.get("tage") or 0))
        self.pf_reihenfolge.setCurrentIndex(0 if e.get("neueste", True) else 1)
        self.pf_ungelesen.setChecked(bool(e.get("ungelesen", True)))
        if e.get("archiv") and Path(e["archiv"]).is_dir():
            self.pf_archiv = Path(e["archiv"]); self.pf_archiv_text.setText(_kurz(self.pf_archiv))
        self.pf_archiv_haken.setChecked(bool(e.get("archiv_an")) and self.pf_archiv is not None)
        self._konten_fuellen(e.get("konto_id"))
        return g

    def _pf_einstellung(self) -> dict:
        try:
            e = json.loads((self.pf_prot / "einstellung.json").read_text("utf-8"))
            return e if isinstance(e, dict) else {}
        except (OSError, ValueError):
            return {}

    def _pf_einstellung_merken(self):
        k = self._konto()
        try:
            af._schreiben(self.pf_prot / "einstellung.json", {  # noqa: SLF001
                "quelle": self.quelle, "konto_id": k["id"] if k else None, "ordner": self.pf_ordner_wahl.currentData(),
                "max": self.pf_max.value(), "tage": self.pf_tage.value(), "neueste": bool(self.pf_reihenfolge.currentData()),
                "ungelesen": self.pf_ungelesen.isChecked(), "archiv": str(self.pf_archiv) if self.pf_archiv else None,
                "archiv_an": self.pf_archiv_haken.isChecked()})
        except OSError:
            pass

    def _konten_fuellen(self, waehle: str | None = None):
        self.konten = pf.konten_laden(self.pf_prot)
        self.konto_wahl.blockSignals(True)
        self.konto_wahl.clear()
        for k in self.konten:
            self.konto_wahl.addItem(k.get("name") or k["adresse"], k["id"])
        if not self.konten:
            self.konto_wahl.addItem("(noch kein Konto — „Konto hinzufügen …“)", None)
        i = self.konto_wahl.findData(waehle) if waehle else -1
        self.konto_wahl.setCurrentIndex(i if i >= 0 else 0)
        self.konto_wahl.blockSignals(False)
        self.pf_ordner = []; self.pf_ordner_wahl.clear()
        self._knoepfe()

    def _konto(self, konto_id: str | None = None) -> dict | None:
        kid = konto_id or (self.konto_wahl.currentData() if hasattr(self, "konto_wahl") else None)
        return next((k for k in self.konten if k["id"] == kid), None)

    def _verbinder(self, konto: dict):
        return lambda: pf.verbinden(konto, self.sb, oeffnen=self.imap_oeffnen, post=self.ms_post)

    def _konto_gewechselt(self, *_):
        self.pf_ordner = []; self.pf_ordner_wahl.clear()
        self._knoepfe()
        if self._konto() and self.quelle == POSTFACH:
            self.ordner_laden()

    def konto_dialog(self, konto: dict | None = None):
        d = KontoDialog(self, konto)
        if d.exec() == QDialog.Accepted and d.ergebnis:
            self._konto_hinzugefuegt(d.ergebnis)

    def _konto_hinzugefuegt(self, konto: dict):
        self._konten_fuellen(konto["id"])
        self._meldung(f"Konto „{konto['adresse']}“ verbunden ({konto.get('ordner_anzahl', '?')} Ordner). Jetzt den Ordner wählen und "
                      "„Vorschlag erstellen“.", GRUEN)
        self._pf_einstellung_merken()
        self.ordner_laden()

    def konto_entfernen(self):
        k = self._konto()
        if not k:
            return
        if QMessageBox.question(self, "Postfach", f"Konto „{k['adresse']}“ aus der App entfernen?\n\nDas Passwort bzw. die Microsoft-"
                                "Anmeldung wird aus dem Schlüsselbund gelöscht. Im Postfach selbst ändert sich nichts; frühere Läufe "
                                "bleiben im Protokoll (Rückgängig geht erst wieder, wenn das Konto neu hinzugefügt wird).") != QMessageBox.Yes:
            return
        try:
            pf.konto_entfernen(self.pf_prot, k["id"], self.sb)
        except (sbund.SchluesselbundFehler, OSError) as ex:
            QMessageBox.warning(self, "Postfach", str(ex)); return
        self._konten_fuellen()

    def ordner_laden(self):
        konto = self._konto()
        if not konto or self.arbeit or self.lauf is not None:
            return
        vorher = self.pf_ordner_wahl.currentData() or self._pf_einstellung().get("ordner")
        verbinden = self._verbinder(konto)

        def arbeit():
            p = verbinden()
            try:
                return p.ordner()
            finally:
                p.abmelden()

        def fertig(erg, fehler):
            if fehler is not None:
                self._meldung(f"Ordner laden ging nicht: {fehler}", ROT); return
            self.pf_ordner = erg
            self.pf_ordner_wahl.blockSignals(True)
            self.pf_ordner_wahl.clear()
            for o in erg:
                if not o["waehlbar"]:
                    continue
                t = o["anzeige"] or o["name"]
                if o["sperre_art"] == "sonder":
                    t += "  (Sonderordner)"
                self.pf_ordner_wahl.addItem(t, o["roh"])
            i = self.pf_ordner_wahl.findData(vorher) if vorher else -1
            if i < 0:
                i = next((n for n in range(self.pf_ordner_wahl.count()) if str(self.pf_ordner_wahl.itemData(n)).upper() == "INBOX"), 0)
            self.pf_ordner_wahl.setCurrentIndex(i)
            self.pf_ordner_wahl.blockSignals(False)
            self._meldung(f"{self.pf_ordner_wahl.count()} Ordner geladen. Ordner wählen, dann „Vorschlag erstellen“ — dabei wird noch "
                          "nichts verändert.")
        self._im_hintergrund("Ordner des Kontos werden geladen …", arbeit, fertig)

    def archiv_waehlen(self):
        start = self.pf_archiv or (Path.home() / "Documents")
        pfad = QFileDialog.getExistingDirectory(self, "Ordner für die .eml-Kopien wählen", str(start))
        if pfad:
            self.archiv_setzen(pfad)

    def archiv_setzen(self, pfad) -> bool:
        fehler = af.ordner_pruefen(pfad, app_ordner=einstellungen.ORDNER)
        if fehler:
            QMessageBox.warning(self, "Postfach", fehler); return False
        self.pf_archiv = Path(os.path.realpath(pfad)); self.pf_archiv_text.setText(_kurz(self.pf_archiv))
        self.pf_archiv_haken.setChecked(True); self._pf_einstellung_merken()
        return True

    def _im_hintergrund(self, text: str, arbeit, fertig):
        """arbeit() im Hintergrund, danach fertig(ergebnis, fehler) im Hauptthread."""
        self.arbeit = text; self._knoepfe(); self._meldung(text)

        def lauf():
            try:
                erg, fehler = arbeit(), None
            except Exception as ex:  # noqa: BLE001 — jede Störung als Text in die Oberfläche
                erg, fehler = None, ex
            self.bote.erledigt.emit(lambda: self._hintergrund_fertig(fertig, erg, fehler))
        threading.Thread(target=lauf, daemon=True).start()

    def _hintergrund_fertig(self, fertig, erg, fehler):
        self.arbeit = None
        try:
            fertig(erg, fehler)
        finally:
            self._knoepfe()

    # ---------- Quelle ----------
    def quelle_setzen(self, quelle: str, laden: bool = True):
        if quelle == self.quelle:
            self.quelle_knoepfe[quelle].setChecked(True); return
        if self.lauf is not None or self.arbeit:
            self.quelle_knoepfe[self.quelle].setChecked(True); return
        self._speichern()
        self._je_quelle[self.quelle] = (self.eintraege, self.suche.text(), self._filter())
        self.quelle = quelle
        self.quelle_knoepfe[quelle].setChecked(True)
        eintraege, suche, filt = self._je_quelle.get(quelle, ([], "", "alle"))
        self.eintraege = eintraege
        mail = quelle == POSTFACH
        self.ordner_zeile.setVisible(not mail); self.datei_optionen.setVisible(not mail)
        self._seite_zeigen(1 if mail else 0)
        self.tabelle.setColumnHidden(SP_UMBENENNEN, mail); self.tabelle.setColumnHidden(SP_NAME, mail)
        self._kopf_beschriften()
        self.suche.setPlaceholderText("Suchen: Betreff, Absender, Ordner, Hinweis …" if mail else "Suchen: Dateiname, Ordner, neuer Name, Hinweis …")
        self.prot_text.setText(f"Protokolle: {_kurz(self.pf_prot if mail else self.prot)}")
        self._baum_fuellen = True
        self.suche.setText(suche)
        self.filter_knoepfe.get(filt, self.filter_knoepfe["alle"]).setChecked(True)
        self._baum_fuellen = False
        self.tabelle_fuellen(); self.laeufe_zeigen()
        self._meldung("")
        if mail and not self.pf_ordner and self._konto():
            if laden:
                self.ordner_laden()
            else:
                self._gemerkter_ordner()
        self._pf_einstellung_merken()

    def _seite_zeigen(self, i: int):
        """Oben „Was aufräumen?“ (0) oder Postfach (1). Die unsichtbare Seite zählt bei der Größe nicht mit (Ignored)."""
        for k in range(self.oben_stapel.count()):
            pol = QSizePolicy.Preferred if k == i else QSizePolicy.Ignored
            self.oben_stapel.widget(k).setSizePolicy(pol, pol)
        self.oben_stapel.setCurrentIndex(i)
        self.oben_stapel.updateGeometry()

    def _gemerkter_ordner(self):
        """Ohne Serverabfrage: den zuletzt gewählten Ordner anbieten (die ganze Liste kommt mit „Ordner neu laden“)."""
        roh = self._pf_einstellung().get("ordner")
        if roh and self.pf_ordner_wahl.count() == 0:
            anzeige = self.pf_meta.get("quelle_anzeige") if self.pf_meta.get("quelle") == roh else None
            self.pf_ordner_wahl.addItem(anzeige or pf.utf7_dekodieren(roh), roh)
        self._knoepfe()

    def _kopf_beschriften(self):
        kopf = {**KOPF, SP_DATEI: "Mail" if self.quelle == POSTFACH else "Datei"}
        self.tabelle.setHorizontalHeaderLabels([("      " + kopf[i]) if i in FELD else kopf[i] for i in range(6)])

    def _prot_aktuell(self) -> Path:
        return self.pf_prot if self.quelle == POSTFACH else self.prot

    def _vh(self) -> list:
        return self.pf_vorhanden if self.quelle == POSTFACH else self.vorhanden

    # ---------- Zustand ----------
    def _knoepfe(self):
        if not getattr(self, "_aufgebaut", False):          # beim Aufbau des Fensters gibt es noch nicht alle Knöpfe
            return
        laeuft = self.lauf is not None or bool(self.arbeit)
        mail = self.quelle == POSTFACH
        for w in (self.ordner_knopf, self.unterordner, self.inhalt, self.seiten, self.max_dateien, self.auswahl_baum,
                  self.konto_wahl, self.konto_neu_knopf, self.pf_ordner_wahl, self.pf_ordner_knopf, self.pf_max, self.pf_reihenfolge,
                  self.pf_tage, self.pf_ungelesen, self.pf_archiv_haken, self.pf_archiv_knopf, *self.quelle_knoepfe.values()):
            w.setEnabled(not laeuft)
        for w in (self.konto_aendern_knopf, self.konto_weg_knopf):
            w.setEnabled(not laeuft and self._konto() is not None)
        self.pf_ordner_knopf.setEnabled(not laeuft and self._konto() is not None)
        self.tabelle.setEnabled(not self.arbeit); self.ordner_tab.setEnabled(not self.arbeit)
        if mail:
            self.start_knopf.setEnabled(not laeuft and self._konto() is not None and bool(self.pf_ordner_wahl.currentData()))
        else:
            self.start_knopf.setEnabled(not laeuft and self.wurzel is not None)
        self.abbruch_knopf.setEnabled(self.lauf is not None)
        self.ausfuehren_knopf.setEnabled(not laeuft and any(e.get("verschieben") or (e.get("umbenennen") and e.get("name")) for e in self.eintraege))
        self.zurueck_knopf.setEnabled(not laeuft and any(not l["rueckgaengig"] for l in af.laeufe(self._prot_aktuell())))

    def _meldung(self, text: str, farbe: str = GRAU):
        self.stand_text.setText(text); self.stand_text.setStyleSheet(f"color:{farbe}")

    def _filter(self) -> str:
        b = self.filter_gruppe.checkedButton()
        return b.property("filter") if b else "alle"

    def _speichern(self):
        einstellung = {"suche": self.suche.text(), "filter": self._filter()}
        try:
            if self.quelle == POSTFACH:
                if self.pf_meta.get("konto_id"):
                    pf.vorschlag_speichern(self.pf_prot, {**self.pf_meta, "vorhanden": self.pf_vorhanden}, self.eintraege, einstellung)
            elif self.wurzel is not None:
                af.vorschlag_speichern(self.prot, self.wurzel, self.eintraege, {"auswahl": self.vorschlag_auswahl, **einstellung})
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

    def _postfach_vorschlag_laden(self):
        v = pf.vorschlag_laden(self.pf_prot)
        if not v or not v.get("eintraege"):
            return
        self.pf_meta = {k: v.get(k) for k in ("konto_id", "konto", "quelle", "quelle_anzeige", "uidvalidity", "gesperrt", "trenner")}
        self.pf_vorhanden = v.get("vorhanden") or []
        einst = v.get("einstellung") or {}
        self._je_quelle[POSTFACH] = (v["eintraege"], einst.get("suche") or "", einst.get("filter") or "alle")

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
    def _engine_bereit(self):
        engine = self.engine_holen()
        if not engine or not engine.bereit():
            self._meldung("Das Modell läuft nicht — im Reiter „Gerät“ auf „Starten“ klicken und warten, bis „bereit“ dasteht. "
                          "Bis dahin wird nichts gelesen und nichts verändert.", ROT)
            return None
        return engine

    def vorschlag_starten(self):
        if self.quelle == POSTFACH:
            return self._mail_vorschlag_starten()
        if self.wurzel is None or self.lauf is not None:
            return
        engine = self._engine_bereit()
        if not engine:
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
        self._lauf_starten()

    def _mail_vorschlag_starten(self):
        konto, quelle = self._konto(), self.pf_ordner_wahl.currentData()
        if not konto or not quelle or self.lauf is not None or self.arbeit:
            return
        engine = self._engine_bereit()
        if not engine:
            return
        if self.eintraege and QMessageBox.question(self, "Postfach", "Den bisherigen Vorschlag verwerfen und neu erstellen?") != QMessageBox.Yes:
            return
        self.eintraege = []; self.tabelle_fuellen()
        self.pf_meta = {"konto_id": konto["id"], "konto": {x: konto.get(x) for x in ("id", "adresse", "anbieter")}, "quelle": quelle,
                        "quelle_anzeige": self.pf_ordner_wahl.currentText().replace("  (Sonderordner)", ""), "uidvalidity": None}
        self._pf_einstellung_merken()
        self.lauf = pf.MailVorschlagslauf(self._verbinder(konto), quelle, lambda s, t: engine.json_fragen(s, t),
                                          frueher=pf.fruehere_ziele(self.pf_prot, konto["id"]), max_mails=self.pf_max.value(),
                                          neueste_zuerst=bool(self.pf_reihenfolge.currentData()), seit_tage=self.pf_tage.value() or None,
                                          ungelesene_auslassen=self.pf_ungelesen.isChecked(),
                                          stand=self.bote.stand.emit, eintrag=self.bote.eintrag.emit)
        self._lauf_starten()

    def _lauf_starten(self):
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
            self.lauf.abbrechen(); self._meldung("Wird nach dem aktuellen Eintrag angehalten …")

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
        mail = self.quelle == POSTFACH
        if mail:
            for k in ("uidvalidity", "quelle_anzeige", "gesperrt", "trenner"):
                if erg.get(k) is not None:
                    self.pf_meta[k] = erg[k]
            if erg.get("vorhanden"):
                self.pf_vorhanden = erg["vorhanden"]
        elif erg.get("vorhanden") is not None:
            self.vorhanden = erg["vorhanden"]
        zahl = {k: sum(1 for e in self.eintraege if e.get("status") == k) for k in STATUS}
        teile = [f"{zahl['vorschlag']} Vorschläge"] + [f"{zahl[k]} {t}" for k, t in (("unklar", "unklar"), ("doppelt", "doppelt"),
                                                                                    ("bleibt", "liegen schon richtig"), ("fehler", "Fehler")) if zahl[k]]
        satz = ("Abgebrochen — " if erg.get("abgebrochen") else "Fertig — ") + ", ".join(teile) + "."
        if erg.get("zu_viele"):
            if mail:
                satz += f" Es gibt mehr Mails, als „höchstens“ erlaubt — nur {self.pf_max.value()} sind dabei. Nach dem Ausführen einfach noch einmal."
            elif af.ganzer_ordner(self.vorschlag_auswahl):
                satz += f" Es gibt mehr Dateien, als „höchstens“ erlaubt — nur die ersten {self.max_dateien.value()} sind dabei."
            else:
                satz += " Weitere Dateien übrig — nach dem Ausführen einfach noch einmal „Vorschlag erstellen“."
        if erg.get("meldungen"):
            satz += " " + " · ".join(erg["meldungen"][:3]) + "."
        if not erg.get("gesamt") and not erg.get("fehler"):
            satz = ("Hier gibt es keine passenden Mails (ungelesene und als gelöscht markierte werden ausgelassen)." if mail else
                    "Hier gibt es keine Dateien zum Aufräumen (versteckte Dateien, Verweise und Pakete werden ausgelassen).")
        if erg.get("fehler"):
            self._meldung(f"{satz} {erg['fehler']}", ROT)
        else:
            self._meldung(satz + f" Jetzt prüfen, bei Bedarf Ordner{'' if mail else ' oder Namen'} ändern, dann „Ausgewählte ausführen“.",
                          GRUEN if self.eintraege else GRAU)
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
        mail = "uid" in e
        endung = Path(e["pfad"]).suffix if Path(e["pfad"]).stem and not mail else ""
        v = QTableWidgetItem()
        v.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | (Qt.ItemIsEnabled if af.kann_setzen(e, "verschieben") else Qt.NoItemFlags))
        v.setCheckState(Qt.Checked if e.get("verschieben") else Qt.Unchecked)
        datei = QTableWidgetItem(e["pfad"]); datei.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable); datei.setData(Qt.UserRole, i)
        if mail:
            datum = (e.get("datum") or "")[:16].replace("T", " ")
            datei.setToolTip(f"{e.get('betreff') or '(ohne Betreff)'}\nVon: {e.get('absender') or ''}\n{datum}, "
                             f"{af.groesse_text(e.get('groesse') or 0)} · liegt in „{e.get('liegt_in')}“"
                             + (f"\nAnhänge: {'; '.join(e['anhaenge'][:8])}" if e.get("anhaenge") else "")
                             + (f"\nGleiche Mail: {e['gleich_wie']}" if e.get("gleich_wie") else "")
                             + (f"\n\nGelesen:\n{e['text'][:300]}" if e.get("text") else ""))
        else:
            datum = datetime.fromtimestamp(e.get("geaendert") or 0).strftime("%d.%m.%Y")
            datei.setToolTip(f"{e['pfad']}\n{e.get('art', '')}, {af.groesse_text(e.get('groesse') or 0)}, geändert am {datum}"
                             + (f"\nGleiche Datei: {e['gleich_wie']}" if e.get("gleich_wie") else "")
                             + (f"\n\nGelesen:\n{e['text'][:300]}" if e.get("text") else ""))
        ordner = QTableWidgetItem(e.get("ordner") or ""); ordner.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
        ordner.setToolTip((f"{ordner.text()}\n\n" if ordner.text() else "") + (
            "Doppelklick zum Ändern (Ordner im Postfach, Ebenen mit „/“)." if mail else
            "Doppelklick zum Ändern. Leer = oberste Ebene des Startordners."))
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

    def _ziel_sperre(self, o: str) -> str | None:
        """Warum dieser Zielordner nicht geht — Dateien: aufzuräumende/ausgeschlossene Ordner; Mails: Sonderordner (Papierkorb …)."""
        if not o:
            return None
        if self.quelle == POSTFACH:
            return pf.mail_ziel_sperre(o, self.pf_meta.get("gesperrt") or [], self.pf_meta.get("trenner"))
        return af.ziel_gesperrt(o, self._gesperrt())

    def _zelle_geaendert(self, item: QTableWidgetItem):
        if self._fuellen:
            return
        r, sp = item.row(), item.column()
        i = self._index(r)
        if i is None:
            return
        e = self.eintraege[i]
        mail = self.quelle == POSTFACH
        if sp == SP_VERSCHIEBEN:
            e["verschieben"] = item.checkState() == Qt.Checked
        elif sp == SP_UMBENENNEN:
            e["umbenennen"] = item.checkState() == Qt.Checked
        elif sp == SP_ORDNER and mail and not item.text().strip():
            e.pop("ordner_ungueltig", None); e.pop("ordner_grund", None)            # Mails: leer = kein Ziel (bleibt liegen)
            e["ordner"], e["verschieben"] = "", False
        elif sp == SP_ORDNER:
            o = af.ordner_normalisieren(item.text(), leer_erlaubt=not mail)
            sperre = self._ziel_sperre(o) if o else None
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
        return af.sichtbare(self.eintraege, self.suche.text(), self._filter(), self._vh())

    def filter_anwenden(self, *_):
        sicht = set(self.sichtbare_indizes())
        for r in range(self.tabelle.rowCount()):
            self.tabelle.setRowHidden(r, self._index(r) not in sicht)
        zahlen = af.filter_zaehlen(self.eintraege, self.suche.text(), self._vh())
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
        liste = af.ordner_liste(self.eintraege, self._vh())
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
        sperre = self._ziel_sperre(neu) if neu else None
        if neu is None or sperre:
            QMessageBox.warning(self, "Aufräumen", sperre or UNGUELTIG_ORDNER)
        elif neu != alt:
            af.ordner_umbenennen(self.eintraege, alt, neu)
            self._speichern()
        self.tabelle_fuellen()

    # ---------- Ausführen und Rückgängig ----------
    def ausfuehren(self):
        if self.quelle == POSTFACH:
            return self._mail_ausfuehren()
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

    def _mail_ausfuehren(self):
        if self.lauf is not None or self.arbeit:
            return
        plan, ungueltig = pf.plan_mails(self.eintraege)
        if not plan:
            QMessageBox.information(self, "Postfach", "Nichts ausgewählt — Häkchen bei „Verschieben“ setzen."); return
        konto = self._konto(self.pf_meta.get("konto_id"))
        if not konto:
            QMessageBox.warning(self, "Postfach", "Das Konto dieses Vorschlags ist nicht mehr eingerichtet — bitte erst wieder hinzufügen."); return
        archiv = None
        if self.pf_archiv_haken.isChecked():
            if not self.pf_archiv or not self.pf_archiv.is_dir():
                QMessageBox.warning(self, "Postfach", "Für die .eml-Kopien zuerst einen Ordner wählen (oder das Häkchen entfernen)."); return
            archiv = self.pf_archiv
        frage = (f"{len(plan)} Mails im Konto „{konto['adresse']}“ verschieben?\n\nEs wird nichts gelöscht — die Mails kommen nur in andere "
                 "Ordner (Papierkorb, Spam, Gesendet und Entwürfe sind nie Ziel). Fehlende Ordner werden angelegt. Jede Aktion steht im "
                 "Protokoll; „Letzten Lauf rückgängig machen“ holt die Mails zurück.")
        if archiv:
            frage += f"\n\nVorher kommt je Mail eine Kopie (.eml) nach „{_kurz(archiv)}“."
        if ungueltig:
            frage += f"\n\n{len(ungueltig)} Einträge ohne gültigen Zielordner werden übersprungen."
        if QMessageBox.question(self, "Postfach", frage) != QMessageBox.Yes:
            return
        eintraege, meta = self.eintraege, {**self.pf_meta, "konto": konto}
        verbinden = self._verbinder(konto)

        def arbeit():
            return pf.mail_ausfuehren(verbinden, meta, eintraege, self.pf_prot, archiv=archiv,
                                      melden=lambda i, n: self.bote.stand.emit(i, n, "Mails werden verschoben …"))

        def fertig(erg, fehler):
            self.laeufe_zeigen()
            if fehler is not None:
                self._meldung(f"Angehalten: {fehler}", ROT)
                QMessageBox.warning(self, "Postfach", f"Angehalten: {fehler}\n\nBereits Erledigtes steht im Protokoll und lässt sich "
                                                      "rückgängig machen.")
                return
            erledigt = set(erg["erledigt"])
            self.eintraege = [e for i, e in enumerate(eintraege) if i not in erledigt]
            self.pf_vorhanden = sorted(set(self.pf_vorhanden) | set(erg["ordner_angelegt"]), key=str.casefold)
            self.tabelle_fuellen(); self._speichern()
            satz = f"{erg['anzahl']} Mails verschoben"
            if erg["ordner_angelegt"]:
                satz += f", {len(erg['ordner_angelegt'])} Ordner angelegt"
            if erg["archiviert"]:
                satz += f", {erg['archiviert']} Kopien als .eml abgelegt"
            satz += "."
            if erg["art"].get("kopiert+markiert"):
                satz += ("\n\nDein Server kann Mails nicht direkt verschieben: sie wurden kopiert und die Originale nur als gelöscht "
                         "markiert (endgültig entfernt das erst dein Mailprogramm).")
            if erg["fehler"]:
                satz += f"\n\n{len(erg['fehler'])} übersprungen:\n" + "\n".join(f"• {p}: {t}" for p, t in erg["fehler"][:12])
                if len(erg["fehler"]) > 12:
                    satz += f"\n… und {len(erg['fehler']) - 12} weitere"
            self._meldung(satz.split("\n")[0], GRUEN if erg["anzahl"] else GRAU)
            QMessageBox.information(self, "Postfach", satz)
        self._im_hintergrund("Mails werden verschoben …", arbeit, fertig)

    def laeufe_zeigen(self):
        self.laeufe_liste.clear()
        for l in af.laeufe(self._prot_aktuell())[:50]:
            wann = (l["beginn"] or "")[:16].replace("T", " ")
            stand = f"zurückgenommen {l['rueckgaengig'][:16].replace('T', ' ')}" if l["rueckgaengig"] else "kann rückgängig gemacht werden"
            if l.get("art") == POSTFACH:
                self.laeufe_liste.addItem(f"{wann}  ·  {l['konto']} ({l['quelle_anzeige']})  ·  {l['anzahl']} Mails  ·  {stand}")
                continue
            was = ", ".join((["lose Dateien"] if l.get("lose") else []) + list(l.get("quellen") or []))
            self.laeufe_liste.addItem(f"{wann}  ·  {_kurz(l['wurzel'])}{f' ({was})' if was else ''}  ·  {l['anzahl']} Dateien  ·  {stand}")
        if not self.laeufe_liste.count():
            self.laeufe_liste.addItem("Noch kein Lauf ausgeführt.")
        self._knoepfe()

    def rueckgaengig(self):
        if self.quelle == POSTFACH:
            return self._mail_rueckgaengig()
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

    def _mail_rueckgaengig(self):
        if self.lauf is not None or self.arbeit:
            return
        offen = [l for l in af.laeufe(self.pf_prot) if not l["rueckgaengig"]]
        if not offen:
            return
        l = offen[0]
        wann = (l["beginn"] or "")[:16].replace("T", " ")
        if QMessageBox.question(self, "Rückgängig", f"Lauf vom {wann} im Konto „{l['konto']}“ ({l['anzahl']} Mails) rückgängig machen?\n\n"
                                "Die Mails kommen in ihren alten Ordner zurück. Dabei angelegte Ordner bleiben stehen (es wird nie "
                                "gelöscht) — leere kannst du in deinem Mailprogramm selbst löschen.") != QMessageBox.Yes:
            return

        def verbinden_fuer(konto_id):
            k = self._konto(konto_id)
            if not k:
                raise pf.PostfachFehler("Das Konto dieses Laufs ist nicht mehr eingerichtet — bitte erst wieder hinzufügen.")
            return self._verbinder(k)()

        def fertig(erg, fehler):
            self.laeufe_zeigen()
            if fehler is not None:
                self._meldung(f"Rückgängig ging nicht: {fehler}", ROT)
                QMessageBox.warning(self, "Rückgängig", str(fehler)); return
            satz = f"{erg['zurueck']} Mails zurückgelegt."
            if erg["ordner_geblieben"]:
                satz += "\n\nAngelegte Ordner bleiben stehen (leer kannst du sie selbst löschen): " + ", ".join(erg["ordner_geblieben"][:10])
            if erg["probleme"]:
                satz += "\n\nHinweise:\n" + "\n".join(f"• {t}" for t in erg["probleme"][:12])
            self._meldung(satz.split("\n")[0], GRUEN)
            QMessageBox.information(self, "Rückgängig", satz)
        self._im_hintergrund("Mails werden zurückgelegt …", lambda: pf.mail_rueckgaengig(self.pf_prot, verbinden_fuer, l["id"]), fertig)
