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


def test_llama_ausgabe_vorabversion_und_tar(tmp_path):
    """llama.cpp: „neueste“ Version ohne Dateien, Builds als Vorabversion mit .tar.gz (Stand 2026-11-17)."""
    import io
    import tarfile
    from kai_ki.engine import ausgabe_waehlen, entpacken
    rels = [{"tag_name": "b12474", "assets": []},
            {"tag_name": "b12473", "assets": [{"name": "llama-b12473-bin-macos-x64.tar.gz", "browser_download_url": "x64"},
                                              {"name": "llama-b12473-bin-macos-arm64.tar.gz", "browser_download_url": "arm"}]}]
    assert ausgabe_waehlen(rels) == ("b12473", "arm")
    assert ausgabe_waehlen([{"tag_name": "b1", "assets": [{"name": "llama-b1-bin-macos-arm64.zip", "browser_download_url": "z"}]}]) == ("b1", "z")
    assert ausgabe_waehlen([{"tag_name": "v1.0.0", "assets": []}]) is None
    puf = io.BytesIO()
    with tarfile.open(fileobj=puf, mode="w:gz") as t:
        inhalt = b"#!/bin/sh\n"
        ti = tarfile.TarInfo("llama-b12473/llama-server"); ti.size = len(inhalt); ti.mode = 0o755
        t.addfile(ti, io.BytesIO(inhalt))
        li = tarfile.TarInfo("llama-b12473/libggml.dylib"); li.type = tarfile.SYMTYPE; li.linkname = "libggml.1.dylib"
        t.addfile(li)
    entpacken(puf.getvalue(), "arm.tar.gz", tmp_path)
    assert (tmp_path / "llama-b12473" / "llama-server").is_file()
    assert (tmp_path / "llama-b12473" / "libggml.dylib").is_symlink()


def test_ladestand_text():
    from kai_ki.engine import ladestand
    assert ladestand(2_300_000_000, 5_800_000_000, True, 60) == ("Download 2,3 von ca. 5,8 GB (39 %)", 39)
    assert ladestand(5_900_000_000, 5_800_000_000, False, 600) == ("Modell wird in den Arbeitsspeicher geladen …", 99)
    assert ladestand(0, 5_800_000_000, False, 5)[0] == "Modell wird vorbereitet …"
    assert ladestand(0, 5_800_000_000, False, 60)[0].startswith("Modell wird in den Arbeitsspeicher")   # schon geladen


def test_modelle_vollstaendig():
    from kai_ki.einstellungen import MODELLE, VORGABE_MODELL
    assert VORGABE_MODELL in MODELLE
    for m in MODELLE.values():
        assert m["hf"] and m["name"] and m["bytes"] > 1e9
    assert MODELLE["qwen35-9b"]["denken_aus"] and "--reasoning" in MODELLE["qwen35-9b"]["args"]
