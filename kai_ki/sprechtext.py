"""Text zum Sprechen vorbereiten (Peter 2026-11-18: „ein Problem sind die Sprachausgaben mit Zahlen“). Chatterbox liest
Ziffern, deutsche Tausenderpunkte, Datumsangaben, Uhrzeiten, Einheiten und Abkürzungen oft falsch oder englisch — deshalb
schreiben wir sie vorher in Wörter um. Eine Stelle für alles, was gesprochen wird (Vorlesen in KAI, Chat-Reiter, Werbefilm).
Große Beträge und Mengen werden gerundet gesprochen („rund 24,1 Millionen Euro“) — volle Ziffern behält beim Zuhören niemand."""
import re

try:
    from num2words import num2words as _n2w
except ImportError:                                   # ohne Bibliothek: Zahlen bleiben stehen, nichts bricht
    _n2w = None

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
ABKUERZUNGEN = [
    (r"\bz\.\s?B\.", "zum Beispiel"), (r"\bd\.\s?h\.", "das heißt"), (r"\bu\.\s?a\.", "unter anderem"), (r"\bca\.", "circa"),
    (r"\bbzw\.", "beziehungsweise"), (r"\busw\.", "und so weiter"), (r"\binkl\.", "inklusive"), (r"\bexkl\.", "exklusive"),
    (r"\bggf\.", "gegebenenfalls"), (r"\bevtl\.", "eventuell"), (r"\bNr\.", "Nummer"), (r"\bStd\.", "Stunden"), (r"\bMin\.", "Minuten"),
    (r"\bMio\.", "Millionen"), (r"\bMrd\.", "Milliarden"), (r"\bTsd\.", "tausend"), (r"\bMwSt\.?", "Mehrwertsteuer"),
    (r"\bUSt\.?", "Umsatzsteuer"), (r"\bGmbH\b", "G m b H"), (r"\bKAI\b", "Kai"), (r"\bvgl\.", "vergleiche"), (r"\bggü\.", "gegenüber"),
]
EINHEITEN = {"km": "Kilometer", "km/h": "Kilometer pro Stunde", "kWh": "Kilowattstunden", "kW": "Kilowatt", "kg": "Kilogramm",
             "l": "Liter", "L": "Liter", "h": "Stunden", "min": "Minuten", "s": "Sekunden", "m": "Meter", "cm": "Zentimeter",
             "t": "Tonnen", "kn": "Knoten", "°C": "Grad", "°": "Grad"}
WEIBLICH = re.compile(r"(ung|ion|heit|keit|schaft|tät|ik|e|ur|anz|enz)$", re.I)


def wort(n, art="cardinal") -> str:
    if _n2w is None:
        return str(n)
    try:
        return _n2w(n, lang="de", to=art)
    except Exception:  # noqa: BLE001
        return str(n)


def _zahl(s: str) -> float:
    """„1.234,56“ / „1234,5“ / „1234“ → Zahl (deutsche Schreibweise)."""
    return float(s.replace(".", "").replace(",", "."))


def zahl_wort(x: float, nachkomma: int = 2) -> str:
    """Zahl in Worte; Nachkommastellen als „Komma …“, ohne überflüssige Nullen."""
    if abs(x - round(x)) < 1e-9:
        return wort(int(round(x)))
    return wort(round(x, nachkomma))


def gerundet(x: float) -> str:
    """Große Mengen gesprochen: ab einer Million „rund 1,8 Millionen“, ab hunderttausend auf drei Stellen gerundet."""
    a = abs(x)
    if a >= 1e9:
        return f"rund {zahl_wort(round(x / 1e9, 1), 1)} Milliarden"
    if a >= 1e6:
        m = round(x / 1e6, 1)
        return f"rund {'eine' if m == 1 else zahl_wort(m, 1)} Million{'' if m == 1 else 'en'}"
    if a >= 1e5:
        return f"rund {wort(int(round(x, -3)))}"
    return zahl_wort(x)


def euro(x: float) -> str:
    if abs(x) >= 1e4:
        return f"{gerundet(x)} Euro"
    e = int(abs(x)); c = int(round((abs(x) - e) * 100))
    if c == 100:
        e, c = e + 1, 0
    vorz = "minus " if x < 0 else ""
    eu = "ein" if e == 1 else wort(e)
    return f"{vorz}{eu} Euro" + (f" {wort(c)}" if c else "")


ZAHL = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?"


