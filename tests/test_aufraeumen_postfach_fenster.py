"""Reiter „Aufräumen“, Quelle „Postfach“ einmal ganz durchgespielt — Konto im Dialog verbinden, Ordner laden, Vorschlag mit einer
gespielten KI, Liste (Filter „Doppelt“, Kopf-Häkchen, Zielordner von Hand), ausführen, rückgängig. Gegen den kleinen IMAP-Server
aus tests/imap_fake.py; läuft auf dem Mac (beim Bauen) und unter Linux ohne Bildschirm (offscreen)."""
import imaplib
import os
import sys
import time

import pytest

pytest.importorskip("PySide6")
if sys.platform != "darwin":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from imap_fake import Server, mail  # noqa: E402

PASSWORT = "Geheim-123"


class MailKI:
    def __init__(self):
        self.fragen = []

    def bereit(self):
        return True

    def json_fragen(self, system, text):
        self.fragen.append(text)
        if "Betreff: Telekom" in text:
            return '{"ordner": "Rechnungen", "grund": "Rechnung"}'
        if "Betreff: Versicherung" in text:
            return '{"ordner": "Versicherungen", "grund": "Versicherung"}'
        return '{"ordner": null, "grund": "unklar"}'


@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def antworten(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    gesehen = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: (gesehen.append(a[2]), QMessageBox.Yes)[1])
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: gesehen.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: gesehen.append(a[2]))
    return gesehen


@pytest.fixture()
def server():
    s = Server()
    s.ordner("Rechnungen"); s.ordner("Papierkorb", ["\\Trash"])
    s.mail("INBOX", mail("Telekom Rechnung Oktober", mid="<a@t>"))
    s.mail("INBOX", mail("Versicherung Police", absender="Allianz <a@allianz.de>", mid="<b@t>"))
    s.mail("INBOX", mail("Vereinsfest", absender="Segelclub <v@sc.de>", mid="<c@t>"))
    s.mail("INBOX", mail("Telekom Rechnung Oktober", mid="<a@t>"))
    yield s
    s.stoppen()


def _oeffnen(konto):
    return imaplib.IMAP4(konto["host"], int(konto["port"]), timeout=10)


def _warten(app, bedingung, sekunden=20):
    ende = time.time() + sekunden
    while not bedingung() and time.time() < ende:
        app.processEvents(); time.sleep(0.01)
    app.processEvents()
    assert bedingung(), "wurde nicht rechtzeitig fertig"


def _fenster(tmp_path, ki, speicher, **kw):
    from kai_ki.aufraeumfenster import AufraeumFenster
    return AufraeumFenster(lambda: ki, tmp_path / "protokoll", schluesselbund=speicher, imap_oeffnen=_oeffnen, **kw)


def _konto_verbinden(app, f, server, passwort=PASSWORT):
    from kai_ki.aufraeumfenster import KontoDialog
    d = KontoDialog(f)
    d.anbieter.setCurrentIndex(d.anbieter.findData("anders"))
    d.adresse.setText("peter@example.de"); d.host.setText("127.0.0.1"); d.port.setValue(server.port); d.passwort.setText(passwort)
    d.pruefen()
    _warten(app, lambda: d.ok_knopf.isEnabled())
    return d


