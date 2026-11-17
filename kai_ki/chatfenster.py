"""Reiter „Chat“ der App: Fragen direkt an das Modell auf diesem Mac — Antwort erscheint beim Schreiben. Eingabe wie in KAI:
ein abgerundetes Feld, links „+“ (Bild/PDF anhängen), rechts Mikrofon und Senden. Das Mikrofon nimmt mit Qt auf, erkannt wird
mit Whisper auf diesem Mac (derselbe Hörer wie für KAI). „Vorlesen“ spricht Antworten mit Chatterbox (derselbe Sprecher wie
für KAI) und spielt sie mit afplay ab. Braucht das laufende Modell („Starten“ im Reiter Gerät)."""
import base64
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QTextBrowser, QToolButton, QVBoxLayout, QWidget)

from .engine import chat_nachrichten
from .gespraech import system_text, verlauf_markdown, vorlese_text, wav_aus_pcm
from .seite import texterkennung, zu_png

KAI_GRUEN = "#1F6E5C"
ROT = "#b3412f"


class ChatBote(QObject):
    text = Signal(str)
    fertig = Signal(str, str)        # Antwort, Fehler
    erkannt = Signal(str, str)       # Text, Fehler
    vorgelesen = Signal(str)         # Fehler (leer = fertig)
    hinweis = Signal(str)


class Eingabe(QPlainTextEdit):
    """Mehrzeilig, Enter sendet, Umschalt+Enter macht eine neue Zeile; wächst bis zu sechs Zeilen mit."""
    senden = Signal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.senden.emit(); return
        super().keyPressEvent(e)


def rund(text: str, tip: str) -> QToolButton:
    b = QToolButton(); b.setText(text); b.setToolTip(tip); b.setFixedSize(34, 34); b.setCursor(Qt.PointingHandCursor)
    return b


