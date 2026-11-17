"""Gespräch direkt in der App (Reiter „Chat“): ohne KAI und ohne Netz mit dem Modell auf diesem Mac. Reine Teile ohne Qt,
damit sie auf jedem Rechner testbar sind."""
from datetime import date

WOCHENTAG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def system_text(heute: date | None = None) -> str:
    d = heute or date.today()
    return ("Du bist die KI von KAI, dem Kurs-, Auftrags- und Informationssystem der Bodensee-Schiffsbetriebe (BSB). "
            "Du läufst auf diesem Mac, nichts verlässt das Gerät. Antworte auf Deutsch, sachlich, freundlich und knapp; "
            f"nutze bei Bedarf Aufzählungen oder kleine Tabellen (Markdown). Heute ist {WOCHENTAG[d.weekday()]}, der {d:%d.%m.%Y}. "
            "Du hast hier keinen Zugriff auf die Daten in KAI; dafür gibt es in KAI den KI-Chat. Wenn du etwas nicht weißt, sag es offen.")


def verlauf_markdown(nachrichten: list, laufend: str | None = None) -> str:
    """Gesprächsverlauf als Markdown für die Anzeige. nachrichten = [{role, content, anhang?}]; laufend = Antwort im Entstehen."""
    teile = []
    for m in nachrichten:
        if m["role"] == "user":
            anh = f" 📎 {m['anhang']}" if m.get("anhang") else ""
            teile.append(f"**Du:**{anh}\n\n{m['content']}")
        elif m["role"] == "assistant":
            teile.append(f"**KAI KI:**\n\n{m['content']}")
    if laufend is not None:
        teile.append(f"**KAI KI:**\n\n{laufend or '…'} ▍")
    return "\n\n---\n\n".join(teile)


def wav_aus_pcm(roh: bytes, rate: int, kanaele: int = 1, gleitkomma: bool = False) -> bytes:
    """Mikrofon-Aufnahme (Qt liefert rohe Samples: Int16 oder Float32, ggf. mehrere Kanäle) → WAV 16 bit mono.
    Die Rate bleibt; der Hörer rechnet selbst auf 16 kHz um."""
    import array
    import io
    import wave
    if gleitkomma:
        f = array.array("f"); f.frombytes(roh[: len(roh) // 4 * 4])
        werte = [max(-1.0, min(1.0, x)) for x in f]
        s = array.array("h", (int(x * 32767) for x in werte))
    else:
        s = array.array("h"); s.frombytes(roh[: len(roh) // 2 * 2])
    if kanaele > 1:                                   # auf einen Kanal mitteln
        s = array.array("h", (int(sum(s[i:i + kanaele]) / kanaele) for i in range(0, len(s) - kanaele + 1, kanaele)))
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(rate)); w.writeframes(s.tobytes())
    return puffer.getvalue()


def vorlese_text(md: str, grenze: int = 1500) -> str:
    """Antwort zum Vorlesen: Markdown weg, Tabellen als Sätze, höchstens `grenze` Zeichen (wie „Vorlesen“ in KAI)."""
    import re
    zeilen = [z for z in str(md or "").splitlines() if not re.match(r"^\s*\|?\s*:?-{2,}", z)]
    zeilen = [", ".join(c.strip() for c in z.split("|") if c.strip()) + "." if z.strip().startswith("|") else z for z in zeilen]
    t = "\n".join(zeilen)
    t = re.sub(r"```[\s\S]*?```", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^\s*[-•]\s+|^\s*\d+[.)]\s+", "", t, flags=re.M)
    t = re.sub(r"[*_`#>]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= grenze:
        return t
    k = t.rfind(". ", 0, grenze)
    return t[: k + 1] if k > grenze * 0.4 else t[:grenze]
