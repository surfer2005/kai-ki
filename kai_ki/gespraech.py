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
