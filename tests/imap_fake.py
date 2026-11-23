"""Kleiner IMAP-Server für die Tests (echter Socket auf 127.0.0.1, ohne TLS): die App spricht mit ihm über das normale imaplib —
so wird auch geprüft, wie imaplib Antworten, Literale und Antwortcodes (COPYUID) liefert. Kann nur, was die App braucht.
Jeder Befehl landet in `befehle` (zum Prüfen: kein DELETE, kein EXPUNGE ohne UIDPLUS, Lesen nur mit PEEK …)."""
import base64
import re
import socketserver
import threading
from datetime import datetime, timezone

MONATE = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\(|\)|[^\s()"\[]+(?:\[[^\]]*\][^\s()"]*)?')


def _unquote(t: str) -> str:
    if t.startswith('"') and t.endswith('"'):
        return re.sub(r"\\(.)", r"\1", t[1:-1])
    return t


def _baum(tokens):
    stapel = [[]]
    for t in tokens:
        if t == "(":
            stapel.append([])
        elif t == ")":
            x = stapel.pop(); stapel[-1].append(x)
        else:
            stapel[-1].append(t)
    return stapel[0]


def _menge(text: str, hoechste: int) -> set:
    raus = set()
    for teil in text.split(","):
        if ":" in teil:
            a, b = teil.split(":")
            a = hoechste if a == "*" else int(a)
            b = hoechste if b == "*" else int(b)
            raus |= set(range(min(a, b), max(a, b) + 1))
        else:
            raus.add(hoechste if teil == "*" else int(teil))
    return raus


