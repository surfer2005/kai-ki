"""KAI KI nachtrainieren („Weg 3“): aus der Trainingsdatei von KAI (Administration → KI → Training) ein eigenes Modell
„KAI angepasst“ machen, das die App wie jedes andere Modell startet.

Ablauf (jeder Schritt meldet sich, bricht mit klarer Meldung ab):
  1. Datei prüfen und aufteilen (90 % Training, 10 % Kontrolle)
  2. LoRA-Training mit mlx-lm auf dem Grundmodell (Qwen3.5 9B, wie das empfohlene Modell der App)
  3. Kontrolle: Fehlerwert auf den zurückgehaltenen Beispielen, vorher und nachher
  4. Zusammenführen: Gelerntes auf die ORIGINAL-Gewichte des Grundmodells (zusammenfuehren.py, nicht `mlx_lm fuse` — das
     speichert umgerechnete Normen, das Ergebnis antwortete im Probelauf nur Unsinn)
  5. Umwandeln ins GGUF-Format (llama.cpp) und auf 4 Bit verkleinern (Q4_K_M, wie das Grundmodell in der App)
  6. Ablegen als modelle/kai-eigen.gguf (das vorige bleibt als kai-eigen-vorher.gguf) + kai-eigen.json

Aufruf über trainieren.sh (nimmt die Umgebung aus einrichten.sh). Nur Python-Standardbibliothek hier — die schweren Teile
laufen als eigene Programme (mlx-lm, llama.cpp), damit ein Speicherfehler dort sauber gemeldet wird.
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

ORDNER = Path(os.environ.get("KAI_KI_ORDNER", Path.home() / "Library" / "Application Support" / "KAI-KI"))
TRAINING = ORDNER / "training"
MODELLE = ORDNER / "modelle"
BASIS_GROSS = "Qwen/Qwen3.5-9B"                 # ab 32 GB Arbeitsspeicher: volle Genauigkeit (bf16)
BASIS_KLEIN = "mlx-community/Qwen3.5-9B-4bit"   # darunter: 4-Bit-Grundmodell (QLoRA), langsamer und etwas ungenauer
ROLLEN = ("system", "user", "assistant")


# ---------- reine Teile (getestet in tests/test_training.py) ----------

def beispiele_pruefen(zeilen):
    """Zeilen der Trainingsdatei → (gültige Beispiele, Fehlermeldungen). Erwartet je Zeile {"messages":[…]} mit
    system/user/assistant, die letzte Nachricht vom Assistenten (die soll das Modell lernen)."""
    gut, fehler = [], []
    for nr, z in enumerate(zeilen, 1):
        z = z.strip()
        if not z:
            continue
        try:
            d = json.loads(z)
        except ValueError:
            fehler.append(f"Zeile {nr}: kein JSON"); continue
        m = d.get("messages") if isinstance(d, dict) else None
        if not isinstance(m, list) or len(m) < 2:
            fehler.append(f"Zeile {nr}: keine Nachrichten"); continue
        if any(not isinstance(x, dict) or x.get("role") not in ROLLEN or not str(x.get("content") or "").strip() for x in m):
            fehler.append(f"Zeile {nr}: Nachricht ohne Rolle oder Text"); continue
        if m[-1]["role"] != "assistant":
            fehler.append(f"Zeile {nr}: letzte Nachricht ist keine Antwort"); continue
        gut.append({"messages": [{"role": x["role"], "content": str(x["content"])} for x in m]})
    return gut, fehler


def aufteilen(beispiele, anteil=0.1, seed=7):
    """Gemischt in Training und Kontrolle teilen — mindestens ein Kontroll-Beispiel, Training nie leer."""
    b = list(beispiele)
    random.Random(seed).shuffle(b)
    n = max(1, round(len(b) * anteil)) if len(b) > 1 else 0
    return b[n:], b[:n]


def schritte(anzahl):
    """Trainingsschritte (Stapel 1): rund drei Durchgänge, mindestens 200, höchstens 1500."""
    return max(200, min(1500, anzahl * 3))


def basis_waehlen(speicher_gb, vorgabe=None):
    """Grundmodell nach Arbeitsspeicher — ein 9B-Modell in voller Genauigkeit braucht beim Training rund 26–30 GB."""
    if vorgabe:
        return vorgabe
    return BASIS_GROSS if speicher_gb >= 30 else BASIS_KLEIN


def original_von(basis):
    """Original-Gewichte zum Trainingsmodell: ein umgewandeltes mlx-Modell (4/8 Bit, bf16) → das Qwen-Original."""
    m = re.match(r"mlx-community/(Qwen.+?)-(\d+bit|bf16)$", basis or "")
    return f"Qwen/{m.group(1)}" if m else basis


def verlust_lesen(text):
    """„Test loss 1.234, Test ppl 3.4“ aus der Ausgabe von mlx-lm → 1.234 (None, wenn nicht gefunden)."""
    t = re.findall(r"Test loss\s+([0-9.]+)", text or "")
    return float(t[-1]) if t else None


# ---------- Ablauf ----------

def melden(text):
    print(f"\n▶ {text}", flush=True)


def abbruch(text):
    print(f"\n✖ {text}", file=sys.stderr, flush=True)
    sys.exit(1)


def speicher_gb():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return 0


def ausfuehren(befehl, log, mitschreiben=True):
    """Programm starten, Ausgabe live zeigen und in die Logdatei schreiben; liefert die Ausgabe als Text."""
    print("  $ " + " ".join(str(x) for x in befehl), flush=True)
    raus = []
    with open(log, "a", encoding="utf-8") as f, subprocess.Popen(
            [str(x) for x in befehl], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}) as p:   # Fortschritt sofort, ohne Farbcodes
        for zeile in p.stdout:
            raus.append(zeile)
            if mitschreiben:
                print("  " + zeile, end="", flush=True)
            f.write(zeile)
        p.wait()
    text = "".join(raus)
    if p.returncode != 0:
        hinweis = ""
        if re.search(r"out of memory|Insufficient Memory|kIOGPUCommandBufferCallbackErrorOutOfMemory|MemoryError", text, re.I):
            hinweis = " — zu wenig Arbeitsspeicher: mit --laenge 4096 (oder kleiner) erneut starten"
        abbruch(f"Schritt fehlgeschlagen (Code {p.returncode}){hinweis}. Ausgabe: {log}")
    return text


def llama_werkzeug(name):
    """llama-quantize aus dem Rechenprogramm, das die App geladen hat."""
    for p in (ORDNER / "llama").rglob(name):
        if p.is_file():
            return p
    return shutil.which(name)


def main():
    ap = argparse.ArgumentParser(description="KAI KI nachtrainieren")
    ap.add_argument("datei", help="Trainingsdatei aus KAI (kai-ki-training-….jsonl)")
    ap.add_argument("--basis", help=f"Grundmodell (Vorgabe nach Arbeitsspeicher: {BASIS_GROSS} bzw. {BASIS_KLEIN})")
    ap.add_argument("--iters", type=int, help="Trainingsschritte (Vorgabe: rund drei Durchgänge)")
    ap.add_argument("--laenge", type=int, default=8192, help="längste Beispiel-Länge in Token (bei Speicherfehler 4096)")
    ap.add_argument("--schichten", type=int, default=16, help="Anzahl nachtrainierter Schichten")
    ap.add_argument("--lernrate", type=float, default=1e-5)
    ap.add_argument("--behalten", action="store_true", help="Zwischenstände (zusammengeführtes Modell, f16-Datei) nicht löschen")
    ap.add_argument("--ohne-ablage", action="store_true", help="Ergebnis nicht in den Modell-Ordner der App legen")
    a = ap.parse_args()

    py = Path(sys.executable)
    gguf_py = TRAINING / "venv-gguf" / "bin" / "python"
    umwandler = TRAINING / "llama.cpp" / "convert_hf_to_gguf.py"
    if not gguf_py.exists() or not umwandler.exists():
        abbruch("Einrichtung fehlt — erst ./einrichten.sh ausführen.")
    quant = llama_werkzeug("llama-quantize")
    if not quant:
        abbruch("llama-quantize nicht gefunden — die App einmal mit dem Grundmodell starten (sie lädt llama.cpp), dann erneut.")

    melden("1/6 Trainingsdatei prüfen")
    zeilen = Path(a.datei).expanduser().read_text("utf-8").splitlines()
    beispiele, fehler = beispiele_pruefen(zeilen)
    for f in fehler[:10]:
        print("  übersprungen: " + f)
    if len(fehler) > 10:
        print(f"  … und {len(fehler) - 10} weitere übersprungen")
    if len(beispiele) < 20:
        abbruch(f"Nur {len(beispiele)} brauchbare Beispiele — für ein Training zu wenig. Erst weiter sammeln (Protokoll → für Training freigeben).")
    if len(beispiele) < 100:
        print(f"  Hinweis: {len(beispiele)} Beispiele sind wenig — die Wirkung bleibt klein. Ab etwa 300 lohnt es sich deutlich.")
    train, kontrolle = aufteilen(beispiele)
    stempel = dt.datetime.now().strftime("%Y%m%d-%H%M")
    lauf = TRAINING / f"lauf-{stempel}"
    daten = lauf / "daten"; daten.mkdir(parents=True, exist_ok=True)
    for name, liste in (("train", train), ("valid", kontrolle), ("test", kontrolle)):
        (daten / f"{name}.jsonl").write_text("".join(json.dumps(b, ensure_ascii=False) + "\n" for b in liste), "utf-8")
    log = lauf / "protokoll.txt"
    gb = speicher_gb()
    basis = basis_waehlen(gb, a.basis)
    iters = a.iters or schritte(len(train))
    print(f"  {len(train)} zum Lernen, {len(kontrolle)} zur Kontrolle · Grundmodell {basis} · {iters} Schritte · "
          f"Arbeitsspeicher {gb:.0f} GB · Ordner {lauf}")

    adapter = lauf / "gelerntes"
    # --mask-prompt: gelernt (und gemessen) wird nur die Antwort, nicht Systemtext/Frage/Daten
    gemeinsam = ["--model", basis, "--data", daten, "--max-seq-length", a.laenge, "--mask-prompt"]
    melden("2/6 Kontrolle vorher (Grundmodell ohne Training)")
    vorher = verlust_lesen(ausfuehren([py, "-m", "mlx_lm", "lora", *gemeinsam, "--adapter-path", "", "--test", "--test-batches", -1],
                                       log, False))
    print(f"  Fehlerwert vorher: {vorher}")

    melden("3/6 Training (das dauert — je nach Menge 20 bis 90 Minuten)")
    ausfuehren([py, "-m", "mlx_lm", "lora", *gemeinsam, "--train", "--adapter-path", adapter, "--iters", iters,
                "--batch-size", 1, "--num-layers", a.schichten, "--learning-rate", a.lernrate, "--grad-checkpoint", "--steps-per-eval", 50, "--save-every", 100, "--seed", 7], log)
    nachher = verlust_lesen(ausfuehren([py, "-m", "mlx_lm", "lora", *gemeinsam, "--adapter-path", adapter, "--test",
                                        "--test-batches", -1], log, False))
    print(f"  Fehlerwert nachher: {nachher} (vorher {vorher}) — kleiner ist besser")
    if vorher is not None and nachher is not None and nachher >= vorher:
        print("  Achtung: auf den Kontroll-Beispielen nicht besser geworden. Weiter geht es trotzdem; ob es sich lohnt,"
              " zeigt der Systemcheck in KAI („Mit Modell prüfen“).")

    melden("4/6 Zusammenführen (Gelerntes auf die Original-Gewichte)")
    original = original_von(basis)
    if original != basis:
        print(f"  Original zum 4-Bit-Grundmodell: {original} (einmaliger Download, ca. 19 GB)")
    holen = ("import sys; from huggingface_hub import snapshot_download as s; "
             "print(s(sys.argv[1], allow_patterns=['*.json', '*.safetensors', '*.jinja', '*.txt', '*.model']))")
    ordner = [z for z in ausfuehren([py, "-c", holen, original], log, False).splitlines() if z.strip()][-1].strip()
    zusammen = lauf / "zusammen"
    ausfuehren([gguf_py, "-I", Path(__file__).with_name("zusammenfuehren.py"), ordner, adapter, zusammen], log)

    melden("5/6 Umwandeln für die App (GGUF, 4 Bit)")
    f16 = lauf / "kai-eigen-f16.gguf"
    ausfuehren([gguf_py, umwandler, zusammen, "--outfile", f16, "--outtype", "f16"], log)
    ergebnis = lauf / "kai-eigen.gguf"
    ausfuehren([quant, f16, ergebnis, "Q4_K_M"], log)
    if not a.behalten:
        f16.unlink(missing_ok=True)
        shutil.rmtree(zusammen, ignore_errors=True)
        shutil.rmtree(daten, ignore_errors=True)     # Kopien der Trainingsdaten (Fragen aus dem Haus) nicht liegen lassen

    info = {"datum": dt.date.today().strftime("%d.%m.%Y"), "basis": basis, "beispiele": len(beispiele), "lernen": len(train),
            "kontrolle": len(kontrolle), "schritte": iters, "fehlerwert_vorher": vorher, "fehlerwert_nachher": nachher,
            "datei": Path(a.datei).name, "lauf": str(lauf)}
    (lauf / "kai-eigen.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), "utf-8")
    if a.ohne_ablage:
        melden(f"Fertig — Ergebnis liegt in {ergebnis} (nicht abgelegt).")
        return
    melden("6/6 In der App ablegen")
    MODELLE.mkdir(parents=True, exist_ok=True)
    ziel = MODELLE / "kai-eigen.gguf"
    if ziel.exists():
        ziel.replace(MODELLE / "kai-eigen-vorher.gguf")
        if (MODELLE / "kai-eigen.json").exists():
            (MODELLE / "kai-eigen.json").replace(MODELLE / "kai-eigen-vorher.json")
    shutil.move(str(ergebnis), ziel)
    (MODELLE / "kai-eigen.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), "utf-8")
    print(f"""
✔ Fertig. Nächste Schritte:
  1. App „KAI KI“ neu öffnen → Modell „KAI angepasst (eigenes Training, Stand {info['datum']})“ wählen → Starten.
  2. In KAI: Administration → KI → Systemcheck → „Mit Modell prüfen“ und mit dem letzten Lauf des Grundmodells vergleichen.
  3. Schlechter als vorher? In der App wieder „Qwen3.5 9B“ wählen. Das vorige eigene Modell liegt als kai-eigen-vorher.gguf daneben.
  Die Trainingsdatei enthält Fragen aus dem Haus — nach dem Training löschen: {Path(a.datei).expanduser()}
""")


if __name__ == "__main__":
    main()
