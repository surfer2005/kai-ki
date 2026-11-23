"""E-Mails lesen (ab 0.1.22): Absender, Betreff, Datum, Text und Anhangnamen aus einer Nachricht im Internet-Format (RFC 5322).

Gemeinsam für beide Quellen des Reiters „Aufräumen“: .eml-Dateien im Ordner auf dem Mac und Mails im Postfach (IMAP). Kodierte
Kopfzeilen (=?UTF-8?…?=), quoted-printable/base64, fremde Zeichensätze und reine HTML-Mails werden in lesbaren Text übersetzt.
Abgeschnittene Nachrichten (vom Server nur der Anfang geholt) gehen auch — dann fehlt eben der Rest.
"""
import html
import re
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime


def _kopf(msg, name: str) -> str:
    """Kopfzeile dekodiert als Text; kaputte Kodierungen werden so gut es geht gelesen, nie als Fehler."""
    try:
        wert = msg.get(name)
    except Exception:  # noqa: BLE001 — kaputte Kopfzeile
        wert = None
    if wert is None:
        try:
            roh = msg.get_all(name, failobj=[]) if hasattr(msg, "get_all") else []
        except Exception:  # noqa: BLE001
            roh = []
        wert = roh[0] if roh else ""
    text = str(wert)
    if "=?" in text:                                   # noch kodiert (z. B. bei einem Fehler im Parser)
        try:
            text = str(make_header(decode_header(text)))
        except Exception:  # noqa: BLE001
            pass
    return " ".join(text.split())


def html_zu_text(roh: str) -> str:
    """HTML ohne Tags: Skripte/Stile weg, Absätze und Zeilenumbrüche bleiben als Zeilen."""
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", roh or "")
    t = re.sub(r"(?is)<!--.*?-->", " ", t)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|table)>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t\r\f\v\xa0]+", " ", t)
    t = "\n".join(z.strip() for z in t.split("\n"))
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def _teil_text(teil) -> str:
    try:
        return teil.get_content()
    except Exception:  # noqa: BLE001 — unbekannter Zeichensatz, abgeschnittenes base64 …
        try:
            daten = teil.get_payload(decode=True) or b""
        except Exception:  # noqa: BLE001
            return ""
        zs = teil.get_content_charset() or "utf-8"
        try:
            return daten.decode(zs, "replace")
        except LookupError:
            return daten.decode("utf-8", "replace")


def _ist_anhang(teil) -> bool:
    try:
        disp = teil.get_content_disposition()
    except Exception:  # noqa: BLE001
        disp = None
    return disp == "attachment" or (disp == "inline" and bool(teil.get_filename())) or (
        bool(teil.get_filename()) and teil.get_content_maintype() != "text")


def mail_lesen(roh: bytes, zeichen: int = 2000) -> dict:
    """Nachricht → {absender, an, betreff, datum (datetime|None), message_id, text, anhaenge}. Text = Klartext-Teil, sonst der
    HTML-Teil ohne Tags, gekürzt auf `zeichen`."""
    msg = BytesParser(policy=policy.default).parsebytes(roh or b"")
    datum = None
    try:
        d = msg.get("Date")
        if d:
            datum = parsedate_to_datetime(str(d))
    except Exception:  # noqa: BLE001
        datum = None
    klar, html_teile, anhaenge = [], [], []
    for teil in msg.walk():
        if teil.is_multipart():
            continue
        try:
            name = teil.get_filename()
        except Exception:  # noqa: BLE001
            name = None
        if _ist_anhang(teil):
            if name:
                anhaenge.append(" ".join(str(name).split()))
            continue
        art = teil.get_content_type()
        if art == "text/plain":
            klar.append(_teil_text(teil))
        elif art == "text/html":
            html_teile.append(_teil_text(teil))
    text = "\n".join(t for t in klar if t.strip()) or html_zu_text("\n".join(html_teile))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    mid = _kopf(msg, "Message-ID").strip()
    return {"absender": _kopf(msg, "From"), "an": _kopf(msg, "To"), "betreff": _kopf(msg, "Subject"), "datum": datum,
            "message_id": mid, "text": text[:zeichen], "anhaenge": list(dict.fromkeys(anhaenge))}


def absender_kurz(absender: str) -> str:
    """„Telekom Deutschland <rechnung@telekom.de>“ → „Telekom Deutschland“, sonst die Adresse."""
    try:
        paare = getaddresses([absender or ""])
    except Exception:  # noqa: BLE001
        paare = []
    if paare:
        name, adresse = paare[0]
        return (name or adresse or absender or "").strip()
    return (absender or "").strip()


def als_text(info: dict, zeichen: int = 2000) -> str:
    """Für die KI: die wichtigsten Kopfzeilen, Anhänge und der Text."""
    zeilen = []
    if info.get("absender"):
        zeilen.append(f"Von: {info['absender']}")
    if info.get("an"):
        zeilen.append(f"An: {info['an']}")
    if info.get("betreff"):
        zeilen.append(f"Betreff: {info['betreff']}")
    if isinstance(info.get("datum"), datetime):
        zeilen.append(f"Datum: {info['datum'].strftime('%Y-%m-%d %H:%M')}")
    if info.get("anhaenge"):
        zeilen.append("Anhänge: " + "; ".join(info["anhaenge"][:12]))
    if info.get("text"):
        zeilen += ["", info["text"]]
    return "\n".join(zeilen)[:zeichen]


def eml_datei_lesen(pfad, zeichen: int = 2000) -> str:
    """Eine .eml-Datei (oder .emlx von Apple Mail: erste Zeile = Länge) als lesbarer Text für die KI."""
    with open(pfad, "rb") as f:
        roh = f.read(4_000_000)
    if str(pfad).lower().endswith(".emlx"):
        kopf, _, rest = roh.partition(b"\n")
        if kopf.strip().isdigit():
            roh = rest[: int(kopf.strip())]
    return als_text(mail_lesen(roh, zeichen), zeichen)
