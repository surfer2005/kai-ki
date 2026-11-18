"""Gelerntes (LoRA aus mlx-lm) auf die ORIGINAL-Gewichte des Grundmodells anwenden — statt `mlx_lm fuse`.

Warum nicht `mlx_lm fuse`: mlx-lm rechnet beim Laden einzelne Gewichte für sich um (bei Qwen3.5 z. B. die Normen auf 1 + w)
und speichert sie so; der llama.cpp-Umwandler rechnet dann noch einmal um — das Modell antwortet nur noch Unsinn
(Probelauf 2026-11-18: alle 61 Normen um genau 1 verschoben, dazu fehlte die Zusatzschicht für Mehrwort-Vorhersage).
Hier bleibt alles wie im Original, nur die nachtrainierten Matrizen bekommen ihren Anteil:  W' = W + scale · Bᵀ·Aᵀ
(gleiche Rechnung wie `LoRALinear.fuse` in mlx-lm). Ein 4-Bit-Grundmodell (QLoRA) wird dabei auf die vollen Gewichte gerechnet.

Aufruf (Umgebung venv-gguf, braucht torch + safetensors):
  python zusammenfuehren.py <Original-Ordner (Hugging Face)> <gelerntes/> <Zielordner>
"""
import json
import shutil
import sys
from pathlib import Path


def hf_name(mlx_modul: str) -> str:
    """mlx-lm-Modulname → Name im Original: language_model.model.layers.N.x → model.language_model.layers.N.x.weight"""
    if mlx_modul.startswith("language_model.model."):
        return "model.language_model." + mlx_modul[len("language_model.model."):] + ".weight"
    if mlx_modul.startswith("model."):
        return mlx_modul + ".weight"          # reine Textmodelle (ohne Bildteil) heißen schon im Original so
    return mlx_modul + ".weight"


def deltas_lesen(adapter: Path):
    """{Original-Name: (lora_a, lora_b)} + scale aus adapters.safetensors / adapter_config.json."""
    from safetensors.numpy import load_file
    cfg = json.loads((adapter / "adapter_config.json").read_text("utf-8"))
    if cfg.get("fine_tune_type", "lora") != "lora":
        raise SystemExit(f"Nur LoRA wird zusammengeführt, nicht {cfg.get('fine_tune_type')}")
    scale = float((cfg.get("lora_parameters") or {}).get("scale", 20.0))
    t = load_file(str(adapter / "adapters.safetensors"))
    paare = {}
    for k in t:
        if k.endswith(".lora_a"):
            modul = k[: -len(".lora_a")]
            if modul + ".lora_b" not in t:
                raise SystemExit(f"lora_b fehlt zu {modul}")
            paare[hf_name(modul)] = (t[k], t[modul + ".lora_b"])
    return paare, scale


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    import torch
    from safetensors.torch import load_file, save_file
    basis, adapter, ziel = (Path(p) for p in sys.argv[1:])
    paare, scale = deltas_lesen(adapter)
    ziel.mkdir(parents=True, exist_ok=True)
    for f in basis.iterdir():                 # Einstellungen, Tokenizer, Vorlagen unverändert übernehmen
        if f.is_file() and not f.name.endswith(".safetensors"):
            shutil.copy2(f, ziel / f.name)
    offen = dict(paare)
    for teil in sorted(basis.glob("*.safetensors")):
        gewichte = load_file(str(teil))
        for name in [n for n in gewichte if n in offen]:
            a, b = offen.pop(name)
            w = gewichte[name]
            delta = scale * (torch.from_numpy(b.astype("float32")).T @ torch.from_numpy(a.astype("float32")).T)
            if tuple(delta.shape) != tuple(w.shape):
                raise SystemExit(f"Form passt nicht bei {name}: Original {tuple(w.shape)}, Gelerntes {tuple(delta.shape)}")
            gewichte[name] = (w.float() + delta).to(w.dtype)
        save_file(gewichte, str(ziel / teil.name), metadata={"format": "pt"})
        print(f"  {teil.name}: fertig", flush=True)
    if offen:
        raise SystemExit(f"{len(offen)} nachtrainierte Matrizen im Original nicht gefunden, z. B. {next(iter(offen))}")
    print(f"  {len(paare)} Matrizen angepasst (scale {scale}), alles andere wie im Original", flush=True)


if __name__ == "__main__":
    main()
