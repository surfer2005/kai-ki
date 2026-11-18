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


def test_fremdes_rechenprogramm_nur_llama():
    import os
    from kai_ki.engine import _ist_llama, _laeuft
    assert _laeuft(os.getpid())
    assert not _ist_llama(os.getpid())          # die eigene App (python) wird nie beendet
    assert not _laeuft(999999999)


def test_saetze_fuer_den_sprecher():
    from kai_ki.sprecher import saetze
    assert saetze("Das ist KAI. Ein System für die ganze Flotte.") == ["Das ist KAI. Ein System für die ganze Flotte."]
    lang = "Bordbuch und Meldungen an Bord, " * 15 + "fertig."
    teile = saetze(lang)
    assert all(len(t) <= 260 for t in teile) and "".join(teile).replace(" ", "") == lang.replace(" ", "")
    assert saetze("") == []


def test_antwort_lesen_ueberspringt_fremde_zeilen():
    import io
    from kai_ki.sprecher import antwort_lesen
    strom = io.StringIO('loaded PerthNet\n{"bereit": true}\n')
    assert antwort_lesen(strom) == {"bereit": True}
    assert antwort_lesen(strom) is None


def test_dienst_ist_gueltiges_python():
    from kai_ki.sprecher import DIENST
    compile(DIENST, "dienst.py", "exec")


def test_angefangener_download_zaehlt_als_geladen(tmp_path):
    from kai_ki.engine import ordner_bytes, teil_bytes
    (tmp_path / "anderes-modell.gguf").write_bytes(b"x" * 100)
    (tmp_path / "neu.gguf.downloadInProgress").write_bytes(b"y" * 40)
    assert teil_bytes(tmp_path) == 40
    assert ordner_bytes(tmp_path) - teil_bytes(tmp_path) == 100   # Anfangswert: nur das fertige andere Modell


def test_chat_nachrichten_bilder_und_texterkennung():
    from kai_ki.engine import chat_nachrichten
    n = chat_nachrichten([
        {"role": "system", "content": "Du bist KAI."},
        {"role": "user", "content": "Was steht hier?", "seiten": [{"data": "QUJD", "mime": "image/png"}]},
        {"role": "assistant", "content": "Ein Lieferschein."},
    ], bild=lambda s: b"PNG", ocr=lambda png: "Relay GmbH")
    assert n[0] == {"role": "system", "content": "Du bist KAI."}
    teile = n[1]["content"]
    assert teile[0]["image_url"]["url"] == "data:image/png;base64,UE5H"
    assert teile[1]["type"] == "text" and teile[1]["text"].startswith("Was steht hier?") and "Relay GmbH" in teile[1]["text"]
    assert n[2] == {"role": "assistant", "content": "Ein Lieferschein."}


def test_hoerer_dienst_ist_gueltiges_python():
    import ast
    from kai_ki.hoerer import DIENST, PAKET, MODELL
    ast.parse(DIENST)
    assert PAKET.startswith("mlx-whisper==") and MODELL.startswith("mlx-community/whisper")


def test_gespraech_in_der_app():
    from datetime import date
    from kai_ki.gespraech import system_text, verlauf_markdown
    assert "Dienstag, der 17.11.2026" in system_text(date(2026, 11, 17))
    md = verlauf_markdown([{"role": "user", "content": "Hallo", "anhang": "ls.pdf"}, {"role": "assistant", "content": "Hallo!"}], laufend="Ich")
    assert md.startswith("**Du:** 📎 ls.pdf") and "**KAI KI:**\n\nHallo!" in md and md.endswith("Ich ▍")


def test_mikrofon_aufnahme_wird_wav():
    import array, io, wave
    from kai_ki.gespraech import wav_aus_pcm
    stereo_float = array.array("f", [0.5, -0.5, 1.5, 1.5]).tobytes()         # 2 Frames, 2 Kanäle, einer übersteuert
    w = wave.open(io.BytesIO(wav_aus_pcm(stereo_float, 48000, 2, True)))
    assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 48000, 2)
    assert array.array("h", w.readframes(2)).tolist() == [0, 32767]
    mono = wave.open(io.BytesIO(wav_aus_pcm(array.array("h", [100, -100, 5]).tobytes(), 16000)))
    assert mono.getnframes() == 3


def test_vorlese_text_ohne_markdown():
    from kai_ki.gespraech import vorlese_text
    assert vorlese_text("Es sind **2** Meldungen.\n\n| Schiff | Anzahl |\n|---|---|\n| MS-LINDAU | 2 |\n- Punkt") == "Es sind 2 Meldungen. Schiff, Anzahl. MS-LINDAU, 2. Punkt"
    assert len(vorlese_text("Satz. " * 400)) <= 1500


