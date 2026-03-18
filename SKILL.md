---
name: renfe-skill
description: Check RENFE Cercanías, Rodalies, and Media Distancia train schedules, delays, and service alerts using GTFS data. Use when the user asks about train times, wants to travel between stations, or needs to know about disruptions on a specific line. Classifies trains as MD (express) or R (all-stops).
---

# RENFE Cercanías / Rodalies / Media Distancia

Query RENFE commuter and regional rail schedules and realtime alerts via GTFS. Trains are automatically classified as MD (Media Distancia / express — fewer stops) or R (Rodalies / cercanías — all stops).

## Setup

Requires `uv`. Run once from the skill directory:

```bash
cd <skill_dir> && uv venv && uv pip install -e .
```

To register as a pi skill, symlink into your skills directory:

```bash
ln -s <skill_dir> ~/.pi/agent/skills/renfe-skill
```

GTFS static data is cached at `~/.cache/renfe-skill/gtfs.zip` for 1 week. First run will download ~15MB.

## Commands

All commands use `uv run renfe` from the skill directory.

### Search schedule

Find departures from origin to destination on a line. Stop names are partial matches (case-insensitive). Output includes train type (MD/R) and number of intermediate stops.

```bash
uv run --directory <skill_dir> renfe schedule --line R11 --from "Girona" --to "Sants"
uv run --directory <skill_dir> renfe schedule --line R11 --from "Sants" --to "Figueres" --after 18:00
uv run --directory <skill_dir> renfe schedule --line R11 --from "Girona" --to "Sants" --date 20260320
```

### Service alerts

Check active alerts for a line:

```bash
uv run --directory <skill_dir> renfe alerts --line R11
```

### Current delays

See realtime delays for active trips on a line:

```bash
uv run --directory <skill_dir> renfe delays --line R11
```

### List stops on a line

```bash
uv run --directory <skill_dir> renfe stops --line R11
```

### List available lines

```bash
uv run --directory <skill_dir> renfe routes
uv run --directory <skill_dir> renfe routes --nucleus Barcelona
uv run --directory <skill_dir> renfe routes --line C1
```

## Train type detection

Trains are classified as MD (express) or R (all-stops) by comparing the number of intermediate stops each trip makes against the maximum for the same origin→destination pair. Trips with fewer than 60% of the max stops are classified as MD.

The detection logic lives in `renfe_skill/train_type.py` and is pluggable — swap the strategy in the `classify()` function.

## Supported networks

Madrid, Barcelona, Rodalies Catalunya, Málaga, Sevilla, Valencia, Bilbao, Santander, Asturias, Cádiz, Murcia/Alicante, Castellón, Zaragoza.

## Tips

- Line names: Madrid/regional use C1-C10, Rodalies Catalunya uses R1-R17/RG1/RL3 etc.
- Stop name matching is partial: "Sants" matches "Barcelona-Sants", "Girona" matches "Girona".
- Use `--after HH:MM` to filter departures from a specific time onwards.
- Add `--refresh` to any command to force re-download the GTFS data.
- Use `stops` command first if unsure of exact stop names.
- MD trains are significantly faster (e.g. Sants→Girona: ~1h05 MD vs ~1h30 R).
