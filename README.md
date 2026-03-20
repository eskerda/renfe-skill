# renfe-skill

<img width="49%" alt="image" src="https://github.com/user-attachments/assets/751f4631-33e8-4f84-bf79-eceaaac36e03" />
<img width="49%" alt="image" src="https://github.com/user-attachments/assets/42943380-5541-4be0-bdba-bce9493ae629" />

Query RENFE Cercanías and Rodalies train schedules and realtime alerts via GTFS.

Trains are automatically classified as express or all-stops based on their stopping pattern.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv venv && uv pip install -e .
```

## Usage

### Schedule

Search by origin and destination. Line is auto-detected when omitted.

```
$ renfe schedule --from Sants --to Girona --after 17:00 --before 21:00

Schedule for R11: Barcelona-Sants → Girona on 20260320
(after 17:00, before 21:00)

  Train   Departure   Arrival  Type    Delay
───────  ──────────  ────────  ────  ───────
  15816      *17:16     18:47     R     +11m
  15818      *17:46     19:05    MD     +16m
  15728      *18:16     19:35    MD     +34m
  34684       18:46     20:07    MD
  15820       19:16     20:47     R
  15734       19:46     21:05    MD
  34608       20:46     22:15    MD

7 trips found.
```

```bash
renfe schedule --from "Sants" --to "Sitges"            # auto-detect line
renfe schedule --line R11 --from "Sants" --to "Figueres"
renfe schedule --from "Sants" --to "Girona" --after now --before +2h
```

### Departures

All trains from a stop — like a station screen.

```
$ renfe dep --stop Sants --line R11 --after 17:00 --before 20:00

Departures from Barcelona-Sants on 20260320
(after 17:00, before 20:00)

  Train  Line   Departure    Delay  Destination
───────  ────  ──────────  ───────  ──────────────────────────────
  15816   R11      *17:16     +11m  Portbou
  15818   R11      *17:46     +16m  Portbou
  15728   R11      *18:16     +34m  Figueres
  34684   R11       18:46           Figueres
  15820   R11       19:16           Portbou
  15734   R11       19:46           Figueres

6 departures.
```

### Arrivals

All trains arriving at a stop.

```
$ renfe arr --stop Girona --line R11 --after 18:00 --before 22:00

Arrivals at Girona on 20260320
(after 18:00, before 22:00)

  Train  Line     Arrival    Delay  Origin
───────  ────  ──────────  ───────  ──────────────────────────────
  15876   R11      *18:38      +9m  Portbou
  15816   R11      *18:47     +11m  Barcelona-Sants
  15818   R11      *19:05     +16m  Barcelona-Sants
  15786   R11      *19:17      +2m  Figueres
  15728   R11      *19:35     +34m  Barcelona-Sants
  34684   R11       20:07           Barcelona-Sants
  15882   R11       20:08           Portbou
  15820   R11       20:47           Barcelona-Sants
  15788   R11       20:57           Figueres
  15734   R11       21:05           Barcelona-Sants
  15886   R11       21:17           Portbou

11 arrivals.
```

### Live positions

```
$ renfe positions --line R11

Active trains on line R11:

   Train  Status          Stop                                  Lat        Lon
────────  ──────────────  ──────────────────────────────  ─────────  ─────────
   15728  STOPPED_AT      Barcelona-El Clot                41.40904    2.18739
   15700  IN_TRANSIT_TO   Girona                           41.75203    2.65400
   15786  IN_TRANSIT_TO   Flaçà                            42.14654    2.98188
   15816  IN_TRANSIT_TO   Girona                           41.98044    2.81710
   15818  IN_TRANSIT_TO   Maçanet-Massanes                 41.77885    2.67715
   15870  STOPPED_AT      Barcelona-Sants                  41.39203    2.16466
```

### Other commands

```bash
renfe alerts --line R11                     # service alerts
renfe delays --line R11                     # current delays
renfe stops --line R11                      # list stops on a line
renfe routes                                # list all lines
renfe routes --nucleus Barcelona            # filter by network
renfe --no-rt schedule --from Sants --to Girona   # skip RT (faster, no Delay column)
```

## Time arguments

`--after` and `--before` accept: `HH:MM`, `now`, `+1h`, `-30m`, `+1h30m`

All commands show the full day unless filtered.

## Stop name matching

Stop names are partial and accent-insensitive: "Gracia" matches "Gràcia", "Macanet" matches "Maçanet".

If a query matches multiple distinct stops (e.g. "Caldes" matches both Caldes D'estrac and Caldes De Malavella), you'll be asked to be more specific.

## Data sources

- **Schedule**: [GTFS static feed](https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip) — cached as SQLite, refreshed weekly
- **Realtime**: [GTFS-RT](https://gtfsrt.renfe.com/) — vehicle positions, trip updates, service alerts

## Supported networks

Madrid, Barcelona, Rodalies Catalunya, Málaga, Sevilla, Valencia, Bilbao, Santander, Asturias, Cádiz, Murcia/Alicante, Castellón, Zaragoza.

## Agent skill

This can be used as an agent skill. It works with [pi](https://pi.dev) and should also work with [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

```bash
# pi
ln -s /path/to/renfe-skill ~/.pi/agent/skills/renfe-skill

# Claude Code
ln -s /path/to/renfe-skill ~/.claude/skills/renfe-skill
```

## License

MIT

---

Skill generated by Claude via [pi](https://pi.dev). Code their own, as-is, no guarantees.
