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

GTFS static data is cached as a SQLite database at `~/.cache/renfe-skill/gtfs.db` (built from the GTFS zip on first run, ~5s). The zip is refreshed weekly. First run will download ~15MB.

## Commands

All commands use `uv run renfe` from the skill directory.

### Search schedule

Find departures from origin to destination. Line is optional — when omitted, all lines serving both stops are shown.

```bash
uv run --directory <skill_dir> renfe schedule --from "Sants" --to "Sitges"
uv run --directory <skill_dir> renfe schedule --line R11 --from "Girona" --to "Sants"
uv run --directory <skill_dir> renfe schedule --line R11 --from "Sants" --to "Figueres" --after 18:00
uv run --directory <skill_dir> renfe schedule --from "Sants" --to "Girona" --after now --before +2h
uv run --directory <skill_dir> renfe schedule --from "Sants" --to "Caldes" --date 20260320
```

### Station departures board

All trains departing from a stop, with destination — like a station screen.

```bash
uv run --directory <skill_dir> renfe departures --stop "Sants"
uv run --directory <skill_dir> renfe dep --stop "Sants" --line R11
uv run --directory <skill_dir> renfe dep --stop "Sants" --after +1h --before +3h
```

### Station arrivals board

All trains arriving at a stop, with origin.

```bash
uv run --directory <skill_dir> renfe arrivals --stop "Sants"
uv run --directory <skill_dir> renfe arr --stop "Sants" --line R11
uv run --directory <skill_dir> renfe arr --stop "Sants" --before +2h
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

### Live train positions

See where trains are right now:

```bash
uv run --directory <skill_dir> renfe positions --line R11
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

## Global flags

- `--refresh` — Force re-download GTFS data and rebuild the database.
- `--no-rt` — Skip realtime delay lookups (faster, schedule-only output without Delay column).

## Train type detection

Trains are classified as MD (express) or R (all-stops) by comparing the number of intermediate stops each trip makes against the maximum for the same origin→destination pair. Trips with fewer than 60% of the max stops are classified as MD.

The detection logic lives in `renfe_skill/train_type.py` and is pluggable — swap the strategy in the `classify()` function.

## Stop name matching

Stop names are matched case-insensitively with accent normalization. Partial matches work: "Sants" matches "Barcelona-Sants", "Gracia" matches "Barcelona-Passeig De Gràcia", "Macanet" matches "Maçanet-Massanes".

## Supported networks

Madrid, Barcelona, Rodalies Catalunya, Málaga, Sevilla, Valencia, Bilbao, Santander, Asturias, Cádiz, Murcia/Alicante, Castellón, Zaragoza.

## Time arguments

`--after` and `--before` accept:
- `HH:MM` — absolute time (e.g. `18:00`)
- `now` — current time
- `+1h`, `+30m`, `+1h30m` — relative to now

All commands show the full day unless filtered with `--after` / `--before`.

## Tips

- Line names: Madrid/regional use C1-C10, Rodalies Catalunya uses R1-R17/RG1/RL3 etc.
- Use `stops` command first if unsure of exact stop names.
- The train number shown in output is the common key across all commands — use it to cross-reference schedule → positions → delays.
- MD trains are significantly faster (e.g. Sants→Girona: ~1h05 MD vs ~1h30 R).
