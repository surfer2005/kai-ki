# KAI KI — eigene KI auf dem Mac

Liest Belegseiten (z. B. eingehende Lieferscheine) für KAI mit einem **Modell auf diesem Mac**. Die App holt die
Aufträge bei KAI ab (nur ausgehende Verbindung, eigener Schlüssel je Gerät) — die Belegbilder verlassen den Mac nicht.
Außerdem: Chat direkt mit dem Modell, Nachtrainieren und — ab 0.1.20 — **Aufräumen** von Ordnern auf dem Mac (Reiter „Aufräumen“),
ab 0.1.22 auch von **E-Mail-Postfächern** (iCloud, web.de, Outlook.com/Live, andere IMAP-Server).

## Einrichten
1. Release laden: <https://github.com/surfer2005/kai-ki/releases/latest> → `KAI-KI-macOS-….zip` entpacken, „KAI KI“ in
   *Programme* ziehen, beim ersten Öffnen **Rechtsklick → Öffnen** (nicht bei Apple signiert).
2. In KAI: *Einstellungen → Schnittstellen → KI* → Anbieter „Eigene KI auf einem Gerät“ → Name eintragen → **Gerät koppeln**.
3. In der App KAI-Adresse und Code eintragen → **Koppeln**. Beim ersten Start lädt die App das Rechenprogramm
   (llama.cpp, macOS arm64) und das gewählte Modell (Qwen3.5 9B empfohlen, ca. 6,6 GB; außerdem Qwen3-VL 8B, Qwen3-VL 8B Q8, Qwen2.5-VL 7B/3B) — das dauert einmalig. Jedes Modell liegt danach im Ordner `modelle`; nicht mehr gebrauchte lassen sich dort löschen.

## Wie es arbeitet
- KAI legt je Seite einen Auftrag ab; die App holt ihn ab, macht aus dem PDF ein Bild (pdfium), liest den Text mit
  **Apples Texterkennung** (auf dem Gerät) und gibt Bild + Text an das Modell (llama.cpp, nur auf 127.0.0.1).
  Die Antwort (JSON) geht an KAI zurück; dort wird zerlegt, zugeordnet usw. wie mit der Cloud-KI.
- **Mehrere Chat-Fragen gleichzeitig** (ab 0.1.23, Peter 2026-11-28: „wenn 5 Leute gleichzeitig fragen“): das Modell rechnet je
  nach Arbeitsspeicher mehrere Fragen auf einmal (llama-server `-np`, Kontext 12.288 je Frage): bis 23 GB eine (MacBook Air 16 GB wie
  bisher), ab 24 GB zwei, ab 40 GB vier (Mac mini 48/64 GB). Je zusätzlichem Platz holt ein Helfer NUR Chat-Aufträge bei KAI ab;
  Lesen (Lieferscheine), Sprechen und Hören bleiben nacheinander im Hauptablauf. Weitere Fragen warten in KAI, Chat vor Lieferscheinen.
- **Reiter „Chat“:** allgemeiner Assistent für jede Frage, nur auf diesem Mac. Ab 0.1.24 lenkt er nicht mehr zu KAI (vorher begann die
  Grundanweisung mit „Du bist die KI von KAI …“); KAI kommt nur vor, wenn ausdrücklich danach gefragt wird. Fragen mit KAI-Daten: KI-Chat in KAI.
  Mit dem Modell „KAI angepasst“ (eigenes Training auf KAI-Abfragen) bleibt eine Neigung zu KAI — für allgemeine Fragen Qwen3.5 9B wählen.
- Fenster schließen = weiter im Hintergrund (Punkt in der Menüleiste: grün bereit, blau arbeitet, rot getrennt).
- Daten: `~/Library/Application Support/KAI-KI/` (Einstellungen mit Schlüssel nur für den Benutzer lesbar, Modelle, Protokoll).

## Entwickeln
Quelle liegt im KAI-Repo unter `edge/kai-ki/` und wird hierher gespiegelt. Release: Version in `kai_ki/__init__.py`
anheben, Tag `vX.Y.Z` pushen → GitHub baut die App (macOS arm64) und legt das Release an.

## Reiter „Aufräumen“ (ab 0.1.20)

