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

## Projektstruktur

```
src/apofika/   # Pipeline-Code
assets/        # jingle_ref.wav
data/raw/      # Original-Downloads
data/processed/# MP3 mit Kapiteln + chapters.json
data/feed.xml  # lokaler Feed
data/state.json
```
