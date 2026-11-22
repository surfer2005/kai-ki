"""Eine Belegseite vorbereiten: PDF → Bild (pdfium), Texterkennung mit Apples Vision (auf dem Gerät, ohne Netz)."""
import base64
import io
import threading

MAX_KANTE = 1400          # längste Bildkante für das Modell: genug zum Lesen, nicht mehr Rechenzeit als nötig
# pdfium ist nicht thread-sicher — Aufträge aus KAI, Chat-Reiter und Aufräumen laufen in eigenen Threads
PDFIUM_SPERRE = threading.Lock()


def zu_png(data_b64: str, mime: str) -> bytes:
    """Seite (einseitiges PDF oder Bild, base64) → PNG mit höchstens MAX_KANTE Pixeln Kantenlänge."""
    roh = base64.b64decode(data_b64)
    from PIL import Image
    if mime == "application/pdf":
        import pypdfium2 as pdfium
        with PDFIUM_SPERRE:
            pdf = pdfium.PdfDocument(roh)
            seite = pdf[0]
            b, h = seite.get_size()                      # Punkte (1/72 Zoll)
            bild = seite.render(scale=MAX_KANTE / max(b, h)).to_pil()
            pdf.close()
    else:
        bild = Image.open(io.BytesIO(roh))
        bild.thumbnail((MAX_KANTE, MAX_KANTE))
    if bild.mode not in ("RGB", "L"):
        bild = bild.convert("RGB")
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG", optimize=True)
    return puffer.getvalue()


def zeilen_ordnen(stuecke: list[tuple[float, float, float, str]]) -> str:
    """Erkannte Textstücke (x, y_oben, höhe, text — y von oben, 0..1) zu Zeilen: gleiche Höhe = eine Zeile, links nach rechts."""
    zeilen: list[list[tuple[float, float, float, str]]] = []
    for st in sorted(stuecke, key=lambda s: (s[1], s[0])):
        if zeilen and abs(zeilen[-1][0][1] - st[1]) < max(0.006, st[2] * 0.5):
            zeilen[-1].append(st)
        else:
            zeilen.append([st])
    return "\n".join("  ".join(s[3] for s in sorted(z, key=lambda s: s[0])) for z in zeilen)


def _vision(handler_bauen) -> str:
    """Apples Texterkennung (Vision, Deutsch + Englisch) über einen VNImageRequestHandler. Leer, wenn nicht verfügbar."""
    try:
        import Vision
    except ImportError:
        return ""
    handler = handler_bauen(Vision)
    if handler is None:
        return ""
    anfrage = Vision.VNRecognizeTextRequest.alloc().init()
    anfrage.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    anfrage.setRecognitionLanguages_(["de-DE", "en-US"])
    anfrage.setUsesLanguageCorrection_(True)
    ok, _fehler = handler.performRequests_error_([anfrage], None)
    if not ok:
        return ""
    stuecke = []
    for beob in anfrage.results() or []:
        kandidat = beob.topCandidates_(1)
        if not kandidat:
            continue
        box = beob.boundingBox()                     # normiert, Ursprung unten links
        x, y, h = box.origin.x, box.origin.y, box.size.height
        stuecke.append((x, 1.0 - (y + h), h, str(kandidat[0].string())))
    return zeilen_ordnen(stuecke)


def texterkennung(png: bytes) -> str:
    """Apples Texterkennung für ein PNG. Leerer Text, wenn sie nicht verfügbar ist."""
    def bauen(Vision):
        from Foundation import NSData
        daten = NSData.dataWithBytes_length_(png, len(png))
        return Vision.VNImageRequestHandler.alloc().initWithData_options_(daten, None)
    try:
        return _vision(bauen)
    except ImportError:
        return ""


def texterkennung_datei(pfad) -> str:
    """Apples Texterkennung direkt für eine Bilddatei (liest auch HEIC/TIFF, die Pillow nicht kennt). Leer ohne Vision."""
    def bauen(Vision):
        from Foundation import NSURL
        return Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(pfad)), None)
    try:
        return _vision(bauen)
    except ImportError:
        return ""
