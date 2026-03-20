"""Download and query GTFS static schedule data."""

import csv
import io
import os
import time
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

import requests

from .config import GTFS_STATIC_URL, NUCLEUS_NAMES


def _normalize(text: str) -> str:
    """Normalize text for accent-insensitive, case-insensitive matching."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.upper()

CACHE_DIR = Path(os.environ.get("RENFE_CACHE_DIR", Path.home() / ".cache" / "renfe-skill"))
CACHE_MAX_AGE = 3600 * 24 * 7  # 1 week


def _cache_path() -> Path:
    return CACHE_DIR / "gtfs.zip"


def _needs_refresh() -> bool:
    p = _cache_path()
    if not p.exists():
        return True
    age = time.time() - p.stat().st_mtime
    return age > CACHE_MAX_AGE


def download_gtfs(force: bool = False) -> Path:
    """Download GTFS zip if stale or missing. Returns path to zip."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path()
    if force or _needs_refresh():
        resp = requests.get(GTFS_STATIC_URL, timeout=120)
        resp.raise_for_status()
        p.write_bytes(resp.content)
    return p


def _read_csv_stripped(zf: zipfile.ZipFile, filename: str):
    """Yield dicts from a CSV inside the zip, stripping all keys and values."""
    with zf.open(filename) as f:
        text = io.TextIOWrapper(f, encoding="utf-8-sig")
        header = text.readline()
        cols = [c.strip() for c in header.split(",")]
        for line in text:
            vals = [v.strip() for v in line.split(",")]
            yield dict(zip(cols, vals))


def load_routes(zip_path: Path) -> list[dict]:
    with zipfile.ZipFile(zip_path) as zf:
        routes = list(_read_csv_stripped(zf, "routes.txt"))
    for r in routes:
        prefix = r["route_id"][:2]
        r["nucleus"] = NUCLEUS_NAMES.get(prefix, prefix)
    return routes


def load_stops(zip_path: Path) -> dict[str, dict]:
    with zipfile.ZipFile(zip_path) as zf:
        return {r["stop_id"]: r for r in _read_csv_stripped(zf, "stops.txt")}


def find_routes(zip_path: Path, line: str | None = None, nucleus: str | None = None) -> list[dict]:
    """Find routes matching a line name (e.g. 'R11') and/or nucleus (e.g. 'Barcelona' or '51')."""
    routes = load_routes(zip_path)
    results = []
    for r in routes:
        if line and r["route_short_name"].upper() != line.upper():
            continue
        if nucleus:
            nuc_upper = nucleus.upper()
            prefix = r["route_id"][:2]
            if nuc_upper != prefix and nuc_upper not in r["nucleus"].upper():
                continue
        results.append(r)
    return results


def get_active_services(zip_path: Path, date_str: str) -> set[str]:
    """Get service_ids active on a given date (YYYYMMDD)."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    day_name = dt.strftime("%A").lower()

    with zipfile.ZipFile(zip_path) as zf:
        active = set()
        for row in _read_csv_stripped(zf, "calendar.txt"):
            start = row["start_date"]
            end = row["end_date"]
            if start <= date_str <= end and row.get(day_name, "0") == "1":
                active.add(row["service_id"])
    return active


def find_trips(zip_path: Path, route_ids: set[str], service_ids: set[str] | None = None) -> list[dict]:
    """Find trips for given route_ids, optionally filtered by active service_ids."""
    trips = []
    with zipfile.ZipFile(zip_path) as zf:
        for row in _read_csv_stripped(zf, "trips.txt"):
            if row["route_id"] in route_ids:
                if service_ids is None or row["service_id"] in service_ids:
                    trips.append(row)
    return trips


def find_stop_times(zip_path: Path, trip_ids: set[str]) -> dict[str, list[dict]]:
    """Load stop_times grouped by trip_id for the given trips."""
    by_trip: dict[str, list[dict]] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for row in _read_csv_stripped(zf, "stop_times.txt"):
            if row["trip_id"] in trip_ids:
                by_trip.setdefault(row["trip_id"], []).append(row)
    # Sort each trip's stops by sequence
    for stops in by_trip.values():
        stops.sort(key=lambda s: int(s["stop_sequence"]))
    return by_trip


def search_schedule(
    zip_path: Path,
    line: str,
    origin: str,
    destination: str,
    date_str: str | None = None,
    after_time: str | None = None,
) -> list[dict]:
    """Search for trips on a line from origin to destination.

    Args:
        line: Line short name, e.g. "R11"
        origin: Partial stop name match, e.g. "Girona"
        destination: Partial stop name match, e.g. "Sants"
        date_str: YYYYMMDD, defaults to today
        after_time: HH:MM, only show departures after this time

    Returns:
        List of dicts with departure_time, arrival_time, origin_stop, dest_stop, trip_id
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    # Find matching routes
    routes = find_routes(zip_path, line=line)
    if not routes:
        return []
    route_ids = {r["route_id"] for r in routes}

    # Active services for the date
    services = get_active_services(zip_path, date_str)
    if not services:
        return []

    # Trips on those routes for that day
    trips = find_trips(zip_path, route_ids, services)
    if not trips:
        return []
    trip_ids = {t["trip_id"] for t in trips}

    # Load stop names for matching
    stops = load_stops(zip_path)

    # Load stop_times
    all_stop_times = find_stop_times(zip_path, trip_ids)

    origin_norm = _normalize(origin)
    dest_norm = _normalize(destination)

    results = []
    for trip_id, stop_times in all_stop_times.items():
        # Find origin and destination stops in this trip
        origin_st = None
        dest_st = None
        for st in stop_times:
            name = _normalize(stops.get(st["stop_id"], {}).get("stop_name", ""))
            if origin_norm in name and origin_st is None:
                origin_st = st
            if dest_norm in name and origin_st is not None:
                dest_st = st
                break

        if origin_st and dest_st:
            dep = origin_st["departure_time"]
            arr = dest_st["arrival_time"]

            if after_time:
                # Compare HH:MM
                if dep[:5] < after_time:
                    continue

            # Count intermediate stops between origin and destination
            origin_seq = int(origin_st["stop_sequence"])
            dest_seq = int(dest_st["stop_sequence"])
            intermediate_stops = dest_seq - origin_seq - 1

            results.append({
                "trip_id": trip_id,
                "departure_time": dep,
                "arrival_time": arr,
                "origin_stop": stops.get(origin_st["stop_id"], {}).get("stop_name", origin_st["stop_id"]),
                "destination_stop": stops.get(dest_st["stop_id"], {}).get("stop_name", dest_st["stop_id"]),
                "origin_stop_id": origin_st["stop_id"],
                "destination_stop_id": dest_st["stop_id"],
                "intermediate_stops": intermediate_stops,
            })

    # Classify train types based on intermediate stop counts
    if results:
        from .train_type import classify
        max_stops = max(r["intermediate_stops"] for r in results)
        for r in results:
            r["train_type"] = classify(r["intermediate_stops"], max_stops).value

    results.sort(key=lambda r: r["departure_time"])
    return results
