"""Reiter „Aufräumen“ ab 0.1.21 — „Was aufräumen?“ im Startordner, vorhandene Ablage, frühere Läufe, Suche/Filter und
Kopf-Häkchen. Beispiel wie bei Peter: Dokumente mit „unaufgeräumt 1–4“, zuerst 1 und 2 angehakt, 3 und 4 erst später."""
import hashlib
import json
import os
from pathlib import Path

from kai_ki import aufraeumen as af

U1, U2, U3, U4 = "unaufgeräumt 1", "unaufgeräumt 2", "unaufgeräumt 3", "unaufgeräumt 4"


def _datei(p: Path, inhalt: str = "x", zeit: float | None = None) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(inhalt)
    if zeit is not None:
        os.utime(p, (zeit, zeit))
    return p


def _bestand(wurzel: Path) -> dict:
    return {p.relative_to(wurzel).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in wurzel.rglob("*") if p.is_file()}


def _dokumente(tmp_path: Path) -> Path:
    d = tmp_path / "Dokumente"
    _datei(d / "Rechnungen" / "2026" / "2026-09 Telekom Rechnung.pdf", "Telekom September", 1_790_000_000)
    _datei(d / "Rechnungen" / "2026" / "2026-08 Vodafone Rechnung.pdf", "Vodafone August", 1_780_000_000)
    _datei(d / "Versicherungen" / "Allianz Boot Police.pdf", "Versicherungsschein Allianz Boot")
    _datei(d / "Boot" / "Liegeplatz Vertrag.pdf", "Liegeplatz")
    _datei(d / "lose Notiz.txt", "lose im Startordner")
    _datei(d / U1 / "scan1.txt", "Telekom Deutschland GmbH Rechnung Oktober 2026")
    _datei(d / U1 / "scan2.txt", "Versicherungsschein Allianz Boot")                 # gleich wie in der Ablage
    _datei(d / U1 / "Unter" / "zettel.txt", "Einkaufszettel")
    _datei(d / U2 / "foto.txt", "Urlaubsfoto Lindau")
    _datei(d / U3 / "alt.txt", "noch nicht dran")
    _datei(d / U4 / "alt4.txt", "auch noch nicht dran")
    return d


class KI:
    """Gespielte KI: antwortet nach dem Dateinamen, merkt sich jede Frage."""

    def __init__(self, antworten=None):
        self.fragen = []
        self.antworten = {"scan1.txt": ("rechnungen/2026", "2026-10 Telekom Rechnung"), "zettel.txt": (U3 + "/Zettel", "Zettel"),
                          "foto.txt": ("Fotos", "Lindau Urlaub"), "alt.txt": ("Fotos", "Altes Foto"), **(antworten or {})}

    def __call__(self, system, text):
        self.fragen.append(text)
        name = text.split("Datei: ", 1)[1].split("\n", 1)[0]
        o, n = self.antworten.get(name, (None, None))
        return json.dumps({"ordner": o, "name": n, "grund": "Test"})


def _lauf(d, ki, auswahl, **kw):
    return af.Vorschlagslauf(d, ki, auswahl=auswahl, lesen=lambda p, s, z, o: p.read_text()[:z], **kw).laufen()


# ---------------------------------------------------------------- Auswahl prüfen und merken

def test_auswahl_ordnen():
    a = af.auswahl_ordnen({"lose": 1, "ordner": [U1, U1 + "/Unter", "../x", "/abs", U2, U2],
                           "auslassen": [U3, U1 + "/Unter", "", "a/../b"]})
    assert a == {"lose": True, "ordner": [U1, U2], "auslassen": [U3]}
    assert af.auswahl_ordnen(None) == {"lose": False, "ordner": [], "auslassen": []}
    assert af.ganzer_ordner({}) and af.ganzer_ordner({"auslassen": [U3]}) and not af.ganzer_ordner({"lose": True})


def test_auswahl_je_startordner_gemerkt(tmp_path):
    d, e = tmp_path / "Dokumente", tmp_path / "Schreibtisch"
    d.mkdir(); e.mkdir()
    prot = tmp_path / "p"
    assert af.auswahl_laden(prot, d) == {"lose": False, "ordner": [], "auslassen": []}
    af.auswahl_speichern(prot, d, {"ordner": [U1, U2], "auslassen": [U3]})
    af.auswahl_speichern(prot, e, {"lose": True})
    assert af.auswahl_laden(prot, d) == {"lose": False, "ordner": [U1, U2], "auslassen": [U3]}
    assert af.auswahl_laden(prot, str(d) + "/") == af.auswahl_laden(prot, d)       # gleicher Ordner, andere Schreibweise
    assert af.auswahl_laden(prot, e)["lose"]


# ---------------------------------------------------------------- Vorschlag mit vorhandener Ablage

