# ApoFiKa Chapters

Privates Tool, das die neueste Folge von [Apokalypse & Filterkaffee](https://apokalypse-und-filterkaffee.podigee.io/feed/mp3) lädt, Thementrenner-Jingles erkennt und Kapitelmarken aus der Themenliste in der Show-Notes setzt. Anschließend wird ein lokaler RSS-Feed ausgeliefert.

Nur für privaten Gebrauch — die Original-Audio-Dateien bleiben urheberrechtlich geschützt.

## Setup

```bash
cd ApoFiKaSplit
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Workflow

### 1. Einmalig: Jingle-Referenz extrahieren

```bash
apofika download
```

Folge anhören, Startzeit eines Thementrenners notieren, dann:

```bash
apofika extract-jingle --from data/raw/<guid>.mp3 --start MM:SS --dur 3
```

Das schreibt `assets/jingle_ref.wav`.

### 2. Neueste Folge verarbeiten

```bash
apofika process
```

Optional:

- `--force` erneut verarbeiten
- `--threshold 0.55` Korrelations-Schwellwert
- `--min-distance 60` Mindestabstand zwischen Treffern (Sekunden)
- `--public-base http://192.168.x.x:8787` für Handy im WLAN

### 3. Lokalen Feed abonnieren

```bash
apofika serve --host 0.0.0.0 --port 8787
```

In der Podcast-App: `http://<mac-ip>:8787/feed.xml`

## Kapitel-Logik

- Zeitpunkte: Template-Matching (normalized cross-correlation) gegen `assets/jingle_ref.wav`
- Titel: `Intro` bei 0:00, danach Themen aus `Die Themen: …` in der Episodenbeschreibung
- Formate: ID3 `CHAP`/`CTOC` in der MP3 und `psc:chapters` im lokalen RSS

## Raspberry Pi 3B (dauerhaft)

Alles kann auf dem Pi laufen. Die Erkennung ist speicherarm (Chunk-Streaming); Dauer ist egal. Zwischen **04:00 und 07:00** prüft ein Timer alle 30 Minuten auf eine neue Folge (`process` überspringt bekannte GUIDs).

### 1. Einmalig auf dem Pi

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev ffmpeg libsndfile1 build-essential
# Zeitzone für 4–7 Uhr Lokalzeit:
sudo timedatectl set-timezone Europe/Berlin

cd ~
git clone <dein-repo-url> ApoFiKaSplit   # oder Projekt per scp/rsync kopieren
cd ApoFiKaSplit
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e .

# 2GB Swap (wichtig bei 1GB RAM)
sudo bash deploy/pi/setup-swap.sh

# Jingle-Referenz einmalig anlegen (siehe Workflow oben), dann:
sudo bash deploy/pi/install.sh
sudo nano /etc/apofika.env   # APOFIKA_PUBLIC_BASE setzen (LAN-IP oder Tunnel-URL)
sudo systemctl restart apofika-serve.service
```

### 2. Zeitplan

| Unit | Rolle |
|------|--------|
| `apofika-serve.service` | Feed + MP3s rund um die Uhr |
| `apofika-process.timer` | 04:00–06:30 alle 30 Min + 07:00 → `process` |

```bash
systemctl list-timers apofika-process.timer
sudo systemctl start apofika-process.service   # manueller Test
journalctl -u apofika-process.service -u apofika-serve.service -f
```

Optional öffentlich: Cloudflare Tunnel / Tailscale Funnel auf Port `8787`, und `APOFIKA_PUBLIC_BASE` auf die HTTPS-URL setzen, danach einmal `apofika process --force --public-base …` oder den Timer abwarten.

## Projektstruktur

```
src/apofika/     # Pipeline-Code
assets/          # jingle_ref.wav
data/raw/        # Original-Downloads
data/processed/  # MP3 mit Kapiteln + chapters.json
data/feed.xml
data/state.json
deploy/pi/       # systemd + Swap-Setup für Raspberry Pi
```

