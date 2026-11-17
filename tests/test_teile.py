"""Reine Teile der App (ohne Mac/Modell testbar)."""
import json

from kai_ki.arbeiter import aufgabe_mit_texterkennung
from kai_ki.engine import antwort_ergaenzen
from kai_ki.seite import zeilen_ordnen


def test_zeilen_ordnen_links_nach_rechts_oben_nach_unten():
    stuecke = [(0.6, 0.100, 0.02, "Lieferschein-Nr."), (0.1, 0.101, 0.02, "Conrad Electronic SE"), (0.1, 0.20, 0.02, "BE12600541")]
    assert zeilen_ordnen(stuecke) == "Conrad Electronic SE  Lieferschein-Nr.\nBE12600541"


def test_volltext_aus_texterkennung():
    t = antwort_ergaenzen('{"lieferant":"Relay GmbH","volltext":null}', "Relay GmbH\nLIEFERSCHEIN")
    assert json.loads(t) == {"lieferant": "Relay GmbH", "volltext": "Relay GmbH\nLIEFERSCHEIN"}
    assert antwort_ergaenzen('{"volltext":"vom Modell"}', "ocr") == '{"volltext": "vom Modell"}'
    assert antwort_ergaenzen("kein json", "ocr") == "kein json"


def test_aufgabe_mit_texterkennung():
    assert aufgabe_mit_texterkennung("Lies", "") == "Lies"
    assert "Texterkennung dieser Seite" in aufgabe_mit_texterkennung("Lies", "SWK000323L")
