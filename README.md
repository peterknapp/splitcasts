# Splitcasts

Privates Tool / WebApp zum Nachträglichen Setzen von Podcast-Kapitelmarken anhand kurzer Musikeinspieler (Jingles). Läuft unter `https://splitcasts.peterknapp.de`.

Nur für privaten Gebrauch — Original-Audio bleibt urheberrechtlich geschützt.

## Features

- Passwortgeschützte Admin-UI
- Mehrere Quell-Podcasts
- Bis zu 3 Jingle-Snippets pro Feed
- Detailansicht: letzte 5 Folgen + Split-Status
- Pro Podcast ein öffentlicher Output-Feed (`/feeds/{slug}.xml`)
- Max. 3 physische Episoden pro Feed (ältere werden gelöscht)
- Timer 04:00–07:00 prüft alle aktiven Feeds

## Setup (lokal)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
apofika migrate          # ApoFiKa-Feed + Legacy-Dateien übernehmen
apofika hash-password    # Hash für SPLITCASTS_PASSWORD_HASH
apofika serve --host 127.0.0.1 --port 8787
```

Login: Passwort aus Env (`SPLITCASTS_PASSWORD` / Hash) — Dev-Fallback: `splitcasts`.

## Wichtige URLs

| URL | Zweck |
|-----|--------|
| `/` | Admin (Login) |
| `/feeds/{slug}` | Feed-Detail, Snippets, Process |
| `/feeds/{slug}.xml` | Öffentlicher Kapitel-Feed |
| `/media/{slug}/{file}.mp3` | Audio |

## Raspberry Pi

Siehe `deploy/pi/`. Nach Code-Update:

```bash
cd ~/ApoFiKaSplit
# rsync vom Mac, dann:
source .venv/bin/activate
pip install -e .
apofika migrate
sudo nano /etc/apofika.env   # SPLITCASTS_PUBLIC_BASE + Passwort
sudo systemctl restart apofika-serve.service
sudo systemctl restart apofika-process.timer
```

Timer ruft `apofika process-all` auf.

## CLI

```bash
apofika migrate
apofika process-all
apofika hash-password
apofika serve
```
