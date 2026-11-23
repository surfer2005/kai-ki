"""Anmeldung bei Microsoft für Outlook.com/Live/Hotmail-Postfächer (ab 0.1.22).

Microsoft lässt für Outlook.com keine Anmeldung mit Passwort per IMAP mehr zu; es geht nur noch mit OAuth 2.0 (XOAUTH2). Ablauf:
der Browser öffnet die Microsoft-Anmeldeseite, nach der Anmeldung leitet Microsoft auf http://localhost:<Port> zurück — dort wartet
die App auf den Code und tauscht ihn (mit PKCE, ohne Geheimnis — die App ist ein „öffentlicher Client“) gegen Zugangsschlüssel.
Der langlebige Erneuerungsschlüssel (refresh token) liegt im Schlüsselbund, der kurzlebige Zugangsschlüssel nur im Arbeitsspeicher.

Es braucht eine EIGENE App-Registrierung in Microsoft Entra (Client-ID, in der App einstellbar) — nie die Client-ID eines fremden
Programms. Anleitung: README, Abschnitt „Postfach aufräumen (ab 0.1.22)“.
"""
import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

MANDANT = "consumers"                                 # nur persönliche Microsoft-Konten (Outlook.com, Live, Hotmail)
AUTH_URL = f"https://login.microsoftonline.com/{MANDANT}/oauth2/v2.0/authorize"
TOKEN_URL = f"https://login.microsoftonline.com/{MANDANT}/oauth2/v2.0/token"
SCOPES = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
OHNE_CLIENT_ID = ("Für Outlook.com braucht die App eine eigene Client-ID aus Microsoft Entra (kostenlos, einmalig anzulegen). "
                  "Die Anleitung steht in der README unter „Postfach aufräumen (ab 0.1.22)“ — dann die Client-ID beim Konto eintragen.")


class AnmeldeFehler(Exception):
    pass


def pkce_paar() -> tuple[str, str]:
    """(code_verifier, code_challenge) nach RFC 7636, Verfahren S256."""
    verifier = secrets.token_urlsafe(64)[:96]          # 43–128 Zeichen aus A–Z a–z 0–9 - _
    return verifier, challenge_von(verifier)