class ChatFenster(QWidget):
    def __init__(self, engine_holen, hoerer_holen, sprecher_holen, cfg: dict, speichern):
        super().__init__()
        self.engine_holen = engine_holen         # () → Engine oder None
        self.hoerer_holen = hoerer_holen         # () → Hoerer (Whisper)
        self.sprecher_holen = sprecher_holen     # () → Sprecher (Chatterbox)
        self.cfg, self.cfg_speichern = cfg, speichern
        self.abspielen = None                    # laufendes afplay
        self.nachrichten: list = []
        self.anhang: dict | None = None
        self.laeuft = False
        self.weiter = True
        self.aufnahme = None                     # (QAudioSource, QIODevice, bytearray, Format, Beginn)
        self.bote = ChatBote()
        self.bote.text.connect(self.zeigen_laufend); self.bote.fertig.connect(self.antwort_fertig)
        self.bote.erkannt.connect(self.erkannt); self.bote.hinweis.connect(lambda t: self.hinweis.setText(t))
        self.bote.vorgelesen.connect(self.vorgelesen)

        lay = QVBoxLayout(self)
        self.anzeige = QTextBrowser(); self.anzeige.setOpenExternalLinks(False)
        self.anzeige.setMarkdown("_Frag die KI direkt auf diesem Mac — ohne KAI, ohne Netz. Modell vorher im Reiter „Gerät“ starten._")
        lay.addWidget(self.anzeige, 1)

        # Eingabefeld wie in KAI: abgerundet, + links, Mikrofon und Senden rechts
        self.feld = QFrame(); self.feld.setObjectName("feld")
        zeile = QHBoxLayout(self.feld); zeile.setContentsMargins(8, 5, 6, 5); zeile.setSpacing(6)
        self.plus = rund("+", "Bild oder PDF anhängen"); self.plus.clicked.connect(self.anhang_waehlen)
        self.eingabe = Eingabe(); self.eingabe.setPlaceholderText("Frage stellen …  ↵ zum Senden, ⇧↵ neue Zeile")
        self.eingabe.setFrameShape(QFrame.NoFrame); self.eingabe.senden.connect(self.senden)
        self.eingabe.textChanged.connect(self.hoehe_anpassen)
        self.aufnahme_text = QLabel(""); self.aufnahme_text.hide()
        self.mikro = rund("🎙", "Frage sprechen (Mikrofon)"); self.mikro.clicked.connect(self.mikro_klick)
        self.senden_knopf = rund("↑", "Senden"); self.senden_knopf.setObjectName("senden"); self.senden_knopf.clicked.connect(self.senden_oder_stopp)
        zeile.addWidget(self.plus, 0, Qt.AlignBottom); zeile.addWidget(self.eingabe, 1); zeile.addWidget(self.aufnahme_text, 1)
        zeile.addWidget(self.mikro, 0, Qt.AlignBottom); zeile.addWidget(self.senden_knopf, 0, Qt.AlignBottom)
        lay.addWidget(self.feld)
        unten = QHBoxLayout()
        self.hinweis = QLabel(""); self.hinweis.setStyleSheet("color:#777"); self.hinweis.setWordWrap(True)
        neu = QPushButton("Neues Gespräch"); neu.clicked.connect(self.neu)
        unten.addWidget(self.hinweis, 1); unten.addWidget(neu)
        lay.addLayout(unten)
        # Vorlesen: letzte Antwort, automatisch jede neue, eigene Stimmprobe
        vz = QHBoxLayout()
        self.vorlesen_knopf = QPushButton("🔊 Vorlesen"); self.vorlesen_knopf.setToolTip("Letzte Antwort vorlesen"); self.vorlesen_knopf.clicked.connect(self.vorlesen_klick)
        self.auto_vorlesen = QCheckBox("Antworten vorlesen"); self.auto_vorlesen.setChecked(bool(self.cfg.get("chat_vorlesen")))
        self.auto_vorlesen.toggled.connect(lambda an: (self.cfg.__setitem__("chat_vorlesen", an), self.cfg_speichern(self.cfg)))
        self.stimme_knopf = QPushButton(); self.stimme_knopf.clicked.connect(self.stimme_waehlen); self.stimme_beschriften()
        vz.addWidget(self.vorlesen_knopf); vz.addWidget(self.auto_vorlesen); vz.addStretch(); vz.addWidget(self.stimme_knopf)
        lay.addLayout(vz)
        self.stil(False); self.hoehe_anpassen()
        self.uhr = QTimer(self); self.uhr.timeout.connect(self.aufnahme_zeit)

    # ---------- Aussehen ----------
    def stil(self, rot: bool):
        rand = ROT if rot else "palette(mid)"
        self.feld.setStyleSheet(f"""
            QFrame#feld {{ border: 1px solid {rand}; border-radius: 21px; background: palette(base); }}
            QPlainTextEdit {{ background: transparent; border: none; font-size: 14px; }}
            QToolButton {{ border: none; border-radius: 17px; font-size: 17px; background: transparent; }}
            QToolButton:hover {{ background: palette(midlight); }}
            QToolButton#senden {{ background: {KAI_GRUEN}; color: white; font-weight: bold; }}
            QToolButton#senden:disabled {{ background: #9fb8b0; }}
            QToolButton#rot {{ background: {ROT}; color: white; }}
        """)

    def hoehe_anpassen(self):
        zeilen = max(1, min(6, int(self.eingabe.document().size().height())))
        h = int(self.eingabe.fontMetrics().lineSpacing() * zeilen + 14)
        self.eingabe.setFixedHeight(max(34, h))
        self.senden_knopf.setEnabled(self.laeuft or bool(self.eingabe.toPlainText().strip() or self.anhang))

    # ---------- Gespräch ----------
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
        self.hinweis.setText(f"📎 {p.name} (bei PDF die erste Seite)"); self.hoehe_anpassen()

    def senden_oder_stopp(self):
        if self.laeuft:
            self.weiter = False
        else:
            self.senden()

    def senden(self):
        text = self.eingabe.toPlainText().strip()
        if self.laeuft or self.aufnahme or (not text and not self.anhang):
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
        self.senden_knopf.setText("■"); self.senden_knopf.setToolTip("Antwort stoppen"); self.senden_knopf.setEnabled(True)
        self.plus.setEnabled(False); self.mikro.setEnabled(False)
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
        self.senden_knopf.setText("↑"); self.senden_knopf.setToolTip("Senden"); self.plus.setEnabled(True); self.mikro.setEnabled(True)
        self.anzeige.setMarkdown(verlauf_markdown(self.nachrichten))
        sb = self.anzeige.verticalScrollBar(); sb.setValue(sb.maximum())
        self.hoehe_anpassen(); self.eingabe.setFocus()
        if text.strip() and self.weiter and self.auto_vorlesen.isChecked():
            self.vorlesen(text)

    # ---------- Vorlesen ----------
    def stimme_beschriften(self):
        p = self.cfg.get("chat_stimme")
        self.stimme_knopf.setText(f"Stimme: {Path(p).name}" if p and Path(p).exists() else "Stimme: eingebaut")
        self.stimme_knopf.setToolTip("Eigene Stimmprobe (WAV/MP3/M4A, 10–30 s, deutsch gesprochen) — Klick: wählen, abbrechen = eingebaute Stimme")

    def stimme_waehlen(self):
        pfad, _ = QFileDialog.getOpenFileName(self, "Stimmprobe wählen", str(Path.home()), "Ton (*.wav *.mp3 *.m4a)")
        self.cfg["chat_stimme"] = pfad or None; self.cfg_speichern(self.cfg); self.stimme_beschriften()

    def vorlesen_klick(self):
        if self.abspielen and self.abspielen.poll() is None:
            self.abspielen.terminate(); return
        letzte = next((m["content"] for m in reversed(self.nachrichten) if m["role"] == "assistant"), None)
        if letzte:
            self.vorlesen(letzte)
        else:
            self.hinweis.setText("Noch keine Antwort zum Vorlesen.")

    def vorlesen(self, text: str):
        self.vorlesen_knopf.setEnabled(False); self.vorlesen_knopf.setText("🔊 wird gesprochen …")
        threading.Thread(target=self._sprechen, args=(vorlese_text(text),), daemon=True).start()

    def _sprechen(self, text: str):
        try:
            stimme = None; p = self.cfg.get("chat_stimme")
            if p and Path(p).exists():
                endung = Path(p).suffix.lower()
                stimme = {"data": base64.b64encode(Path(p).read_bytes()).decode(), "mime": {".mp3": "audio/mpeg", ".m4a": "audio/mp4"}.get(endung, "audio/wav")}
            wav, _sek = self.sprecher_holen().sprechen(text, "de", 0.5, 0.5, stimme, fortschritt=lambda t: self.bote.hinweis.emit(t))
            datei = Path(tempfile.mkstemp(suffix=".wav")[1]); datei.write_bytes(wav)
            self.bote.vorgelesen.emit("")
            self.abspielen = subprocess.Popen(["afplay", str(datei)])
            self.abspielen.wait(); datei.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            self.bote.vorgelesen.emit(str(e))

    def vorgelesen(self, fehler: str):
        self.vorlesen_knopf.setEnabled(True); self.vorlesen_knopf.setText("🔊 Vorlesen")
        self.hinweis.setText(f"Vorlesen fehlgeschlagen: {fehler}" if fehler else "Wird abgespielt — „🔊 Vorlesen“ noch einmal klicken hält an.")

    # ---------- Mikrofon ----------
    def mikro_klick(self):
        if self.aufnahme:
            self.aufnahme_beenden()
        else:
            # macOS fragt einmal nach der Freigabe; ohne sie kommt nur Stille
            try:
                from PySide6.QtCore import QMicrophonePermission
                app = QApplication.instance(); erlaubnis = QMicrophonePermission()
                stand = app.checkPermission(erlaubnis)
                if stand == Qt.PermissionStatus.Undetermined:
                    app.requestPermission(erlaubnis, self, lambda *_: self.aufnahme_starten()); return
                if stand == Qt.PermissionStatus.Denied:
                    self.hinweis.setText("Das Mikrofon ist für KAI KI nicht freigegeben — Systemeinstellungen → Datenschutz & Sicherheit → Mikrofon."); return
            except Exception:  # noqa: BLE001 — ältere Qt ohne Rechte-Abfrage: einfach versuchen
                pass
            self.aufnahme_starten()

    def aufnahme_starten(self):
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        geraet = QMediaDevices.defaultAudioInput()
        if geraet.isNull():
            self.hinweis.setText("Kein Mikrofon gefunden."); return
        fmt = QAudioFormat(); fmt.setSampleRate(16000); fmt.setChannelCount(1); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not geraet.isFormatSupported(fmt):
            fmt = geraet.preferredFormat()
        quelle = QAudioSource(geraet, fmt, self); daten = bytearray()
        io = quelle.start()
        io.readyRead.connect(lambda: daten.extend(io.readAll().data()))
        self.aufnahme = (quelle, io, daten, fmt, time.time())
        self.mikro.setText("■"); self.mikro.setObjectName("rot"); self.mikro.setToolTip("Aufnahme beenden"); self.stil(True)
        self.eingabe.hide(); self.aufnahme_text.show(); self.aufnahme_zeit(); self.uhr.start(250)
        self.hinweis.setText("Fertig gesprochen? Auf ■ klicken. Erkannt wird auf diesem Mac (Whisper); der Text kommt zum Prüfen ins Feld.")

    def aufnahme_zeit(self):
        if self.aufnahme:
            s = int(time.time() - self.aufnahme[4])
            self.aufnahme_text.setText(f"<span style='color:{ROT}'>●</span> Aufnahme {s} s — sprich deine Frage")
            if s >= 120:
                self.aufnahme_beenden()

    def aufnahme_beenden(self):
        quelle, io, daten, fmt, _ = self.aufnahme
        try:
            daten.extend(io.readAll().data())
        except Exception:  # noqa: BLE001
            pass
        quelle.stop(); self.uhr.stop(); self.aufnahme = None
        self.mikro.setText("🎙"); self.mikro.setObjectName(""); self.mikro.setToolTip("Frage sprechen (Mikrofon)"); self.stil(False)
        from PySide6.QtMultimedia import QAudioFormat
        gleit = fmt.sampleFormat() == QAudioFormat.SampleFormat.Float
        wav = wav_aus_pcm(bytes(daten), fmt.sampleRate(), fmt.channelCount(), gleit)
        if len(wav) < 44 + fmt.sampleRate():          # unter ~0,5 s: nichts zu erkennen
            self.eingabe.show(); self.aufnahme_text.hide(); self.hinweis.setText(""); return
        self.aufnahme_text.setText("erkenne Sprache …"); self.mikro.setEnabled(False); self.senden_knopf.setEnabled(False)
        threading.Thread(target=self._erkennen, args=(wav,), daemon=True).start()

    def _erkennen(self, wav: bytes):
        try:
            text = self.hoerer_holen().hoeren(wav, "de", fortschritt=lambda t: self.bote.hinweis.emit(t))
            self.bote.erkannt.emit(text, "")
        except Exception as e:  # noqa: BLE001
            self.bote.erkannt.emit("", str(e))

    def erkannt(self, text: str, fehler: str):
        self.aufnahme_text.hide(); self.eingabe.show(); self.mikro.setEnabled(True)
        self.hinweis.setText(f"Fehler bei der Spracherkennung: {fehler}" if fehler else "")
        if text.strip():
            alt = self.eingabe.toPlainText().strip()
            self.eingabe.setPlainText(f"{alt} {text.strip()}" if alt else text.strip())
            c = self.eingabe.textCursor(); c.movePosition(c.MoveOperation.End); self.eingabe.setTextCursor(c)
        self.hoehe_anpassen(); self.eingabe.setFocus()
