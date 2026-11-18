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