def challenge_von(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def client_id_pruefen(client_id) -> str:
    cid = (client_id or "").strip()
    if not cid:
        raise AnmeldeFehler(OHNE_CLIENT_ID)
    if len(cid) > 100 or any(c.isspace() for c in cid):
        raise AnmeldeFehler("Die Client-ID sieht nicht richtig aus (z. B. 1a2b3c4d-…, ohne Leerzeichen).")
    return cid


def anmelde_adresse(client_id: str, rueckruf: str, challenge: str, state: str, adresse: str = "") -> str:
    p = {"client_id": client_id, "response_type": "code", "redirect_uri": rueckruf, "response_mode": "query", "scope": SCOPES,
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"}
    if adresse:
        p["login_hint"] = adresse
    return f"{AUTH_URL}?{urlencode(p)}"


SEITE = ("<!doctype html><meta charset='utf-8'><title>KAI KI</title><body style='font-family:-apple-system,sans-serif;margin:3em'>"
         "<h2>{titel}</h2><p>{text}</p></body>")


class Rueckruf:
    """Kleiner Webserver auf 127.0.0.1 (und ::1, falls vorhanden), der genau EINEN Rückruf von Microsoft annimmt."""

    def __init__(self, state: str):
        self.state, self.code, self.fehler = state, None, None
        self.fertig = threading.Event()
        self.server: list[HTTPServer] = []
        rueckruf = self

        class Bearbeiter(BaseHTTPRequestHandler):
            def log_message(self, *a):                # nichts ins Protokoll (die Adresse enthält den Code)
                pass

            def do_GET(self):
                q = parse_qs(urlparse(self.path).query)
                if urlparse(self.path).path not in ("/", ""):
                    self.send_response(404); self.end_headers(); return
                titel, text = rueckruf.annehmen(q)
                body = SEITE.format(titel=titel, text=text).encode("utf-8")
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        s4 = HTTPServer(("127.0.0.1", 0), Bearbeiter)
        self.port = s4.server_address[1]
        self.server.append(s4)
        try:                                           # Browser lösen „localhost“ teils zuerst über IPv6 auf
            import socket

            class Server6(HTTPServer):
                address_family = socket.AF_INET6
            self.server.append(Server6(("::1", self.port), Bearbeiter))
        except OSError:
            pass
        for s in self.server:
            threading.Thread(target=s.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()

    @property
    def adresse(self) -> str:
        return f"http://localhost:{self.port}"

    def annehmen(self, q: dict) -> tuple[str, str]:
        if self.fertig.is_set():
            return "Schon erledigt", "Du kannst dieses Fenster schließen."
        if (q.get("state") or [""])[0] != self.state:
            self.fehler = "Antwort von Microsoft passt nicht zu dieser Anmeldung (state) — bitte noch einmal versuchen."
        elif q.get("error"):
            self.fehler = f"Microsoft: {(q.get('error_description') or q.get('error'))[0][:300]}"
        elif q.get("code"):
            self.code = q["code"][0]
        else:
            self.fehler = "Microsoft hat keinen Code geschickt."
        self.fertig.set()
        if self.fehler:
            return "Anmeldung nicht geklappt", "Zurück zur App „KAI KI“ — dort steht, was fehlt."
        return "Anmeldung abgeschlossen", "Du kannst dieses Fenster schließen und zur App „KAI KI“ zurückkehren."

    def schliessen(self):
        for s in self.server:
            s.shutdown()                               # wartet höchstens poll_interval
            s.server_close()


def _token_antwort(r) -> dict:
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code >= 400 or "access_token" not in j:
        text = j.get("error_description") or j.get("error") or f"HTTP {r.status_code}"
        if "AADSTS700016" in str(text) or "unauthorized_client" in str(j.get("error")):
            text = f"Microsoft kennt diese Client-ID nicht (oder sie ist nicht für persönliche Konten freigegeben). {str(text)[:200]}"
        raise AnmeldeFehler(f"Microsoft: {str(text)[:400]}")
    return {"access_token": j["access_token"], "refresh_token": j.get("refresh_token") or "",
            "laeuft_ab": time.time() + int(j.get("expires_in") or 3600) - 120}


def code_einloesen(client_id: str, code: str, verifier: str, rueckruf: str, post=None) -> dict:
    if post is None:
        import requests
        post = requests.post
    r = post(TOKEN_URL, data={"client_id": client_id, "grant_type": "authorization_code", "code": code, "redirect_uri": rueckruf,
                              "code_verifier": verifier, "scope": SCOPES}, timeout=30)
    return _token_antwort(r)


def erneuern(client_id: str, refresh_token: str, post=None) -> dict:
    """Neuer Zugangsschlüssel aus dem Erneuerungsschlüssel. Microsoft schickt dabei meist auch einen NEUEN Erneuerungsschlüssel —
    der muss gespeichert werden (der alte läuft irgendwann ab)."""
    client_id = client_id_pruefen(client_id)
    if not refresh_token:
        raise AnmeldeFehler("Für dieses Konto ist keine Anmeldung gespeichert — bitte beim Konto „Ändern …“ neu anmelden.")
    if post is None:
        import requests
        post = requests.post
    r = post(TOKEN_URL, data={"client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh_token,
                              "scope": SCOPES}, timeout=30)
    return _token_antwort(r)


def anmelden(client_id: str, adresse: str = "", browser=webbrowser.open, warten_s: int = 300, post=None,
             abbruch: threading.Event | None = None) -> dict:
    """Browser-Anmeldung → {access_token, refresh_token, laeuft_ab}. Wartet höchstens `warten_s` Sekunden auf den Rückruf."""
    client_id = client_id_pruefen(client_id)
    verifier, challenge = pkce_paar()
    state = secrets.token_urlsafe(24)
    rr = Rueckruf(state)
    try:
        if not browser(anmelde_adresse(client_id, rr.adresse, challenge, state, adresse)):
            raise AnmeldeFehler("Der Browser ließ sich nicht öffnen.")
        ende = time.time() + warten_s
        while not rr.fertig.wait(0.25):
            if (abbruch and abbruch.is_set()) or time.time() > ende:
                raise AnmeldeFehler("Anmeldung abgebrochen bzw. nicht rechtzeitig abgeschlossen.")
        if rr.fehler:
            raise AnmeldeFehler(rr.fehler)
        return code_einloesen(client_id, rr.code, verifier, rr.adresse, post)
    finally:
        rr.schliessen()