def test_postfach_ganz_durchgespielt(tmp_path, app, antworten, server):
    from PySide6.QtCore import Qt
    from kai_ki import aufraeumen as af
    from kai_ki import schluesselbund as sb
    from kai_ki.aufraeumfenster import POSTFACH, SP_DATEI, SP_NAME, SP_ORDNER, SP_UMBENENNEN, SP_VERSCHIEBEN
    speicher = sb.Arbeitsspeicher()
    ki = MailKI()
    f = _fenster(tmp_path, ki, speicher)
    f.quelle_setzen(POSTFACH)
    assert f.postfach_box.isVisibleTo(f) and not f.was_box.isVisibleTo(f) and not f.ordner_zeile.isVisibleTo(f) and f.tabelle.isColumnHidden(SP_NAME)
    assert f.tabelle.horizontalHeaderItem(SP_DATEI).text() == "Mail" and not f.start_knopf.isEnabled()

    # falsches Passwort: klare Meldung, nichts gespeichert, Passwort taucht nicht auf
    d = _konto_verbinden(app, f, server, passwort="falsch-geheim")
    assert d.ergebnis is None and "Anmeldung abgelehnt" in d.status.text() and "falsch-geheim" not in d.status.text()
    assert not f.konten and speicher.werte == {}
    # richtig: Konto gespeichert, Passwort nur im Schlüsselbund
    d = _konto_verbinden(app, f, server)
    assert d.ergebnis and d.ergebnis["ordner_anzahl"] == 3
    f._konto_hinzugefuegt(d.ergebnis)
    _warten(app, lambda: f.arbeit is None)
    assert list(speicher.werte.values()) == [PASSWORT]
    assert PASSWORT not in (tmp_path / "protokoll" / "postfach" / "konten.json").read_text("utf-8")
    ordner = [f.pf_ordner_wahl.itemText(i) for i in range(f.pf_ordner_wahl.count())]
    assert ordner == ["INBOX", "Papierkorb  (Sonderordner)", "Rechnungen"] and f.pf_ordner_wahl.currentData() == "INBOX"
    assert f.start_knopf.isEnabled()

    vorher = server.inhalt("INBOX")
    f.vorschlag_starten(); _warten(app, lambda: f.lauf is None)
    assert server.inhalt("INBOX") == vorher                                       # nur gelesen
    assert f.tabelle.rowCount() == 4 and len(ki.fragen) == 3
    e = {(x["betreff"], x["status"]): x for x in f.eintraege}
    assert e[("Telekom Rechnung Oktober", "doppelt")]["ordner"] == "Doppelt"
    assert e[("Versicherung Police", "vorschlag")]["ordner"] == "Versicherungen"
    neu = {f.ordner_tab.item(r, 0).text(): f.ordner_tab.item(r, 2).text() for r in range(f.ordner_tab.rowCount())}
    assert neu == {"Doppelt": "neu", "Rechnungen": "", "Versicherungen": "neu"}
    assert not f.kopf.aktiv[SP_UMBENENNEN]                                        # Mails werden nie umbenannt

    def zeile(betreff, status=None):
        return next(r for r in range(f.tabelle.rowCount()) if f.tabelle.item(r, SP_DATEI).text().startswith(betreff)
                    and (status is None or f.eintraege[f._index(r)]["status"] == status))
    # Filter „Doppelt“ → Kopf-Häkchen aus → die Kopie wird nicht angefasst
    f.filter_knoepfe["doppelt"].click()
    f.kopf_geklickt(SP_VERSCHIEBEN)
    assert not e[("Telekom Rechnung Oktober", "doppelt")]["verschieben"] and e[("Versicherung Police", "vorschlag")]["verschieben"]
    f.filter_knoepfe["alle"].click()
    # unklare Mail: Papierkorb von Hand → abgelehnt; „Verein“ → gewählt
    f.tabelle.item(zeile("Vereinsfest"), SP_ORDNER).setText("Papierkorb/Alt")
    v = f.eintraege[f._index(zeile("Vereinsfest"))]
    assert not v["verschieben"] and "Sonderordner" in v["ordner_grund"]
    f.tabelle.item(zeile("Vereinsfest"), SP_ORDNER).setText("Verein")
    assert f.tabelle.item(zeile("Vereinsfest"), SP_VERSCHIEBEN).checkState() == Qt.Checked and v["status"] == "hand"

    # gemerkt: ein neues Fenster startet im Postfach mit demselben Vorschlag
    g = _fenster(tmp_path, ki, speicher)
    assert g.quelle == POSTFACH and len(g.eintraege) == 4 and g.arbeit is None          # beim Start keine Serverabfrage
    assert g.pf_ordner_wahl.currentData() == "INBOX" and g.start_knopf.isEnabled()

    f.ausfuehren(); _warten(app, lambda: f.arbeit is None)
    assert server.message_ids("Rechnungen") == ["<a@t>"] and server.message_ids("Versicherungen") == ["<b@t>"]
    assert server.message_ids("Verein") == ["<c@t>"] and server.message_ids("INBOX") == ["<a@t>"]   # Kopie blieb (Häkchen aus)
    assert [x["status"] for x in f.eintraege] == ["doppelt"]
    assert "3 Mails verschoben" in f.stand_text.text() and "kann rückgängig" in f.laeufe_liste.item(0).text()
    assert "Mails" in f.laeufe_liste.item(0).text() and f.zurueck_knopf.isEnabled()

    f.rueckgaengig(); _warten(app, lambda: f.arbeit is None)
    assert sorted(server.message_ids("INBOX")) == ["<a@t>", "<a@t>", "<b@t>", "<c@t>"]
    assert "zurückgenommen" in f.laeufe_liste.item(0).text() and not f.zurueck_knopf.isEnabled()
    assert af.laeufe(tmp_path / "protokoll" / "postfach")[0]["rueckgaengig"]
    assert "Verein" in server.boxen                                               # angelegte Ordner bleiben stehen

    # zurück zu „Ordner auf dem Mac“: dort ist alles wie vorher
    f.quelle_setzen("ordner")
    assert f.eintraege == [] and f.tabelle.horizontalHeaderItem(SP_DATEI).text() == "Datei" and not f.tabelle.isColumnHidden(SP_NAME)


