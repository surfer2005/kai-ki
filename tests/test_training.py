"""Reine Teile des Nachtrainierens (training/trainieren.py) — ohne Modell und ohne mlx testbar."""
import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location("trainieren", Path(__file__).parent.parent / "training" / "trainieren.py")
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)


def _zeile(*paare):
    return json.dumps({"messages": [{"role": r, "content": c} for r, c in paare]}, ensure_ascii=False)


def test_beispiele_pruefen():
    zeilen = [
        _zeile(("system", "S"), ("user", "Wer hat Platz 101?"), ("assistant", "ABFRAGE {\"werkzeug\":\"liegeplatz\"}")),
        "",                                                     # Leerzeile zählt nicht
        "kein json",
        _zeile(("system", "S"), ("user", "Frage")),             # keine Antwort am Ende
        _zeile(("system", "S"), ("user", ""), ("assistant", "x")),   # leere Frage
        json.dumps({"text": "anderes Format"}),
    ]
    gut, fehler = tr.beispiele_pruefen(zeilen)
    assert len(gut) == 1 and gut[0]["messages"][2]["role"] == "assistant"
    assert len(fehler) == 4 and fehler[0].startswith("Zeile 3")


def test_aufteilen_und_schritte():
    train, kontrolle = tr.aufteilen(list(range(50)))
    assert len(kontrolle) == 5 and len(train) == 45 and not set(train) & set(kontrolle)
    assert tr.aufteilen(list(range(50))) == (train, kontrolle)         # gleiche Mischung bei gleichem Startwert
    t, k = tr.aufteilen([1, 2]); assert len(t) == 1 and len(k) == 1          # kleinster Fall: je eines
    assert tr.schritte(20) == 200 and tr.schritte(300) == 900 and tr.schritte(5000) == 1500


def test_basis_und_fehlerwert():
    assert tr.basis_waehlen(36) == tr.BASIS_GROSS
    assert tr.basis_waehlen(16) == tr.BASIS_KLEIN
    assert tr.basis_waehlen(16, "Qwen/Qwen3.5-0.8B") == "Qwen/Qwen3.5-0.8B"
    assert tr.original_von(tr.BASIS_KLEIN) == tr.BASIS_GROSS
    assert tr.original_von("mlx-community/Qwen3.5-9B-bf16") == "Qwen/Qwen3.5-9B"
    assert tr.original_von("Qwen/Qwen3.5-0.8B") == "Qwen/Qwen3.5-0.8B"
    assert tr.verlust_lesen("Calculating loss...\nTest loss 1.234, Test ppl 3.435.") == 1.234
    assert tr.verlust_lesen("nichts") is None


def test_zusammenfuehren_namen():
    """mlx-lm-Modulnamen → Namen in den Original-Gewichten (Qwen3.5 mit Bildteil)."""
    spec = importlib.util.spec_from_file_location("zf", Path(__file__).parent.parent / "training" / "zusammenfuehren.py")
    zf = importlib.util.module_from_spec(spec); spec.loader.exec_module(zf)
    assert zf.hf_name("language_model.model.layers.20.linear_attn.in_proj_qkv") == "model.language_model.layers.20.linear_attn.in_proj_qkv.weight"
    assert zf.hf_name("model.layers.3.self_attn.q_proj") == "model.layers.3.self_attn.q_proj.weight"


def test_app_fortschritt_aus_zeilen():
    """Reiter „Training“: Fortschritt aus den Zeilen von trainieren.py und mlx-lm 0.32 (mit und ohne Farbcodes)."""
    from kai_ki import training as t
    st = {}
    for z in ["\n▶ 1/6 Trainingsdatei prüfen",
              "  300 zum Lernen, 33 zur Kontrolle · Grundmodell Qwen/Qwen3.5-9B · 900 Schritte · Arbeitsspeicher 36 GB · Ordner /x",
              "▶ 2/6 Kontrolle vorher (Grundmodell ohne Training)", "  Fehlerwert vorher: 3.052",
              "▶ 3/6 Training (das dauert — je nach Menge 20 bis 90 Minuten)",
              "  \x1b[38;5;244m 450\x1b[0m    \x1b[1;32m1.234 ▼\x1b[0m    \x1b[1m  850\x1b[0m    \x1b[38;5;244m 96.0k\x1b[0m"]:
        t.zeile_auswerten(z, st)
    assert st == {"schritt": 3, "iters": 900, "vorher": 3.052, "iter": 450}
    assert t.prozent(st) == 10 + 37 and t.schritt_text(st) == "Schritt 3 von 6: Training — 450 von 900"
    t.zeile_auswerten("   500    val 1.300    2.10s", st)
    assert st["iter"] == 500
    t.zeile_auswerten("  Fehlerwert nachher: 1.644 (vorher 3.052) — kleiner ist besser", st)
    t.zeile_auswerten("✔ Fertig. Nächste Schritte:", st)
    assert st["nachher"] == 1.644 and t.prozent(st) == 100 and t.schritt_text(st) == "Fertig"
    f = t.zeile_auswerten("✖ Schritt fehlgeschlagen (Code 1).", {"schritt": 5})
    assert f["fehler"].startswith("Schritt fehlgeschlagen") and t.prozent(f) == 92
    assert t.schritt_text({"schritt": 2}).endswith("(beim ersten Mal ca. 19 GB Download)")


def test_app_daten_und_geraet(tmp_path, monkeypatch):
    import io
    import tarfile
    from kai_ki import training as t
    monkeypatch.setattr(t, "DATEN", tmp_path / "daten")
    (tmp_path / "daten").mkdir(); (tmp_path / "daten" / "alt.jsonl").write_text("x")
    datei, n = t.daten_ablegen({"zeilen": ['{"messages":[]}', '{"messages":[1]}', ""]}, "Test")
    assert n == 2 and datei.name.startswith("kai-ki-training-Test-") and oct(datei.stat().st_mode)[-3:] == "600"
    assert [p.name for p in (tmp_path / "daten").iterdir()] == [datei.name]          # nur der letzte Stand bleibt
    assert "voller Genauigkeit" in t.geraet_text(36, 200) and "4-Bit" in t.geraet_text(16, 200)
    assert "zu wenig" in t.geraet_text(8, 200) and "60 GB" in t.geraet_text(36, 20)
    # GitHub-Quellarchiv ohne obersten Ordner entpacken
    puffer = io.BytesIO()
    with tarfile.open(fileobj=puffer, mode="w:gz") as tar:
        inhalt = b"print(1)"; info = tarfile.TarInfo("llama.cpp-b1/convert_hf_to_gguf.py"); info.size = len(inhalt)
        tar.addfile(info, io.BytesIO(inhalt))
    t._entpacken_ohne_obersten(puffer.getvalue(), tmp_path / "llama")
    assert (tmp_path / "llama" / "convert_hf_to_gguf.py").read_bytes() == b"print(1)"
    assert (t.skript_ordner() / "trainieren.py").exists() and (t.skript_ordner() / "zusammenfuehren.py").exists()