def test_abgeloester_ablauf_meldet_nichts_mehr():
    from kai_ki.arbeiter import Arbeiter
    gesehen = []
    a = Arbeiter(kai=None, engine=None, status=gesehen.append, melden=gesehen.append)
    a.status("bereit"); a.halt.set(); a.status("fehler"); a.melden("Modell konnte nicht starten")
    assert gesehen == ["bereit"]


def test_wiederholung_nur_ohne_anhalten(monkeypatch):
    from kai_ki import engine as E
    e = E.Engine("qwen35-9b"); versuche = []
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    def scheitert(w, f):
        versuche.append(1)
        raise E.EngineFehler("Rechenprogramm beendet")
    monkeypatch.setattr(e, "_starten", scheitert)
    try:
        e.starten(versuche=3)
    except E.EngineFehler:
        pass
    assert len(versuche) == 3                     # Netzabbruch: neue Versuche
    versuche.clear()
    def angehalten(w, f):
        versuche.append(1); e.angehalten = True    # Nutzer hält während des Ladens an
        raise E.EngineFehler("Rechenprogramm beendet")
    monkeypatch.setattr(e, "_starten", angehalten)
    try:
        e.starten(versuche=3)
    except E.EngineFehler:
        pass
    assert len(versuche) == 1


def test_sprechtext_zahlen_datum_uhrzeit_einheiten():
    from kai_ki.sprechtext import sprechtext as s
    assert s("Umsatz 24.099.694,29 €") == "Umsatz rund vierundzwanzig Komma eins Millionen Euro"
    assert s("Kosten: 920,50 €") == "Kosten: neunhundertzwanzig Euro fünfzig"
    assert s("1 €") == "ein Euro"
    assert s("am 17.11.2026") == "am siebzehnten November zweitausendsechsundzwanzig"
    assert s("Stand 2026-11-17") == "Stand siebzehnter November zweitausendsechsundzwanzig"
    assert s("Abfahrt 14:10 Uhr") == "Abfahrt vierzehn Uhr zehn"
    assert s("30 % mehr, 115 km") == "dreißig Prozent mehr, einhundertfünfzehn Kilometer"
    assert s("MS-STUTTGART und KS-FRIDOLIN") == "M S Stuttgart und K S Fridolin"
    assert s("1 Meldung, 1 Schiff, 442 Meldungen") == "eine Meldung, ein Schiff, vierhundertzweiundvierzig Meldungen"
    assert s("412.134 Personen") == "rund vierhundertzwölftausend Personen"
    assert s("z. B. ca. 3,5 h") == "zum Beispiel circa drei Komma fünf Stunden"
    assert s("Meldung M-0014") == "Meldung M null null eins vier"
    assert s("Das ist KAI der BSB.") == "Das ist Kai der B S B."


def test_sprechtext_grenzfaelle():
    from kai_ki.sprechtext import sprechtext as s
    assert s("vom 11.10.2026, Abfahrt 07:25 – 13 Fahrten") == "vom elften Oktober zweitausendsechsundzwanzig, Abfahrt sieben Uhr fünfundzwanzig, dreizehn Fahrten"
    assert s("Version 0.1.13") == "Version 0.1.13"
    assert s("Beleg 074051") == "Beleg null sieben vier null fünf eins"


def test_mehrere_verbindungen():
    from kai_ki.einstellungen import bezeichnung, verbindungen
    alt = {"kai_url": "https://kai-bsb.de/test", "token": "t1", "name": "MacBook Peter"}
    assert verbindungen(alt) == [{"kai_url": "https://kai-bsb.de/test", "token": "t1", "name": "MacBook Peter"}]
    assert verbindungen({"verbindungen": [{"kai_url": "https://kai-bsb.de", "token": "t2"}, {"kai_url": "x"}]}) == [{"kai_url": "https://kai-bsb.de", "token": "t2"}]
    assert (bezeichnung("https://kai-bsb.de/test/"), bezeichnung("https://kai-bsb.de"), bezeichnung("http://10.0.8.18:8083")) == ("Test", "Produktion", "10.0.8.18:8083")


def test_adresse_ordnen():
    """Ohne https:// kam nur „MissingSchema“ (Peter 2026-11-18)."""
    from kai_ki.kai import adresse_ordnen
    assert adresse_ordnen("kai-bsb.de") == "https://kai-bsb.de"
    assert adresse_ordnen(" kai-bsb.de/test/ ") == "https://kai-bsb.de/test"
    assert adresse_ordnen("https://kai-bsb.de/") == "https://kai-bsb.de"
    assert adresse_ordnen("http://localhost:8281") == "http://localhost:8281"
    assert adresse_ordnen("") == ""
