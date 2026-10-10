# Splitcasts

Web-App und CLI, um **Kapitelmarken in Podcast-Folgen** zu setzen – anhand kurzer Musikeinspieler (Jingles). Du lädst den Original-RSS eines Podcasts, hinterlegst bis zu drei Jingle-Snippets, und bekommst einen eigenen Output-Feed mit Kapiteln (ID3 `CHAP` + Podcast Chapters / PSC), den Apps wie Overcast verstehen.

Typischer Einsatz: privat auf dem eigenen Rechner oder einem Raspberry Pi, optional hinter Cloudflare Tunnel für öffentliche HTTPS-Feed-URLs.

> **Hinweis:** Original-Audio bleibt urheberrechtlich geschützt. Dieses Projekt ist zum privaten/eigenen Gebrauch gedacht – nicht zum Weiterveröffentlichen fremder Podcasts.

## Was die App kann

- Passwortgeschützte Admin-UI
- Mehrere Quell-Podcasts (pro Feed ein Slug)
- Bis zu 3 Jingle-Snippets pro Feed (Upload oder Schnitt aus einer Folge)
- Jingle-Editor: Startzeit + Dauer wählen, WAV-Vorschau hören, in Slot speichern
- Detailansicht: letzte Folgen + Split-Status
- Pro Podcast ein Output-Feed: `/feeds/{slug}.xml`
- Max. 3 physische Episoden pro Feed (ältere Dateien werden gelöscht)
- Optionaler Timer (z. B. 04:00–07:00) für `process-all`

## Voraussetzungen

- **Python 3.11+**
- macOS oder Linux (Raspberry Pi OS ok)
- Für Audioverarbeitung: die Python-Abhängigkeiten aus `pyproject.toml` (u. a. `librosa`, `soundfile`, `numpy`, `scipy`)
- Optional: öffentlicher Hostname / Tunnel, wenn Podcast-Apps von außen auf den Feed zugreifen sollen

## Lokal starten (schnell)

```bash
git clone https://origin.cursor.com/peter-knapp/splitcasts.git Splitcasts
cd Splitcasts

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .

# Optional: sicheres Admin-Passwort als Hash
apofika hash-password
# → Ausgabe in SPLITCASTS_PASSWORD_HASH setzen

export SPLITCASTS_PASSWORD=dein-passwort   # oder Hash statt Klartext
export SPLITCASTS_SESSION_SECRET=$(openssl rand -hex 32)
export SPLITCASTS_PUBLIC_BASE=http://127.0.0.1:8787

apofika serve --host 127.0.0.1 --port 8787
```

Dann im Browser: [http://127.0.0.1:8787](http://127.0.0.1:8787)

Ohne gesetztes Passwort gilt der Dev-Fallback `splitcasts` (nur lokal, nie im Internet lassen).

### Erster Feed

1. Einloggen
2. Neuen Feed anlegen (Quell-RSS-URL) → Slug wird vergeben
3. Auf der Feed-Detailseite Jingle(s) hochladen **oder** mit dem Editor aus einer Folge schneiden
4. „Process“ / warten auf Worker → Status der Folgen prüfen
5. Output-Feed in der Podcast-App abonnieren:  
   `{PUBLIC_BASE}/feeds/{slug}.xml`

### Wichtige Umgebungsvariablen

| Variable | Zweck |
|----------|--------|
| `SPLITCASTS_PASSWORD` / `SPLITCASTS_PASSWORD_HASH` | Admin-Login |
| `SPLITCASTS_SESSION_SECRET` | Cookie-Signierung (in Produktion setzen) |
| `SPLITCASTS_PUBLIC_BASE` | Basis-URL in Enclosure-Links (muss für Apps erreichbar sein) |
| `SPLITCASTS_DB` | Optionaler Pfad zur SQLite-DB |
| `APOFIKA_HOME` | Projektwurzel (v. a. auf dem Pi) |

Beispiel für Produktion: `deploy/pi/apofika.env.example`.

## Wichtige URLs

| URL | Zweck |
|-----|--------|
| `/` | Admin (Login) |
| `/feeds/{slug}` | Feed-Detail, Snippets, Process, Jingle-Editor |
| `/feeds/{slug}.xml` | Öffentlicher Kapitel-Feed |
| `/media/{slug}/{file}.mp3` | Verarbeitetes Audio |

## CLI

```bash
apofika serve              # Web-UI
apofika process-all        # alle aktiven Feeds verarbeiten
apofika hash-password      # Passwort-Hash erzeugen
apofika migrate            # Legacy-/ApoFiKa-Daten übernehmen (falls vorhanden)
apofika extract-jingle     # Jingle per CLI aus MP3 schneiden
```

## Raspberry Pi / Dauerbetrieb

Siehe `deploy/pi/` (systemd-Units, Timer, Cloudflare-Tunnel-Beispiele).

Kurz nach Code-Update:

```bash
cd ~/ApoFiKaSplit   # oder dein Clone-Pfad
source .venv/bin/activate
pip install -e .
sudo systemctl restart apofika-serve.service
sudo systemctl restart apofika-process.timer
```

`SPLITCASTS_PUBLIC_BASE` muss die öffentliche HTTPS-URL sein (z. B. Tunnel), sonst können Apps die Enclosures oft nicht laden.

## Projektstruktur (Kurz)

```
src/apofika/     # App (Web, Worker, Detection, RSS, Templates)
deploy/pi/       # systemd + Tunnel-Beispiele
tests/           # pytest
data/            # lokal erzeugt (DB, Roh-/Output-Audio) – nicht im Repo
```

## Entwicklung

```bash
source .venv/bin/activate
pip install -e .
pytest
```

## Lizenz / Nutzung

Kein Weitervertrieb fremder Podcast-Inhalte. Nutze die Output-Feeds nur im Rahmen dessen, was für dich rechtlich ok ist (typischerweise privates Abonnement / eigene Geräte).