Ordner auf diesem Mac sortieren lassen (Peter 2026-11-22: „Könnte ich meiner KI sagen: räum die Dokumente auf?“). Alles läuft
auf dem Mac, nichts geht ins Netz. **Zum Ausprobieren erst eine Kopie eines Ordners nehmen.**

1. Im Reiter „Gerät“ das Modell starten (ohne laufendes Modell macht der Reiter nichts).
2. **Ordner wählen …** — z. B. Dokumente, Downloads, ein Ordner in iCloud Drive oder auf einem USB-Stick. Nicht erlaubt: der ganze
   Benutzerordner, die Festplatte, System-/Programmordner, die Library (außer iCloud Drive / Cloud-Speicher), der Datenordner der App.
3. **Vorschlag erstellen** — die App liest je Datei Name, Typ, Größe, Datum und den Inhalt (PDF: Textebene, sonst Apples
   Texterkennung der ersten Seiten; Bilder: Texterkennung; Word/Excel/PowerPoint/OpenOffice, Text, .doc/.rtf über macOS `textutil`)
   und fragt die KI nach Zielordner und Dateinamen. Dabei wird **nichts verändert**. Läuft im Hintergrund, mit Fortschritt und
   „Abbrechen“; die KI braucht je Datei einige Sekunden. Der Vorschlag wird gemerkt (auch nach einem Neustart der App).
4. In der Liste prüfen: Zielordner und neuen Namen per Doppelklick ändern; rechts die vorgeschlagenen Ordner — dort umbenennen
   gilt für alle Dateien darin (z. B. „Rechnung“ und „Rechnungen“ zusammenlegen). „Verschieben“ ist vorgewählt, „Umbenennen“ nicht.
   „unklar“ = die KI war unsicher oder hat Unbrauchbares geantwortet → wird nicht verschoben, bis du selbst einen Ordner einträgst.
   Gleicher Inhalt (Prüfsumme) → Vorschlag Ordner „Doppelt“ (bis 0.1.20 „Doppelt?“) — die Kopie wird nur dorthin verschoben,
   nie gelöscht; der Hinweis nennt, wo die gleiche Datei liegt.
5. **Ausgewählte ausführen** — verschiebt bzw. benennt um. **Letzten Lauf rückgängig machen** stellt den Stand davor wieder her.

Sicherheitsregeln (`kai_ki/aufraeumen.py`, geprüft in `tests/test_aufraeumen.py`, `tests/test_aufraeumen_auswahl.py` und
`tests/test_aufraeumen_fenster.py`):
- Gearbeitet wird nur im gewählten Ordner und seinen Unterordnern. Verweise (Symlinks) werden nie verfolgt, versteckte Dateien und
  Pakete (.app, .photoslibrary, .pages-Ordner …) ausgelassen. Was die KI vorschlägt, wird geprüft: kein „..“, kein absoluter Pfad,
  keine versteckten Ordner, keine Paket-Endungen, höchstens 4 Ebenen; die Dateiendung bleibt immer gleich. Texte aus den Dateien
  gelten für die KI nur als Inhalt, nie als Anweisung — und selbst eine „böse“ Antwort kann nichts außerhalb des Ordners bewirken.
- **Nie löschen, nie überschreiben**: gibt es den Zielnamen schon, kommt „ (2)“, „ (3)“ … dazu. Umbenannt wird „exklusiv“
  (macOS `renamex_np` mit `RENAME_EXCL`), d. h. das System selbst verweigert das Überschreiben. Ziel auf einem anderen Laufwerk →
  ausgelassen (es wird nie kopiert).
- **Protokoll**: jede Aktion steht VOR dem Verschieben in `~/Library/Application Support/KAI-KI/aufraeumen/lauf-<Datum>.json`
  (alt → neu, Zeit, angelegte Ordner). Kann das Protokoll nicht geschrieben werden, wird nichts verschoben.
- **Rückgängig** geht rückwärts durch das Protokoll; ist ein alter Platz inzwischen belegt, kommt die Datei mit „ (2)“ daneben.
  Angelegte Ordner werden nur entfernt, wenn sie leer sind. Die früheren Läufe stehen unten im Reiter.

### In die vorhandene Ablage einsortieren (ab 0.1.21)