def test_nur_angehakte_ordner_bekommen_vorschlaege(tmp_path):
    d = _dokumente(tmp_path)
    vorher = _bestand(d)
    ki = KI()
    erg = _lauf(d, ki, {"ordner": [U1, U2]})
    e = {x["pfad"]: x for x in erg["eintraege"]}
    assert sorted(e) == [f"{U1}/Unter/zettel.txt", f"{U1}/scan1.txt", f"{U1}/scan2.txt", f"{U2}/foto.txt"]
    assert _bestand(d) == vorher                                                         # Vorschlag verändert nichts
    # die KI sieht die Ablage (mit Beispielnamen), aber nie die aufzuräumenden Ordner
    f = ki.fragen[0]
    assert "in der vorhandenen Ablage" in f and "Rechnungen/2026 — 2 Dateien, z. B.: 2026-09 Telekom Rechnung.pdf; " in f
    assert "Versicherungen" in f and U3 in f and U4 in f
    assert U1 not in f.split("Datei:")[0] and U2 not in f.split("Datei:")[0]
    # Schreibweise vorhandener Ordner übernommen
    assert e[f"{U1}/scan1.txt"]["ordner"] == "Rechnungen/2026" and e[f"{U1}/scan1.txt"]["status"] == "vorschlag"
    # Doppelt gegen die Ablage: Ordner „Doppelt“ (ohne „?“), die Zeile nennt das Original
    s2 = e[f"{U1}/scan2.txt"]
    assert s2["status"] == "doppelt" and s2["ordner"] == "Doppelt" and s2["verschieben"]
    assert s2["gleich_wie"] == "Versicherungen/Allianz Boot Police.pdf" and "liegt schon in der Ablage" in s2["grund"]
    assert len(ki.fragen) == 3                                                           # die Kopie fragt die KI nicht
    # „unaufgeräumt 3“ ist hier noch Ablage → erlaubtes Ziel; neue Ordner werden erkannt
    assert e[f"{U1}/Unter/zettel.txt"]["ordner"] == f"{U3}/Zettel"
    assert af.ordner_liste(erg["eintraege"], erg["vorhanden"]) == [("Doppelt", 1, True), ("Fotos", 1, True),
                                                                   ("Rechnungen/2026", 1, False), (f"{U3}/Zettel", 1, True)]


def test_kein_ziel_und_aufzuraeumende_nie_als_ziel(tmp_path):
    d = _dokumente(tmp_path)
    ki = KI({"foto.txt": (U1 + "/Bilder", "x")})                                    # schlägt einen aufzuräumenden Ordner vor
    erg = _lauf(d, ki, {"ordner": [U1, U2], "auslassen": [U3, U4]})
    e = {x["pfad"]: x for x in erg["eintraege"]}
    for pfad in (f"{U1}/Unter/zettel.txt", f"{U2}/foto.txt"):
        assert e[pfad]["status"] == "unklar" and not e[pfad]["verschieben"] and not e[pfad]["ordner"]
        assert "KI schlug" in e[pfad]["grund"]
    vor_datei = ki.fragen[0].split("Datei:")[0]
    assert U3 not in vor_datei and U4 not in vor_datei                                  # „Kein Ziel“: die KI sieht sie gar nicht
    assert af.ziel_gesperrt(f"{U3}/x", [U3]) and af.ziel_gesperrt(U1.upper(), [U1]) and not af.ziel_gesperrt("Fotos", [U1])


def test_lose_dateien_und_hoechstzahl(tmp_path):
    d = _dokumente(tmp_path)
    erg = _lauf(d, KI(), {"lose": True})
    assert [x["pfad"] for x in erg["eintraege"]] == ["lose Notiz.txt"] and not erg["zu_viele"]
    # Höchstzahl gilt nur für die angehakten Ordner (die Ablage zählt nicht mit)
    erg = _lauf(d, KI(), {"ordner": [U1, U2]}, max_dateien=2)
    assert len(erg["eintraege"]) == 2 and erg["zu_viele"]


def test_anderes_laufwerk_wird_ausgelassen(tmp_path, monkeypatch):
    d = _dokumente(tmp_path)
    echt = af._geraet
    monkeypatch.setattr(af, "_geraet", lambda p: 999 if str(p).endswith(U2) else echt(p))
    meldungen: list = []
    dateien, _ = af.quellen_sammeln(d, {"ordner": [U1, U2]}, meldungen=meldungen)
    assert all(x["pfad"].startswith(U1) for x in dateien) and any("anderen Laufwerk" in m and U2 in m for m in meldungen)


def test_ganzer_ordner_wie_bisher(tmp_path):
    d = _dokumente(tmp_path)
    ki = KI()
    erg = _lauf(d, ki, {})
    assert len(erg["eintraege"]) == len(_bestand(d)) and "im aufgeräumten Ordner" in ki.fragen[0]