class Server:
    def __init__(self, *, caps=("IMAP4rev1", "MOVE", "UIDPLUS", "NAMESPACE", "SPECIAL-USE", "AUTH=PLAIN", "AUTH=XOAUTH2"),
                 trenner="/", praefix="", benutzer="peter@example.de", passwort="Geheim-123", token=None):
        self.caps, self.trenner, self.praefix = list(caps), trenner, praefix
        self.benutzer, self.passwort, self.token = benutzer, passwort, token
        self.boxen: dict = {}
        self.befehle: list = []
        self.trennen_beim_lesen = False                   # nächster Abruf von Mail-Inhalten: Verbindung einfach weg
        self.anmeldungen: list = []
        self.lock = threading.RLock()
        self._naechste_validity = 1000
        server = self

        class Bearbeiter(socketserver.StreamRequestHandler):
            def handle(self):
                server._sitzung(self)

        class TCP(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True
        self.tcp = TCP(("127.0.0.1", 0), Bearbeiter)
        self.port = self.tcp.server_address[1]
        threading.Thread(target=self.tcp.serve_forever, daemon=True).start()
        self.ordner("INBOX")

    def stoppen(self):
        self.tcp.shutdown(); self.tcp.server_close()

    # ---- Inhalt
    def ordner(self, name: str, flags=()):
        with self.lock:
            if name not in self.boxen:
                self._naechste_validity += 1
                self.boxen[name] = {"flags": list(flags), "validity": self._naechste_validity, "uidnext": 1, "msgs": []}
            return self.boxen[name]

    def mail(self, box: str, roh: bytes, flags=("\\Seen",), datum=None, struktur=None) -> int:
        with self.lock:
            b = self.ordner(box)
            uid = b["uidnext"]; b["uidnext"] += 1
            b["msgs"].append({"uid": uid, "flags": set(flags), "roh": roh, "datum": datum or datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
                              "struktur": struktur})
            return uid

    def inhalt(self, box: str) -> list:
        with self.lock:
            return [(m["uid"], sorted(m["flags"]), m["roh"]) for m in self.boxen[box]["msgs"]]

    def message_ids(self, box: str) -> list:
        raus = []
        for _u, _f, roh in self.inhalt(box):
            m = re.search(rb"(?im)^Message-ID:\s*(\S+)", roh)
            raus.append(m.group(1).decode() if m else None)
        return raus

    # ---- Sitzung
    def _sitzung(self, h):
        zustand = {"an": False, "box": None, "nur_lesen": False}
        w = h.wfile

        def senden(x):
            w.write(x if isinstance(x, bytes) else x.encode("latin-1")); w.flush()
        senden(f"* OK [CAPABILITY {' '.join(self.caps)}] Fake-IMAP bereit\r\n")
        while True:
            zeile = h.rfile.readline()
            if not zeile:
                return
            zeile = zeile.decode("latin-1").rstrip("\r\n")
            tag, _, rest = zeile.partition(" ")
            with self.lock:
                self.befehle.append(rest)
            try:
                weiter = self._befehl(tag, rest, zustand, senden, h)
            except Exception as ex:  # noqa: BLE001
                senden(f"{tag} BAD {ex}\r\n"); weiter = True
            if not weiter:
                return

    def _befehl(self, tag, rest, z, senden, h) -> bool:
        tokens = TOKEN.findall(rest)
        cmd = tokens[0].upper() if tokens else ""
        args = tokens[1:]
        if cmd == "UID":
            cmd = "UID " + args[0].upper(); args = args[1:]
        if cmd == "CAPABILITY":
            senden(f"* CAPABILITY {' '.join(self.caps)}\r\n{tag} OK CAPABILITY fertig\r\n"); return True
        if cmd == "NOOP":
            senden(f"{tag} OK fertig\r\n"); return True
        if cmd == "LOGOUT":
            senden(f"* BYE tschuess\r\n{tag} OK fertig\r\n"); return False
        if cmd == "LOGIN":
            u, p = _unquote(args[0]), _unquote(args[1])
            self.anmeldungen.append(("LOGIN", u))
            if u == self.benutzer and p == self.passwort:
                z["an"] = True; senden(f"{tag} OK [CAPABILITY {' '.join(self.caps)}] angemeldet\r\n")
            else:
                senden(f"{tag} NO [AUTHENTICATIONFAILED] Authentication failed.\r\n")
            return True
        if cmd == "AUTHENTICATE":
            mech = args[0].upper()
            senden("+ \r\n")
            antwort = base64.b64decode(h.rfile.readline().strip() or b"").decode("utf-8")
            ok = False
            if mech == "PLAIN":
                _, u, p = antwort.split("\0")
                ok = u == self.benutzer and p == self.passwort
            elif mech == "XOAUTH2":
                m = re.fullmatch(r"user=([^\x01]*)\x01auth=Bearer ([^\x01]*)\x01\x01", antwort)
                ok = bool(m) and m.group(1) == self.benutzer and self.token is not None and m.group(2) == self.token
            self.anmeldungen.append((mech, self.benutzer if ok else None))
            if ok:
                z["an"] = True; senden(f"{tag} OK angemeldet\r\n")
            else:
                senden(f"{tag} NO AUTHENTICATE failed.\r\n")
            return True
        if not z["an"]:
            senden(f"{tag} BAD nicht angemeldet\r\n"); return True
        if cmd == "NAMESPACE":
            senden(f'* NAMESPACE (("{self.praefix}" "{self.trenner}")) NIL NIL\r\n{tag} OK fertig\r\n'); return True
        if cmd == "LIST":
            for name, b in sorted(self.boxen.items()):
                fl = " ".join(b["flags"])
                if '"' in name:
                    senden(f'* LIST ({fl}) "{self.trenner}" {{{len(name)}}}\r\n{name}\r\n')
                else:
                    senden(f'* LIST ({fl}) "{self.trenner}" "{name}"\r\n')
            senden(f"{tag} OK LIST fertig\r\n"); return True
        if cmd in ("CREATE", "SUBSCRIBE", "DELETE"):
            name = _unquote(args[0])
            if cmd == "SUBSCRIBE":
                senden(f"{tag} OK fertig\r\n"); return True
            if cmd == "DELETE":
                senden(f"{tag} NO DELETE ist im Test verboten\r\n"); return True
            if name in self.boxen:
                senden(f"{tag} NO [ALREADYEXISTS] Mailbox exists\r\n"); return True
            innen = name[len(self.praefix):] if self.praefix and name.startswith(self.praefix) else name
            if self.trenner in innen:
                eltern = self.praefix + innen.rsplit(self.trenner, 1)[0]
                if eltern not in self.boxen:
                    senden(f"{tag} NO Eltern fehlen\r\n"); return True
            self.ordner(name); senden(f"{tag} OK CREATE fertig\r\n"); return True
        if cmd in ("SELECT", "EXAMINE"):
            name = _unquote(args[0])
            if name not in self.boxen:
                senden(f"{tag} NO gibt es nicht\r\n"); return True
            b = self.boxen[name]
            z["box"], z["nur_lesen"] = name, cmd == "EXAMINE"
            senden(f"* FLAGS (\\Seen \\Deleted)\r\n* {len(b['msgs'])} EXISTS\r\n* 0 RECENT\r\n* OK [UIDVALIDITY {b['validity']}] UIDs\r\n"
                   f"* OK [UIDNEXT {b['uidnext']}] next\r\n{tag} OK [{'READ-ONLY' if z['nur_lesen'] else 'READ-WRITE'}] fertig\r\n")
            return True
        if z["box"] is None:
            senden(f"{tag} BAD kein Ordner gewaehlt\r\n"); return True
        b = self.boxen[z["box"]]
        msgs = b["msgs"]
        if cmd == "UID SEARCH":
            treffer = [m["uid"] for m in msgs if self._passt(m, args)]
            senden(f"* SEARCH {' '.join(map(str, treffer))}\r\n{tag} OK SEARCH fertig\r\n"); return True
        if cmd in ("UID FETCH", "FETCH"):
            if self.trennen_beim_lesen and "BODY.PEEK[]<" in rest.upper():
                self.trennen_beim_lesen = False
                return False
            if cmd == "FETCH":
                seqs = _menge(args[0], len(msgs))
                wahl = [(i + 1, m) for i, m in enumerate(msgs) if i + 1 in seqs]
            else:
                uids = _menge(args[0], max([m["uid"] for m in msgs] or [0]))
                wahl = [(i + 1, m) for i, m in enumerate(msgs) if m["uid"] in uids]
            items = _baum(args[1:])
            items = items[0] if items and isinstance(items[0], list) else items
            for seq, m in wahl:
                senden(self._fetch(seq, m, items, cmd == "UID FETCH", z["nur_lesen"]))
            senden(f"{tag} OK FETCH fertig\r\n"); return True
        if cmd in ("UID MOVE", "UID COPY"):
            if cmd == "UID MOVE" and "MOVE" not in self.caps:
                senden(f"{tag} BAD kein MOVE\r\n"); return True
            if cmd == "UID MOVE" and z["nur_lesen"]:
                senden(f"{tag} NO [READ-ONLY]\r\n"); return True
            ziel = _unquote(args[1])
            if ziel not in self.boxen:
                senden(f"{tag} NO [TRYCREATE] gibt es nicht\r\n"); return True
            uids = _menge(args[0], max([m["uid"] for m in msgs] or [0]))
            zb = self.boxen[ziel]
            paare = []
            for m in [m for m in msgs if m["uid"] in uids]:
                neu = zb["uidnext"]; zb["uidnext"] += 1
                zb["msgs"].append({**m, "uid": neu, "flags": set(m["flags"]) - {"\\Deleted"}})
                paare.append((m["uid"], neu))
            code = f"[COPYUID {zb['validity']} {','.join(str(a) for a, _ in paare)} {','.join(str(n) for _, n in paare)}]" \
                if paare and "UIDPLUS" in self.caps else ""
            if cmd == "UID MOVE":
                if code:
                    senden(f"* OK {code} verschoben\r\n")
                for seq in sorted((i + 1 for i, m in enumerate(msgs) if m["uid"] in uids), reverse=True):
                    senden(f"* {seq} EXPUNGE\r\n")
                b["msgs"] = [m for m in msgs if m["uid"] not in uids]
                senden(f"{tag} OK MOVE fertig\r\n")
            else:
                senden(f"{tag} OK {code} COPY fertig\r\n")
            return True
        if cmd == "UID STORE":
            if z["nur_lesen"]:
                senden(f"{tag} NO [READ-ONLY]\r\n"); return True
            uids = _menge(args[0], max([m["uid"] for m in msgs] or [0]))
            flags = [f for f in _baum(args[2:])[0]] if args[2:] and args[2] == "(" else args[2:]
            for m in msgs:
                if m["uid"] in uids:
                    if args[1].upper().startswith("+"):
                        m["flags"] |= set(flags)
                    elif args[1].upper().startswith("-"):
                        m["flags"] -= set(flags)
            senden(f"{tag} OK STORE fertig\r\n"); return True
        if cmd in ("UID EXPUNGE", "EXPUNGE"):
            if cmd == "UID EXPUNGE" and "UIDPLUS" not in self.caps:
                senden(f"{tag} BAD kein UIDPLUS\r\n"); return True
            uids = _menge(args[0], max([m["uid"] for m in msgs] or [0])) if cmd == "UID EXPUNGE" else None
            weg = [i + 1 for i, m in enumerate(msgs) if "\\Deleted" in m["flags"] and (uids is None or m["uid"] in uids)]
            for seq in sorted(weg, reverse=True):
                senden(f"* {seq} EXPUNGE\r\n")
            b["msgs"] = [m for i, m in enumerate(msgs) if i + 1 not in weg]
            senden(f"{tag} OK EXPUNGE fertig\r\n"); return True
        senden(f"{tag} BAD unbekannt: {cmd}\r\n")
        return True

    def _passt(self, m, args) -> bool:
        i = 0
        while i < len(args):
            a = args[i].upper()
            if a == "ALL":
                pass
            elif a == "SEEN" and "\\Seen" not in m["flags"]:
                return False
            elif a == "UNSEEN" and "\\Seen" in m["flags"]:
                return False
            elif a == "UNDELETED" and "\\Deleted" in m["flags"]:
                return False
            elif a == "SINCE":
                t, mo, j = args[i + 1].split("-")
                ab = datetime(int(j), MONATE.index(mo) + 1, int(t), tzinfo=timezone.utc)
                if m["datum"] < ab:
                    return False
                i += 1
            elif a == "HEADER":
                feld, wert = args[i + 1], _unquote(args[i + 2])
                kopf = re.search(rb"(?im)^" + re.escape(feld.encode()) + rb":\s*(.*)$", m["roh"])
                if not kopf or wert.lower() not in kopf.group(1).decode("latin-1").strip().lower():
                    return False
                i += 2
            i += 1
        return True

    def _fetch(self, seq, m, items, mit_uid, nur_lesen) -> bytes:
        teile: list = []
        namen = [str(x).upper() if isinstance(x, str) else x for x in items]
        if mit_uid and "UID" not in namen:
            namen = ["UID"] + namen
        for n in namen:
            if n == "UID":
                teile.append(f"UID {m['uid']}".encode())
            elif n == "FLAGS":
                teile.append(f"FLAGS ({' '.join(sorted(m['flags']))})".encode())
            elif n == "RFC822.SIZE":
                teile.append(f"RFC822.SIZE {len(m['roh'])}".encode())
            elif n == "INTERNALDATE":
                d = m["datum"]
                teile.append(f'INTERNALDATE "{d.day:02d}-{MONATE[d.month - 1]}-{d.year} {d:%H:%M:%S} +0000"'.encode())
            elif n == "BODYSTRUCTURE":
                teile.append(("BODYSTRUCTURE " + (m["struktur"] or '("text" "plain" ("charset" "utf-8") NIL NIL "7bit" 10 1)')).encode())
            elif n.startswith("BODY"):
                peek = n.startswith("BODY.PEEK")
                abschnitt = re.search(r"\[(.*)\]", n).group(1)
                teil_ = re.search(r"<(\d+)\.(\d+)>", n)
                if abschnitt.startswith("HEADER.FIELDS"):
                    felder = re.search(r"\((.*)\)", abschnitt).group(1).split()
                    kopf = m["roh"].split(b"\r\n\r\n", 1)[0]
                    daten = b"".join(z + b"\r\n" for z in kopf.split(b"\r\n")
                                     if any(z.lower().startswith(f.lower().encode() + b":") for f in felder)) + b"\r\n"
                else:
                    daten = m["roh"]
                schl = f"BODY[{abschnitt}]"
                if teil_:
                    a, laenge = int(teil_.group(1)), int(teil_.group(2))
                    daten = daten[a:a + laenge]; schl += f"<{a}>"
                if not peek and not nur_lesen:
                    m["flags"].add("\\Seen")
                teile.append(schl.encode() + f" {{{len(daten)}}}\r\n".encode() + daten)
        return f"* {seq} FETCH (".encode() + b" ".join(teile) + b")\r\n"


def mail(betreff: str, absender="Telekom <rechnung@telekom.de>", text="Hallo", mid=None, datum="Thu, 01 Oct 2026 09:00:00 +0200",
         anhang: str | None = None) -> bytes:
    """Einfache Mail; `betreff` darf schon kodiert sein (=?UTF-8?…?=)."""
    kopf = f"From: {absender}\r\nTo: peter@example.de\r\nSubject: {betreff}\r\nDate: {datum}\r\n"
    if mid:
        kopf += f"Message-ID: {mid}\r\n"
    if not anhang:
        return (kopf + "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
                ).encode() + text.encode("utf-8") + b"\r\n"
    return (kopf + 'MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary="GRENZE"\r\n\r\n--GRENZE\r\n'
            "Content-Type: text/plain; charset=utf-8\r\n\r\n").encode() + text.encode("utf-8") + (
        f'\r\n--GRENZE\r\nContent-Type: application/pdf; name="{anhang}"\r\nContent-Disposition: attachment; filename="{anhang}"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQK\r\n--GRENZE--\r\n").encode()