Es gibt **einen** Startordner (z. B. Dokumente) — alle neuen Ordner entstehen darin. Darunter steht **„Was aufräumen?“**: die losen
Dateien direkt im Startordner und je Ordner zwei Häkchen (Unterordner klappen auf).

- **Aufräumen** angehakt = unaufgeräumt: nur diese Dateien bekommen Vorschläge. Diese Ordner sind nie Ziel, die KI sieht sie nicht.
- **nichts** angehakt = die übrigen Ordner sind die **vorhandene Ablage**: dort wird nie etwas angefasst, aber hineinsortiert. Die KI
  bekommt den Ordnerbaum mit Anzahl Dateien und 2–3 Beispielnamen der neuesten Dateien je Ordner, nimmt vorhandene Ordner (auch
  Jahresordner) und übernimmt deren Namensschema; neue Ordner nur, wenn nichts passt.
- **Kein Ziel** = bleibt liegen und ist kein Ziel — die KI sieht den Ordner gar nicht (für Ordner, die erst später drankommen).
- Nichts angehakt = wie 0.1.20, der ganze Startordner wird aufgeräumt.

Beispiel: Dokumente mit „Rechnungen“, „Versicherungen“, „Boot“ und „unaufgeräumt 1“ bis „unaufgeräumt 4“. Zuerst bei „unaufgeräumt 1“
und „unaufgeräumt 2“ **Aufräumen** anhaken, bei „unaufgeräumt 3“ und „unaufgeräumt 4“ **Kein Ziel** (die kommen später). Die KI sortiert
die Dateien aus 1 und 2 nach „Rechnungen/2026“, „Versicherungen“ … ein. Eine Datei, die es in der Ablage schon gibt, kommt nach
„Doppelt“ (der Hinweis nennt z. B. „Versicherungen/Allianz Police.pdf“). Beim nächsten Mal „unaufgeräumt 3“ anhaken: Ordner, die frühere
Läufe angelegt oder befüllt haben, stehen als „aus früheren Läufen“ in der Liste und gehen der KI zuerst („hierhin bevorzugt“);
„unaufgeräumt 1“/„2“ werden, sobald sie leer sind, nicht mehr angeboten.

- Die Auswahl wird **je Startordner gemerkt**. Ein Vorschlag merkt sich, mit welcher Auswahl er gemacht wurde; Vorschläge aus 0.1.20
  lassen sich weiter laden (sie gelten für den ganzen Ordner).
- „höchstens … Dateien“ zählt nur die angehakten Ordner. Ist die Grenze erreicht: **Weitere Dateien übrig — nach dem Ausführen einfach
  noch einmal „Vorschlag erstellen“** (Erledigtes ist dann weg).
- Doppelte werden auch gegen die Ablage gesucht (Prüfsumme).
- Leere Quellordner bleiben stehen; nach dem Ausführen nennt die Meldung sie — löschen kannst du sie selbst. Rückgängig je Lauf.
- Unterordner auf einem anderen Laufwerk (eingehängt) werden ausgelassen, mit Meldung. Es gibt keinen Laufwerkswechsel mehr.
- Rechts bei den Zielordnern steht **„neu“**, wenn der Ordner beim Ausführen angelegt würde.

**Liste: Suche, Schnellfilter, Häkchen im Listenkopf**
- Suchfeld über der Liste: findet den Text in Dateiname/bisherigem Ordner, Zielordner, neuem Namen, Hinweis oder „gleiche Datei wie“.
- Schnellfilter **Alle · Doppelt · Unklar · Neuer Ordner · Bleibt** mit Anzahl („Bleibt“ = liegt schon richtig).
- Im Listenkopf je ein Häkchen **Verschieben** und **Umbenennen** (alle / keine / teils). Sie wirken **nur auf die gerade sichtbaren
  Zeilen**. Beispiel: Filter „Doppelt“ → Kopf-Häkchen „Verschieben“ aus → keine Kopie wird angefasst, alles andere bleibt wie es ist.
  Zeilen ohne Zielordner („unklar“) und „liegt schon richtig“ werden beim Anhaken übersprungen.
- Suche, Filter und alle Häkchen stehen im gemerkten Vorschlag.