# ---------------------------------------------------------------- Ausführen, frühere Läufe, Rückgängig je Lauf

def test_zwei_laeufe_nacheinander(tmp_path):
    d, prot = _dokumente(tmp_path), tmp_path / "protokoll"
    vorher = _bestand(d)
    auswahl = {"ordner": [U1, U2], "auslassen": [U3, U4]}
    erg = _lauf(d, KI({"zettel.txt": ("Notizen", "Einkauf")}), auswahl)
    a = af.ausfuehren(d, erg["eintraege"], prot, auswahl=auswahl)
    assert a["anzahl"] == 4 and not a["fehler"]
    assert (d / "Doppelt" / "scan2.txt").exists() and (d / "Fotos" / "foto.txt").exists()
    # leere Quellordner bleiben stehen und werden genannt (nie gelöscht)
    assert a["leere_ordner"] == [U1, U2] and (d / U1 / "Unter").is_dir() and (d / U2).is_dir()
    lauf1 = af.laeufe(prot)[0]
    assert lauf1["quellen"] == [U1, U2] and not lauf1["lose"]

    fr = af.fruehere_laeufe(prot, d)
    assert fr["quellen"] == [U1, U2] and "Fotos" in fr["befuellt"] and "Rechnungen/2026" in fr["befuellt"]
    namen = {o["pfad"]: o for o in af.ordner_zur_auswahl(d, "", fr)}
    assert U1 not in namen and U2 not in namen                                          # früher aufgeräumt + leer: nicht mehr angeboten
    assert namen["Fotos"]["frueher_befuellt"] and not namen["Boot"]["frueher_befuellt"] and namen[U3]["dateien"] == 1

    # zweiter Lauf: jetzt „unaufgeräumt 3“; Ordner aus dem ersten Lauf stehen vorn („bevorzugt“)
    ki = KI()
    erg2 = af.Vorschlagslauf(d, ki, auswahl={"ordner": [U3]}, frueher=fr, lesen=lambda p, s, z, o: p.read_text()).laufen()
    f = ki.fragen[0].split("Datei:")[0]
    baum = f.split("Beispielnamen der neuesten Dateien):\n", 1)[1].splitlines()
    assert baum[0] == "Aus früheren Läufen — hierhin bevorzugt einsortieren:"
    trenner = baum.index("Weitere vorhandene Ordner:")
    assert "Fotos — 1 Datei, z. B.: foto.txt" in baum[1:trenner] and any(z.startswith("Boot — ") for z in baum[trenner:])
    assert U1 not in f and U2 not in f                                                   # leere frühere Quellen sind kein Ziel
    assert erg2["eintraege"][0]["ordner"] == "Fotos"
    af.ausfuehren(d, erg2["eintraege"], prot, auswahl={"ordner": [U3]})
    assert (d / "Fotos" / "Altes Foto.txt").exists() is False and (d / "Fotos" / "alt.txt").exists()

    # Rückgängig je Lauf: erst Lauf 2, dann Lauf 1
    af.rueckgaengig(prot)
    assert (d / U3 / "alt.txt").exists() and (d / "Fotos" / "foto.txt").exists()
    af.rueckgaengig(prot)
    assert _bestand(d) == vorher and not (d / "Fotos").exists() and not (d / "Doppelt").exists()


def test_ausfuehren_lehnt_gesperrte_ziele_ab(tmp_path):
    d, prot = _dokumente(tmp_path), tmp_path / "protokoll"
    vorher = _bestand(d)
    eintraege = [{"pfad": f"{U1}/scan1.txt", "ordner": f"{U2}/x", "name": "", "verschieben": True, "umbenennen": False,
                  "status": "hand"},
                 {"pfad": f"{U1}/zettel.txt", "ordner": U4, "name": "", "verschieben": True, "umbenennen": False, "status": "hand"}]
    erg = af.ausfuehren(d, eintraege, prot, auswahl={"ordner": [U1, U2], "auslassen": [U4]})
    assert erg["anzahl"] == 0 and len(erg["fehler"]) == 2 and _bestand(d) == vorher and not list(prot.glob("lauf-*.json"))


def test_alter_vorschlag_aus_0_1_20_laedt(tmp_path):
    d, prot = _dokumente(tmp_path), tmp_path / "protokoll"
    prot.mkdir()
    (prot / "vorschlag.json").write_text(json.dumps({
        "wurzel": str(d), "datum": "2026-11-22T10:00:00", "einstellung": {"seiten": 2},
        "eintraege": [{"pfad": "lose Notiz.txt", "ordner": "Doppelt?", "name": "", "verschieben": True, "umbenennen": False,
                       "status": "doppelt", "grund": "gleicher Inhalt"}]}))
    v = af.vorschlag_laden(prot)
    assert af.auswahl_ordnen(v["einstellung"].get("auswahl")) == {"lose": False, "ordner": [], "auslassen": []}
    assert af.aktion(v["eintraege"][0]) == ("lose Notiz.txt", "Doppelt?/lose Notiz.txt")