def test_outlook_konto_mit_microsoft_anmeldung(tmp_path, app, antworten, server, monkeypatch):
    import time as zeit
    from kai_ki import postfach as pf
    from kai_ki import schluesselbund as sb
    from kai_ki.aufraeumfenster import POSTFACH, KontoDialog
    server.token = "AT-1"
    aufrufe = []

    def anmelden(client_id, adresse, abbruch=None):
        aufrufe.append((client_id, adresse))
        return {"access_token": "AT-1", "refresh_token": "RT-1", "laeuft_ab": zeit.time() + 3000}
    speicher = sb.Arbeitsspeicher()
    f = _fenster(tmp_path, MailKI(), speicher, ms_anmelden=anmelden)
    f.quelle_setzen(POSTFACH)
    d = KontoDialog(f)
    d.anbieter.setCurrentIndex(d.anbieter.findData("outlook"))
    assert not d.passwort.isVisibleTo(d) and d.client_id.isVisibleTo(d) and "Microsoft" in d.ok_knopf.text()
    d.adresse.setText("peter@example.de")
    d.pruefen()                                                                   # ohne Client-ID: klare Meldung
    assert "eigene Client-ID" in d.status.text() and not aufrufe
    d.client_id.setText("11111111-2222-3333-4444-555555555555")
    echt = pf.konto_ordnen                                                         # Testserver statt outlook.office365.com
    monkeypatch.setattr(pf, "konto_ordnen", lambda k: {**echt(k), "host": "127.0.0.1", "port": server.port})
    d.pruefen(); _warten(app, lambda: d.ok_knopf.isEnabled())
    assert d.ergebnis, d.status.text()
    assert aufrufe == [("11111111-2222-3333-4444-555555555555", "peter@example.de")]
    assert server.anmeldungen[-1] == ("XOAUTH2", "peter@example.de")
    assert speicher.lesen(sb.schluessel(d.ergebnis["id"], "refresh")) == "RT-1"
    k = pf.konten_laden(tmp_path / "protokoll" / "postfach")[0]
    assert k["anmeldung"] == "oauth" and "RT-1" not in str(k) and "AT-1" not in str(k)