## Postfach aufräumen (ab 0.1.22)

Peter 2026-11-23 („bau es direkt, am besten für alle drei Anmeldungen“): im Reiter „Aufräumen“ oben **Quelle: Postfach** wählen. Ein
E-Mail-Konto wird direkt verbunden (IMAP), die KI auf diesem Mac schlägt je Mail einen Ordner vor. Bedienung, Liste (Suche,
Schnellfilter, Häkchen „Verschieben“ im Listenkopf), Protokoll und Rückgängig sind dieselben wie bei den Dateien; Mails werden nur
verschoben, nie umbenannt.

1. Im Reiter „Gerät“ das Modell starten.
2. **Konto hinzufügen …** → Anbieter, Adresse, Anmeldung (siehe unten) → **Prüfen und speichern**: die App meldet sich einmal an und
   liest die Ordnerliste. Erst wenn das klappt, wird das Konto gespeichert.
3. **Ordner im Konto** wählen (Vorgabe INBOX), dazu „höchstens … Mails“ (Vorgabe 300), neueste oder älteste zuerst, wahlweise nur die
   letzten … Tage. **Ungelesene nicht anfassen** ist vorgewählt (ungelesene Mails bekommen keinen Vorschlag).
4. **Vorschlag erstellen** — die App liest je Mail Absender, Betreff, Datum, Text (Klartext, sonst HTML ohne Tags) und die Namen der
   Anhänge. Dabei wird **nichts verändert und nichts als gelesen markiert** (Ordner nur zum Lesen geöffnet — EXAMINE — und Mails mit
   BODY.PEEK geholt). Die KI bekommt die Ordner des Kontos mit Anzahl und Betreff der neuesten Mails, nimmt vorhandene Ordner
   (die aus früheren Läufen zuerst) und schlägt nur dann neue vor, wenn nichts passt. Gleiche **Message-ID** mehrmals → die jüngere
   Mail bekommt den Vorschlag „Doppelt“ (wird nur dorthin verschoben, nie gelöscht).
5. Liste prüfen wie bei den Dateien, dann **Ausgewählte ausführen**: verschiebt die Mails im Konto, fehlende Ordner werden angelegt.
   Häkchen **zusätzlich als .eml auf dem Mac ablegen** → vorher kommt je Mail eine Kopie als Datei in den gewählten Ordner (immer ein
   neuer Name, nie überschrieben). **Letzten Lauf rückgängig machen** holt die Mails in ihren alten Ordner zurück.

### Was du vorher einrichten musst

**iCloud** (imap.mail.me.com, Port 993, SSL): iCloud nimmt nicht das Apple-Passwort, sondern ein **app-spezifisches Passwort**:
<https://appleid.apple.com> → Anmeldung und Sicherheit → App-spezifische Passwörter → „+“ → Name „KAI KI“ → das angezeigte Passwort
(xxxx-xxxx-xxxx-xxxx) in der App eintragen. (Geht nur mit Zwei-Faktor-Authentifizierung, die bei Apple-IDs heute fast immer an ist.)
⚠️ Bleibt der Knopf „Erstellen“ hellblau (gesperrt), die Apple-Seite in **Chrome** öffnen — in Safari ging es am 23.11.2026 nicht.

**web.de** (imap.web.de, Port 993, SSL): im Browser bei web.de → E-Mail → **Einstellungen → POP3/IMAP Abruf → „POP3 und IMAP Zugriff
erlauben“** einschalten. In der App Adresse und das normale web.de-Passwort eintragen.

**Outlook.com / Live / Hotmail** (outlook.office365.com, Port 993, SSL, Anmeldung XOAUTH2): Microsoft lässt für Outlook.com kein
Passwort per IMAP mehr zu. Die App meldet sich deshalb im **Browser** bei Microsoft an (OAuth 2.0 mit PKCE, Rückruf auf
`http://localhost`, Mandant `consumers`, Berechtigungen `https://outlook.office.com/IMAP.AccessAsUser.All offline_access`) und speichert
nur den Erneuerungsschlüssel (refresh token) im Schlüsselbund. Dafür braucht es **einmalig eine eigene App-Registrierung** in Microsoft
Entra — die Client-ID eines fremden Programms wird bewusst nicht verwendet:

1. <https://entra.microsoft.com> öffnen (oder <https://portal.azure.com> → „Microsoft Entra ID“). Microsoft verlangt dafür ein
   Entra-Verzeichnis: wer keins hat, legt mit seinem Microsoft-Konto ein kostenloses Azure-Konto an (dabei entsteht ein Verzeichnis) —
   oder jemand mit Zugang zu einem Verzeichnis (z. B. die IT) legt die Registrierung an. Die Client-ID ist **kein Geheimnis** und darf
   weitergegeben werden.
2. **Anwendungen → App-Registrierungen → Neue Registrierung.** Name z. B. „KAI KI Postfach“. Unterstützte Kontotypen:
   **„Nur persönliche Microsoft-Konten“** (oder „Konten in einem beliebigen Organisationsverzeichnis und persönliche Microsoft-Konten“).
3. **Umleitungs-URI:** Plattform **„Öffentlicher Client/nativ (mobil und Desktop)“**, Adresse **`http://localhost`** (ohne Port — die
   App wählt beim Anmelden selbst einen freien Port, das lässt Microsoft für localhost zu). → **Registrieren.** Nicht die Plattform
   „Web“ nehmen (die verlangt ein Geheimnis).
4. **Authentifizierung → Erweiterte Einstellungen → „Öffentliche Clientflows zulassen“ = Ja** → Speichern.
5. **API-Berechtigungen → Berechtigung hinzufügen → Microsoft Graph → Delegierte Berechtigungen:** `IMAP.AccessAsUser.All` und
   `offline_access` → Hinzufügen. (Zustimmen musst du beim ersten Anmelden selbst — eine Administrator-Zustimmung braucht es für
   persönliche Konten nicht.)
6. **Übersicht → „Anwendungs-ID (Client)“** kopieren — das ist die **Client-ID**. In der App: Konto hinzufügen → Anbieter
   „Outlook.com / Live / Hotmail“ → Adresse + Client-ID → **Bei Microsoft anmelden und speichern** → im Browser anmelden und
   zustimmen → „Anmeldung abgeschlossen“ → zurück in die App.

Ohne Client-ID meldet die App das klar und verweist hierher (kein Fehler). Läuft die Anmeldung später ab: Konto → **Ändern …** →
neu anmelden.

**Anderer IMAP-Server:** Server, Port (meist 993 mit SSL, sonst 143 mit STARTTLS), Benutzername (meist die Adresse) und Passwort aus
der Hilfe des Anbieters.

### Sicherheitsregeln (`kai_ki/postfach.py`, geprüft in `tests/test_postfach.py` und `tests/test_aufraeumen_postfach_fenster.py`)
- **Zugangsdaten nur im macOS-Schlüsselbund** (Dienst `de.bsb.kai-ki.postfach`, `kai_ki/schluesselbund.py`) — nie in Dateien, nie
  im Protokoll. Gespeichert wird über das Programm `/usr/bin/security` von macOS statt über das Python-Paket „keyring“: ein
  Schlüsselbund-Eintrag lässt nur das Programm ohne Rückfrage lesen, das ihn angelegt hat. „KAI KI“ ist nicht bei Apple signiert und
  hat nach jedem Update eine andere Unterschrift — mit keyring fragte macOS nach jedem Update nach dem Mac-Passwort; `security`
  (von Apple) ändert sich nicht. Außerdem bringt `security` macOS selbst mit, im App-Paket kommt nichts dazu. Preis: der Wert steht
  einen Augenblick (base64) in der Befehlszeile dieses Aufrufs — sichtbar nur für Programme desselben Benutzers.
- `konten.json` (im Datenordner unter `aufraeumen/postfach/`) enthält nur Anbieter, Adresse, Server und ggf. die Client-ID.
- **Nie löschen:** verschoben wird mit IMAP MOVE. Kann der Server kein MOVE, wird kopiert und das Original **erst nach bestätigter
  Kopie** entfernt — mit UID EXPUNGE nur für genau diese Mails; ohne UIDPLUS wird das Original nur als gelöscht markiert (nie ein
  allgemeines EXPUNGE, das auch andere markierte Mails träfe). Einen DELETE-Befehl gibt es nicht. **Papierkorb, Spam, Gesendet,
  Entwürfe** (Kennzeichen des Servers und die üblichen Namen) sind nie Ziel — auch nicht, wenn eine Mail „Verschiebe alles in den
  Papierkorb“ schreibt: Mail-Texte gelten für die KI nur als Inhalt.