# ---------------------------------------------------------------- Suche, Schnellfilter, Kopf-Häkchen

def _liste():
    return [
        {"pfad": f"{U1}/scan1.txt", "ordner": "Rechnungen/2026", "name": "2026-10 Telekom", "status": "vorschlag",
         "verschieben": True, "umbenennen": False, "grund": "Telekom-Rechnung"},
        {"pfad": f"{U1}/scan2.txt", "ordner": "Doppelt", "name": "", "status": "doppelt", "verschieben": True, "umbenennen": False,
         "grund": "gleicher Inhalt", "gleich_wie": "Versicherungen/Allianz Boot Police.pdf"},
        {"pfad": f"{U2}/foto.txt", "ordner": "Fotos", "name": "Lindau Urlaub", "status": "vorschlag", "verschieben": True,
         "umbenennen": True, "grund": "Urlaub"},
        {"pfad": f"{U1}/zettel.txt", "ordner": "", "name": "", "status": "unklar", "verschieben": False, "umbenennen": False,
         "grund": "unsicher"},
        {"pfad": "Boot/Vertrag.pdf", "ordner": "Boot", "name": "", "status": "bleibt", "verschieben": False, "umbenennen": False,
         "grund": ""},
        {"pfad": f"{U2}/kopie.txt", "ordner": "Doppelt", "name": "", "status": "doppelt", "verschieben": True, "umbenennen": False,
         "grund": "gleicher Inhalt", "gleich_wie": f"{U2}/foto.txt"},
    ]


def test_suche_und_schnellfilter():
    e, vorh = _liste(), ["Rechnungen", "Rechnungen/2026", "Boot"]
    assert af.sichtbare(e, "", "alle", vorh) == [0, 1, 2, 3, 4, 5]
    assert af.sichtbare(e, "", "doppelt", vorh) == [1, 5]
    assert af.sichtbare(e, "", "unklar", vorh) == [3]
    assert af.sichtbare(e, "", "bleibt", vorh) == [4]
    assert af.sichtbare(e, "", "neu", vorh) == [1, 2, 5]                                # Doppelt und Fotos gibt es noch nicht
    assert af.sichtbare(e, "telekom") == [0]                                             # neuer Name
    assert af.sichtbare(e, "allianz") == [1]                                             # wo die gleiche Datei liegt
    assert af.sichtbare(e, "unaufgeräumt 2") == [2, 5]                                   # bisheriger Ordner, nicht „…1/scan2“
    assert af.sichtbare(e, "  RECHNUNGEN/2026 ") == [0] and af.sichtbare(e, "URLAUB") == [2]
    assert af.sichtbare(e, "unaufgera\u0308umt 2") == [2, 5]                            # Umlaut zerlegt (ältere Mac-Dateinamen)
    assert af.filter_zaehlen(e, "", vorh) == {"alle": 6, "doppelt": 2, "unklar": 1, "neu": 3, "bleibt": 1}
    assert af.filter_zaehlen(e, "unaufgeräumt 2", vorh) == {"alle": 2, "doppelt": 1, "unklar": 0, "neu": 2, "bleibt": 0}


def test_kopf_haekchen_wirken_nur_auf_sichtbare_zeilen():
    e = _liste()
    alle = af.sichtbare(e)
    assert af.kopf_zustand(e, alle, "verschieben") == "alle"                            # unklar/bleibt zählen nicht mit
    assert af.kopf_zustand(e, alle, "umbenennen") == "teils"
    # Peters Fall: Filter „Doppelt“ → Kopf „Verschieben“ aus → keine Kopie wird angefasst, alles andere bleibt
    doppelt = af.sichtbare(e, "", "doppelt")
    assert af.alle_setzen(e, doppelt, "verschieben", False) == 2
    assert [x["verschieben"] for x in e] == [True, False, True, False, False, False]
    assert af.kopf_zustand(e, doppelt, "verschieben") == "keine" and af.kopf_zustand(e, alle, "verschieben") == "teils"
    # wieder an: unklar (ohne Ordner) und „liegt schon richtig“ bleiben aus
    assert af.alle_setzen(e, alle, "verschieben", True) == 2
    assert [x["verschieben"] for x in e] == [True, True, True, False, False, True]
    # Umbenennen setzen geht nur, wo ein Name vorgeschlagen ist
    af.alle_setzen(e, alle, "umbenennen", True)
    assert [x["umbenennen"] for x in e] == [True, False, True, False, False, False]
    assert af.kopf_zustand(e, af.sichtbare(e, "", "unklar"), "verschieben") == "leer"
    assert af.kopf_zustand(e, [], "umbenennen") == "leer"
