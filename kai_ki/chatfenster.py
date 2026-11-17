"""Reiter „Chat“ der App: Fragen direkt an das Modell auf diesem Mac — Antwort erscheint beim Schreiben. Optional ein Bild
oder PDF anhängen (erste Seite, mit Texterkennung). Braucht das laufende Modell („Starten“ im Reiter Gerät)."""
import base64
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from .engine import chat_nachrichten
from .gespraech import system_text, verlauf_markdown
from .seite import texterkennung, zu_png


class ChatBote(QObject):
    text = Signal(str)
    fertig = Signal(str, str)        # Antwort, Fehler


class ChatFenster(QWidget):
    def __init__(self, engine_holen):
        super().__init__()
        self.engine_holen = engine_holen         # () → Engine oder None
        self.nachrichten: list = []
        self.anhang: dict | None = None
        self.laeuft = False
        self.weiter = True
        self.bote = ChatBote(); self.bote.text.connect(self.zeigen_laufend); self.bote.fertig.connect(self.antwort_fertig)

        lay = QVBoxLayout(self)
        self.anzeige = QTextBrowser(); self.anzeige.setOpenExternalLinks(False)
        self.anzeige.setMarkdown("_Frag die KI direkt auf diesem Mac — ohne KAI, ohne Netz. Modell vorher im Reiter „Gerät“ starten._")
        lay.addWidget(self.anzeige, 1)
        self.hinweis = QLabel(""); self.hinweis.setStyleSheet("color:#666"); self.hinweis.setWordWrap(True); lay.addWidget(self.hinweis)
        zeile = QHBoxLayout()
        self.plus = QPushButton("+"); self.plus.setFixedWidth(36); self.plus.setToolTip("Bild oder PDF anhängen"); self.plus.clicked.connect(self.anhang_waehlen)
        self.eingabe = QLineEdit(); self.eingabe.setPlaceholderText("Frage stellen … (Enter sendet)"); self.eingabe.returnPressed.connect(self.senden)
        self.senden_knopf = QPushButton("Senden"); self.senden_knopf.clicked.connect(self.senden)
        self.stopp_knopf = QPushButton("Stopp"); self.stopp_knopf.clicked.connect(self.stoppen); self.stopp_knopf.setEnabled(False)
        neu = QPushButton("Neues Gespräch"); neu.clicked.connect(self.neu)
        for wdg in (self.plus, self.eingabe, self.senden_knopf, self.stopp_knopf, neu):
            zeile.addWidget(wdg)
        zeile.setStretch(1, 1)
        lay.addLayout(zeile)

    def neu(self):
        if self.laeuft:
            return
        self.nachrichten = []; self.anhang = None; self.hinweis.setText("")
        self.anzeige.setMarkdown("_Neues Gespräch._")

    def anhang_waehlen(self):
        pfad, _ = QFileDialog.getOpenFileName(self, "Bild oder PDF anhängen", str(Path.home()), "Bilder und PDF (*.png *.jpg *.jpeg *.webp *.pdf)")
        if not pfad:
            return
        p = Path(pfad)
        mime = "application/pdf" if p.suffix.lower() == ".pdf" else "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        self.anhang = {"name": p.name, "data": base64.b64encode(p.read_bytes()).decode(), "mime": mime}
        self.hinweis.setText(f"Angehängt: {p.name} (bei PDF die erste Seite)")

    def senden(self):
        text = self.eingabe.text().strip()
        if self.laeuft or (not text and not self.anhang):
            return
        engine = self.engine_holen()
        if not engine or not engine.bereit():
            self.hinweis.setText("Das Modell läuft nicht — im Reiter „Gerät“ auf „Starten“ und warten, bis „bereit“ dasteht.")
            return
        frage = {"role": "user", "content": text or "Was steht in diesem Anhang? Fasse das Wichtigste zusammen."}
        if self.anhang:
            frage["anhang"] = self.anhang["name"]; frage["seiten"] = [{"data": self.anhang["data"], "mime": self.anhang["mime"]}]
        self.nachrichten.append(frage)
        self.anhang = None; self.eingabe.clear(); self.hinweis.setText("")
        self.laeuft, self.weiter = True, True
        self.senden_knopf.setEnabled(False); self.stopp_knopf.setEnabled(True); self.plus.setEnabled(False)
        self.zeigen_laufend("")
        threading.Thread(target=self._rechnen, args=(engine,), daemon=True).start()

    def _rechnen(self, engine):
        letzt = [0.0]

        def beim_schreiben(t: str) -> bool:
            if time.time() - letzt[0] > 0.08:
                letzt[0] = time.time(); self.bote.text.emit(t)
            return self.weiter
        try:
            # Anhänge nur an der jüngsten Frage mit Anhang mitschicken (Kontext des Modells ist klein)
            verlauf = [{"role": "system", "content": system_text()}]
            letzte_mit = max((i for i, m in enumerate(self.nachrichten) if m.get("seiten")), default=-1)
            for i, m in enumerate(self.nachrichten[-12:], start=max(0, len(self.nachrichten) - 12)):
                e = {"role": m["role"], "content": m["content"]}
                if i == letzte_mit:
                    e["seiten"] = m["seiten"]
                verlauf.append(e)
            n = chat_nachrichten(verlauf, bild=lambda s: zu_png(s["data"], s.get("mime", "image/jpeg")), ocr=texterkennung)
            text, _ein, _aus = engine.chat(n, 1500, 0.4, beim_schreiben)
            self.bote.fertig.emit(text, "")
        except Exception as e:  # noqa: BLE001
            self.bote.fertig.emit("", str(e))

    def zeigen_laufend(self, t: str):
        self.anzeige.setMarkdown(verlauf_markdown(self.nachrichten, t))
        sb = self.anzeige.verticalScrollBar(); sb.setValue(sb.maximum())

    def antwort_fertig(self, text: str, fehler: str):
        if fehler:
            self.hinweis.setText(f"Fehler: {fehler}")
        if text.strip():
            self.nachrichten.append({"role": "assistant", "content": text.strip() + ("" if self.weiter else " …")})
        self.laeuft = False
        self.senden_knopf.setEnabled(True); self.stopp_knopf.setEnabled(False); self.plus.setEnabled(True)
        self.anzeige.setMarkdown(verlauf_markdown(self.nachrichten))
        sb = self.anzeige.verticalScrollBar(); sb.setValue(sb.maximum())
        self.eingabe.setFocus()

    def stoppen(self):
        self.weiter = False