def sprechtext(text: str) -> str:
    t = str(text or "")
    # Abkürzungen und Symbole
    for muster, ersatz in ABKUERZUNGEN:
        t = re.sub(muster, ersatz, t)
    t = t.replace("&", " und ").replace("→", " zu ").replace("±", "plus minus ").replace("_", " ")
    t = re.sub(r"\s*[–—]\s*", ", ", t)
    # Beträge: „1.234,56 €“, „€ 1.234“, „1234 EUR“
    t = re.sub(rf"(?:€|EUR)\s?(-?(?:{ZAHL}))", lambda m: euro(_zahl(m.group(1))), t)
    t = re.sub(rf"(-?(?:{ZAHL}))\s?(?:€|EUR\b|Euro\b)", lambda m: euro(_zahl(m.group(1))), t)
    # Prozent
    t = re.sub(rf"({ZAHL})\s?(?:%|Prozent\b)", lambda m: f"{zahl_wort(_zahl(m.group(1)))} Prozent", t)
    # Datum: 17.11.2026 / 17.11. / 2026-11-17 — nach „am/vom/zum/seit dem“ im Dativ
    def datum(tag: int, monat: int, jahr: int | None, vor: str) -> str:
        if not (1 <= tag <= 31 and 1 <= monat <= 12):
            return None
        o = wort(tag, "ordinal")                       # „siebzehnte“
        o = o + ("n" if re.search(r"\b(am|vom|zum|beim|seit dem|bis zum|ab dem|dem)\s*$", vor, re.I) else "r")
        return f"{o} {MONATE[monat - 1]}" + (f" {wort(jahr, 'year')}" if jahr else "")

    def iso(m):
        r = datum(int(m.group(3)), int(m.group(2)), int(m.group(1)), t[max(0, m.start() - 12):m.start()])
        return r or m.group(0)
    t = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", iso, t)

    def de(m):
        j = m.group(3)
        jahr = (int(j) + 2000 if len(j) == 2 else int(j)) if j else None
        r = datum(int(m.group(1)), int(m.group(2)), jahr, t[max(0, m.start() - 12):m.start()])
        return r or m.group(0)
    t = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2}(?!\d))?(?!\d)", de, t)
    # Uhrzeit: 14:10 (Uhr) → „vierzehn Uhr zehn“, 14:00 → „vierzehn Uhr“
    def uhr(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59:
            return m.group(0)
        return f"{wort(h)} Uhr" + (f" {wort(mi)}" if mi else "")
    t = re.sub(r"\b(\d{1,2}):(\d{2})(?::\d{2})?(?:\s?Uhr\b)?", uhr, t)
    # Kennungen mit Buchstaben und Ziffern (M-0014, BE22600379, KN 1175): Ziffern einzeln
    t = re.sub(r"\b([A-Za-zÄÖÜäöü]+[-/]?)(\d{3,})\b", lambda m: f"{m.group(1).rstrip('-/')} {' '.join(wort(int(d)) for d in m.group(2))}", t)
    # Nummern mit führender Null (Belegnummern, „074051“): Ziffer für Ziffer
    t = re.sub(r"(?<![\w.,])0\d+(?![\w.,])", lambda m: " ".join(wort(int(d)) for d in m.group(0)), t)
    # Zahl + Einheit
    einheit = "|".join(re.escape(e) for e in sorted(EINHEITEN, key=len, reverse=True))
    t = re.sub(rf"({ZAHL})\s?({einheit})(?![A-Za-zÄÖÜäöü])", lambda m: f"{mengen_wort(_zahl(m.group(1)))} {EINHEITEN[m.group(2)]}", t)
    # (erst nach Beträgen und Kennungen — „EUR“ und „BE2260…“ brauchen die Großbuchstaben noch) Schiffs- und Firmenkürzel: „MS-STUTTGART“ → „M S Stuttgart“; Wörter in Großbuchstaben normal schreiben
    t = re.sub(r"\b([A-ZÄÖÜ]{2,3})-(?=[A-ZÄÖÜ(])", lambda m: " ".join(m.group(1)) + " ", t)
    t = re.sub(r"\b[A-ZÄÖÜ]{4,}\b", lambda m: m.group(0).capitalize(), t)
    t = re.sub(r"\b[A-ZÄÖÜ]{2,3}\b", lambda m: " ".join(m.group(0)), t)
    # Übrige Zahlen; „1 Meldung“ → „eine Meldung“, „1 Schiff“ → „ein Schiff“
    def zahl(m):
        x = _zahl(m.group(1)); folgt = m.group(2) or ""
        if x == 1 and folgt:
            return ("eine " if WEIBLICH.search(folgt) else "ein ") + folgt
        return f"{mengen_wort(x)}{' ' + folgt if folgt else ''}"
    t = re.sub(rf"(?<![\w.,])(-?(?:{ZAHL}))(?![\w]|[.,]\d)(?:\s([A-Za-zÄÖÜäöüß]+))?", zahl, t)   # nicht in „0.1.13“
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def mengen_wort(x: float) -> str:
    return gerundet(x) if abs(x) >= 1e5 else zahl_wort(x)