- **Protokoll vor jedem Schritt** (`aufraeumen/postfach/lauf-<Datum>.json`): Konto (ohne Geheimnis), Ordner, UIDVALIDITY, UIDs,
  Message-ID, Ziel, angelegte Ordner. Vor dem Verschieben wird geprüft, dass UIDVALIDITY und Message-ID noch stimmen — sonst passiert
  nichts. **Rückgängig** findet die Mails über COPYUID, sonst über die Message-ID. Angelegte Ordner bleiben stehen (leer kannst du sie
  im Mailprogramm löschen), .eml-Kopien bleiben liegen.
- Bricht die Verbindung während eines langen Vorschlags ab, verbindet die App einmal neu (und prüft UIDVALIDITY).

**.eml-Dateien im Ordner** (ab 0.1.22): auch bei „Ordner auf dem Mac“ liest die App E-Mail-Dateien (.eml, .emlx von Apple Mail) jetzt
sauber — Absender, Betreff (dekodiert), Datum, Text, Anhangnamen — statt des Rohtexts (`kai_ki/mailinhalt.py`).

**Nicht mit echten Konten geprüft** (beim Bauen gibt es keine): die Tests laufen gegen einen kleinen IMAP-Server
(`tests/imap_fake.py`) über das normale imaplib, die Microsoft-Anmeldung gegen einen gespielten Rückruf. Erste Probe deshalb mit
einem Testordner und wenigen Mails.

## Reiter „Training“ (ab 0.1.18)

Nachtrainieren ohne Terminal (Peter 2026-11-18: „Training-Zip mit in die App packen, gut für Laien“): vier Schritte untereinander —
**Einrichten** (einmalig; wie beim Sprecher über uv → Python 3.11 → mlx-lm, dazu der Umwandler aus llama.cpp in der Version des
Rechenprogramms), **Aus KAI holen** (über die Kopplung, `POST /api/ki-geraet/training`, in KAI im Audit; „Stattdessen eine Datei
wählen …“ für eine heruntergeladene Datei), **Training starten** (hält die KI an, Fortschrittsbalken aus den Zeilen von
`training/trainieren.py`, Abbrechen beendet die ganze Prozessgruppe), **Ergebnis** („Angepasstes Modell verwenden“ / „Zurück zum
Grundmodell“). Die geholten Trainingsdaten werden nach erfolgreichem Training gelöscht. Die Skripte stecken im App-Paket
(`--add-data training:training`, beim Bauen geprüft) — eine Quelle für App und Trainings-Zip.

## Eigenes Modell „KAI angepasst“ (ab 0.1.17)

Das Training im Reiter „Training“ legt das Ergebnis als `modelle/kai-eigen.gguf` ab; ab dann steht in der Modell-Auswahl
„KAI angepasst (eigenes Training, Stand …)“. Die App startet es mit `-m` statt Download und nimmt den Bildteil (mmproj) vom
Grundmodell Qwen3.5 9B — der muss also einmal geladen worden sein, sonst liest das eigene Modell nur Text. Fehlt die Datei
später, wählt die App wieder das Grundmodell. Ab 0.1.19 gibt es keine eigene Trainings-Datei mehr unter Releases — die Skripte
stecken in der App (`training/README.md`).

## Mehrere KAI zugleich (ab 0.1.14)

Es lassen sich mehrere KAI koppeln, z. B. Test (`https://kai-bsb.de/test`) und Produktion (`https://kai-bsb.de`): im Block
„Neue Verbindung koppeln“ Adresse + neuen Code aus der jeweiligen KAI (Einstellungen → Schnittstellen → KI → Gerät koppeln)
eintragen, „Koppeln“ (oder Enter im Code-Feld). Die gekoppelten stehen oben unter „Verbindungen zu KAI“. Je Verbindung holt ein eigener Ablauf die Aufträge; Modell, Sprecher und Spracherkennung laufen nur einmal und werden
geteilt. In der Liste „Erledigte Aufträge“ steht, aus welcher KAI ein Auftrag kam. Gleiche Adresse noch einmal koppeln = Gerät neu
gekoppelt; „Verbindung entfernen“ löst eine Verbindung.

## Adresse ohne https:// (ab 0.1.16)

„kai-bsb.de“ reicht: die App ergänzt `https://` selbst (vorher Fehler „MissingSchema“), Schrägstrich am Ende fällt weg.

## Fenster (ab 0.1.15)

Koppeln als eigener Block mit breiten Feldern; ist das Fenster zu niedrig, scrollt die Geräte-Seite, statt die Felder zu
stauchen (in 0.1.14 standen Adresse und Code schmal in der Mitte und waren abgeschnitten). `tests/test_fenster.py` prüft das
beim Bauen im echten macOS-Stil.

## Zahlen beim Sprechen (ab 0.1.13)

Vor dem Sprechen schreibt die App Zahlen, Beträge, Datum, Uhrzeit, Einheiten und Kürzel in Worte (`sprechtext.py`, Bibliothek
`num2words`, LGPL): „24.099.694,29 €“ → „rund vierundzwanzig Komma eins Millionen Euro“, „17.11.2026“ → „siebzehnter November
zweitausendsechsundzwanzig“, „14:10 Uhr“ → „vierzehn Uhr zehn“, „MS-STUTTGART“ → „M S Stuttgart“. Beträge ab 10.000 € und
Mengen ab 100.000 werden gerundet gesprochen. Gilt für alles, was der Mac spricht (Vorlesen in KAI, Chat-Reiter, Werbefilm).

## Chat in der App (ab 0.1.9)

Reiter „Chat“: Fragen direkt an das Modell auf diesem Mac — ohne KAI und ohne Netz, die Antwort erscheint beim Schreiben.
Eingabe wie in KAI: „+“ hängt ein Bild oder PDF an (erste Seite, mit Texterkennung), 🎙 nimmt die Frage auf (Whisper auf dem Mac,
ab 0.1.10; macOS fragt beim ersten Mal nach dem Mikrofon), „🔊 Vorlesen“ bzw. das Häkchen „Antworten vorlesen“ spricht Antworten
mit Chatterbox (eigene Stimmprobe wählbar). Das Modell muss im Reiter „Gerät“ gestartet sein. Den
Chat mit Mikrofon und KAI-Daten (nur Admin) gibt es in KAI unter Informationen → KI-Chat; dafür holt die App die Aufträge
bei KAI ab (Chat ab 0.1.7, Mikrofon/Whisper ab 0.1.8).

## Abgebrochener Download (ab 0.1.6)

Bricht der Modell-Download ab (Netz), setzt llama.cpp beim nächsten Start am angefangenen Stück fort
(`*.downloadInProgress` im Modell-Ordner, HTTP-Range) — nichts wird doppelt geladen. Die App versucht das von selbst
bis zu sechsmal; die Anzeige zählt das schon Geladene mit und beginnt nicht wieder bei 0 %.

## Sprechen (ab 0.1.5)

Zweite Auftragsart: KAI schickt einen Text, die App macht daraus eine Tonspur (WAV) — für Erklärvideos und Filme.
Modell: **Chatterbox Multilingual** (Resemble AI, MIT-Lizenz, Deutsch). Weil PyTorch für die App zu groß ist, richtet die App
beim ersten Sprechauftrag eine eigene Umgebung ein (`~/Library/Application Support/KAI-KI/sprecher`): `uv` (Astral) →
Python 3.11 → `chatterbox-tts==0.1.7`, danach lädt der Sprecher-Dienst das Modell von Hugging Face (einige GB, einmalig).
Das dauert beim ersten Mal einige Minuten; der Stand steht in KAI in der Gerätezeile. Protokoll: `sprecher/sprecher.log`.
Stimmproben (10–30 s echte deutsche Sprache) liegen in KAI (Einstellungen → Schnittstellen → KI → Sprechen) und reisen mit
dem Auftrag; ohne Probe nimmt das Modell seine Standardstimme (im Deutschen evtl. mit englischem Klang).
