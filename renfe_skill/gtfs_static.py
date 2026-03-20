"""Download and query GTFS static schedule data via SQLite cache."""

import csv
import io
import os
import sqlite3
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


def _zip_path() -> Path:
    return CACHE_DIR / "gtfs.zip"


def _db_path() -> Path:
    return CACHE_DIR / "gtfs.db"


def _needs_download() -> bool:
    p = _zip_path()
    if not p.exists():
        return True
    return (time.time() - p.stat().st_mtime) > CACHE_MAX_AGE


def _needs_rebuild() -> bool:
    db = _db_path()
    zp = _zip_path()
    if not db.exists():
        return True
    return db.stat().st_mtime < zp.stat().st_mtime


def _build_db(zip_path: Path, db_path: Path) -> None:
    """Build SQLite database from GTFS zip. ~10s one-time cost."""
    import sys
    print("Building schedule database...", end=" ", flush=True, file=sys.stderr)
    start = time.time()

    # Remove stale db if exists
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    conn.executescript("""
        CREATE TABLE stops (
            stop_id TEXT PRIMARY KEY,
            stop_name TEXT,
            stop_name_norm TEXT,
            stop_lat REAL,
            stop_lon REAL
        );
        CREATE TABLE routes (
            route_id TEXT PRIMARY KEY,
            route_short_name TEXT,
            route_long_name TEXT,
            nucleus TEXT
        );
        CREATE TABLE calendar (
            service_id TEXT PRIMARY KEY,
            monday INTEGER, tuesday INTEGER, wednesday INTEGER,
            thursday INTEGER, friday INTEGER, saturday INTEGER, sunday INTEGER,
            start_date TEXT,
            end_date TEXT
        );
        CREATE TABLE trips (
            trip_id TEXT PRIMARY KEY,
            route_id TEXT,
            service_id TEXT
        );
        CREATE TABLE stop_times (
            trip_id TEXT,
            stop_id TEXT,
            arrival_time TEXT,
            departure_time TEXT,
            stop_sequence INTEGER
        );
    """)

    def _stripped_reader(zf, filename):
        """CSV reader that strips both keys and values."""
        with zf.open(filename) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))
            for row in reader:
                yield {k.strip(): v.strip() for k, v in row.items()}

    with zipfile.ZipFile(zip_path) as zf:
        # stops
        conn.executemany(
            "INSERT INTO stops VALUES (?,?,?,?,?)",
            ((r["stop_id"], r["stop_name"], _normalize(r["stop_name"]),
              float(r["stop_lat"]), float(r["stop_lon"]))
             for r in _stripped_reader(zf, "stops.txt"))
        )

        # routes
        conn.executemany(
            "INSERT INTO routes VALUES (?,?,?,?)",
            ((r["route_id"], r["route_short_name"], r["route_long_name"],
              NUCLEUS_NAMES.get(r["route_id"][:2], r["route_id"][:2]))
             for r in _stripped_reader(zf, "routes.txt"))
        )

        # calendar
        conn.executemany(
            "INSERT INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?)",
            ((r["service_id"],
              int(r["monday"]), int(r["tuesday"]), int(r["wednesday"]),
              int(r["thursday"]), int(r["friday"]), int(r["saturday"]),
              int(r["sunday"]), r["start_date"], r["end_date"])
             for r in _stripped_reader(zf, "calendar.txt"))
        )

        # trips
        conn.executemany(
            "INSERT INTO trips VALUES (?,?,?)",
            ((r["trip_id"], r["route_id"], r["service_id"])
             for r in _stripped_reader(zf, "trips.txt"))
        )

        # stop_times — the big one
        conn.executemany(
            "INSERT INTO stop_times VALUES (?,?,?,?,?)",
            ((r["trip_id"], r["stop_id"], r["arrival_time"],
              r["departure_time"], int(r["stop_sequence"]))
             for r in _stripped_reader(zf, "stop_times.txt"))
        )

    # Indexes — built after bulk insert for speed
    conn.executescript("""
        CREATE INDEX idx_stop_times_stop_id ON stop_times(stop_id);
        CREATE INDEX idx_stop_times_trip_id ON stop_times(trip_id);
        CREATE INDEX idx_trips_route_id ON trips(route_id);
        CREATE INDEX idx_trips_service_id ON trips(service_id);
        CREATE INDEX idx_routes_short_name ON routes(route_short_name);
    """)

    conn.commit()
    conn.close()

    # Set db mtime to match zip mtime
    zip_mtime = zip_path.stat().st_mtime
    os.utime(db_path, (zip_mtime, zip_mtime))

    elapsed = time.time() - start
    print(f"done ({elapsed:.1f}s)", file=sys.stderr)


def download_gtfs(force: bool = False) -> Path:
    """Download GTFS zip if stale, build SQLite DB if needed. Returns path to DB."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    zp = _zip_path()
    if force or _needs_download():
        resp = requests.get(GTFS_STATIC_URL, timeout=120)
        resp.raise_for_status()
        zp.write_bytes(resp.content)

    db = _db_path()
    if force or _needs_rebuild():
        _build_db(zp, db)

    return db


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def load_routes(db_path: Path) -> list[dict]:
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM routes").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def load_stops(db_path: Path) -> dict[str, dict]:
    conn = _connect(db_path)
    rows = conn.execute("SELECT stop_id, stop_name, stop_lat, stop_lon FROM stops").fetchall()
    conn.close()
    return {r["stop_id"]: dict(r) for r in rows}


def find_routes(db_path: Path, line: str | None = None, nucleus: str | None = None) -> list[dict]:
    """Find routes matching a line name and/or nucleus."""
    conn = _connect(db_path)
    query = "SELECT * FROM routes WHERE 1=1"
    params: list = []
    if line:
        query += " AND UPPER(route_short_name) = ?"
        params.append(line.upper())
    if nucleus:
        nuc_upper = nucleus.upper()
        query += " AND (route_id LIKE ? OR UPPER(nucleus) LIKE ?)"
        params.extend([f"{nuc_upper}%", f"%{nuc_upper}%"])
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_services(db_path: Path, date_str: str) -> set[str]:
    """Get service_ids active on a given date (YYYYMMDD)."""
    dt = datetime.strptime(date_str, "%Y%m%d")
    day_col = dt.strftime("%A").lower()
    conn = _connect(db_path)
    rows = conn.execute(
        f"SELECT service_id FROM calendar WHERE start_date <= ? AND end_date >= ? AND {day_col} = 1",
        (date_str, date_str)
    ).fetchall()
    conn.close()
    return {r["service_id"] for r in rows}


def find_trips(db_path: Path, route_ids: set[str], service_ids: set[str] | None = None) -> list[dict]:
    """Find trips for given route_ids, optionally filtered by service_ids."""
    conn = _connect(db_path)
    placeholders = ",".join("?" for _ in route_ids)
    query = f"SELECT * FROM trips WHERE route_id IN ({placeholders})"
    params = list(route_ids)
    if service_ids:
        svc_ph = ",".join("?" for _ in service_ids)
        query += f" AND service_id IN ({svc_ph})"
        params.extend(service_ids)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def find_stop_times(db_path: Path, trip_ids: set[str]) -> dict[str, list[dict]]:
    """Load stop_times grouped by trip_id."""
    conn = _connect(db_path)
    # Process in chunks to avoid SQLite variable limit
    by_trip: dict[str, list[dict]] = {}
    trip_list = list(trip_ids)
    chunk_size = 900  # SQLite limit is 999 variables
    for i in range(0, len(trip_list), chunk_size):
        chunk = trip_list[i:i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT * FROM stop_times WHERE trip_id IN ({placeholders}) ORDER BY trip_id, stop_sequence",
            chunk
        ).fetchall()
        for r in rows:
            by_trip.setdefault(r["trip_id"], []).append(dict(r))
    conn.close()
    return by_trip


def search_schedule(
    db_path: Path,
    line: str | None,
    origin: str,
    destination: str,
    date_str: str | None = None,
    after_time: str | None = None,
    before_time: str | None = None,
) -> list[dict]:
    """Search for trips from origin to destination, optionally on a specific line.

    Returns list of dicts with departure_time, arrival_time, origin_stop, dest_stop,
    trip_id, line, intermediate_stops, train_type.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    conn = _connect(db_path)
    origin_norm = _normalize(origin)
    dest_norm = _normalize(destination)

    # Find matching stop_ids
    origin_stops = conn.execute(
        "SELECT stop_id, stop_name FROM stops WHERE stop_name_norm LIKE ?",
        (f"%{origin_norm}%",)
    ).fetchall()
    dest_stops = conn.execute(
        "SELECT stop_id, stop_name FROM stops WHERE stop_name_norm LIKE ?",
        (f"%{dest_norm}%",)
    ).fetchall()

    if not origin_stops or not dest_stops:
        conn.close()
        return []

    origin_ids = {r["stop_id"] for r in origin_stops}
    dest_ids = {r["stop_id"] for r in dest_stops}
    origin_names = {r["stop_id"]: r["stop_name"] for r in origin_stops}
    dest_names = {r["stop_id"]: r["stop_name"] for r in dest_stops}

    # Get active services
    dt = datetime.strptime(date_str, "%Y%m%d")
    day_col = dt.strftime("%A").lower()
    services = conn.execute(
        f"SELECT service_id FROM calendar WHERE start_date <= ? AND end_date >= ? AND {day_col} = 1",
        (date_str, date_str)
    ).fetchall()
    service_ids = {r["service_id"] for r in services}

    if not service_ids:
        conn.close()
        return []

    # Build the trip filter: active services + optional line filter
    svc_ph = ",".join("?" for _ in service_ids)
    if line:
        trip_query = f"""
            SELECT t.trip_id, r.route_short_name as line
            FROM trips t
            JOIN routes r ON t.route_id = r.route_id
            WHERE t.service_id IN ({svc_ph})
            AND UPPER(r.route_short_name) = ?
        """
        trip_params = list(service_ids) + [line.upper()]
    else:
        trip_query = f"""
            SELECT t.trip_id, r.route_short_name as line
            FROM trips t
            JOIN routes r ON t.route_id = r.route_id
            WHERE t.service_id IN ({svc_ph})
        """
        trip_params = list(service_ids)

    trip_rows = conn.execute(trip_query, trip_params).fetchall()
    trip_to_line = {r["trip_id"]: r["line"] for r in trip_rows}

    if not trip_to_line:
        conn.close()
        return []

    # Find trips that pass through both origin and destination stops
    # Use SQL to find matching pairs efficiently
    origin_ph = ",".join("?" for _ in origin_ids)
    dest_ph = ",".join("?" for _ in dest_ids)
    trip_list = list(trip_to_line.keys())

    results = []
    chunk_size = 500
    for i in range(0, len(trip_list), chunk_size):
        chunk = trip_list[i:i + chunk_size]
        trip_ph = ",".join("?" for _ in chunk)

        # Get origin stop_times
        origin_rows = conn.execute(
            f"""SELECT trip_id, stop_id, departure_time, stop_sequence
                FROM stop_times
                WHERE trip_id IN ({trip_ph}) AND stop_id IN ({origin_ph})""",
            chunk + list(origin_ids)
        ).fetchall()

        # Get destination stop_times
        dest_rows = conn.execute(
            f"""SELECT trip_id, stop_id, arrival_time, stop_sequence
                FROM stop_times
                WHERE trip_id IN ({trip_ph}) AND stop_id IN ({dest_ph})""",
            chunk + list(dest_ids)
        ).fetchall()

        # Build lookup: trip_id -> (earliest origin, latest dest)
        trip_origin: dict[str, dict] = {}
        for r in origin_rows:
            tid = r["trip_id"]
            if tid not in trip_origin or r["stop_sequence"] < trip_origin[tid]["stop_sequence"]:
                trip_origin[tid] = dict(r)

        trip_dest: dict[str, dict] = {}
        for r in dest_rows:
            tid = r["trip_id"]
            if tid not in trip_dest or r["stop_sequence"] > trip_dest[tid]["stop_sequence"]:
                trip_dest[tid] = dict(r)

        # Match trips where origin comes before destination
        for tid in trip_origin:
            if tid not in trip_dest:
                continue
            o = trip_origin[tid]
            d = trip_dest[tid]
            if o["stop_sequence"] >= d["stop_sequence"]:
                continue

            dep = o["departure_time"]
            if after_time and dep[:5] < after_time:
                continue
            if before_time and dep[:5] > before_time:
                continue

            intermediate_stops = d["stop_sequence"] - o["stop_sequence"] - 1

            results.append({
                "trip_id": tid,
                "line": trip_to_line[tid],
                "departure_time": dep,
                "arrival_time": d["arrival_time"],
                "origin_stop": origin_names.get(o["stop_id"], o["stop_id"]),
                "destination_stop": dest_names.get(d["stop_id"], d["stop_id"]),
                "origin_stop_id": o["stop_id"],
                "destination_stop_id": d["stop_id"],
                "intermediate_stops": intermediate_stops,
            })

    conn.close()

    # Classify train types — per line
    if results:
        from .train_type import classify
        by_line: dict[str, list[dict]] = {}
        for r in results:
            by_line.setdefault(r["line"], []).append(r)
        for line_results in by_line.values():
            max_stops = max(r["intermediate_stops"] for r in line_results)
            for r in line_results:
                r["train_type"] = classify(r["intermediate_stops"], max_stops).value

    results.sort(key=lambda r: r["departure_time"])
    return results


def _search_stop_board(
    db_path: Path,
    stop: str,
    mode: str,  # "departures" or "arrivals"
    line: str | None = None,
    date_str: str | None = None,
    after_time: str | None = None,
    before_time: str | None = None,
) -> list[dict]:
    """Shared logic for departures/arrivals board.

    mode="departures": exclude trips ending at this stop, show final stop as destination.
    mode="arrivals": exclude trips starting at this stop, show first stop as origin.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    conn = _connect(db_path)
    stop_norm = _normalize(stop)

    stop_rows = conn.execute(
        "SELECT stop_id, stop_name FROM stops WHERE stop_name_norm LIKE ?",
        (f"%{stop_norm}%",)
    ).fetchall()
    if not stop_rows:
        conn.close()
        return []

    stop_ids = {r["stop_id"] for r in stop_rows}
    stop_name = stop_rows[0]["stop_name"]

    dt = datetime.strptime(date_str, "%Y%m%d")
    day_col = dt.strftime("%A").lower()
    services = conn.execute(
        f"SELECT service_id FROM calendar WHERE start_date <= ? AND end_date >= ? AND {day_col} = 1",
        (date_str, date_str)
    ).fetchall()
    service_ids = {r["service_id"] for r in services}
    if not service_ids:
        conn.close()
        return []

    svc_ph = ",".join("?" for _ in service_ids)
    if line:
        trip_query = f"""
            SELECT t.trip_id, r.route_short_name as line
            FROM trips t JOIN routes r ON t.route_id = r.route_id
            WHERE t.service_id IN ({svc_ph}) AND UPPER(r.route_short_name) = ?
        """
        trip_params = list(service_ids) + [line.upper()]
    else:
        trip_query = f"""
            SELECT t.trip_id, r.route_short_name as line
            FROM trips t JOIN routes r ON t.route_id = r.route_id
            WHERE t.service_id IN ({svc_ph})
        """
        trip_params = list(service_ids)

    trip_rows = conn.execute(trip_query, trip_params).fetchall()
    trip_to_line = {r["trip_id"]: r["line"] for r in trip_rows}
    if not trip_to_line:
        conn.close()
        return []

    stop_ph = ",".join("?" for _ in stop_ids)
    trip_list = list(trip_to_line.keys())

    if mode == "departures":
        seq_filter = "<"
        seq_func = "MAX"
        time_col = "departure_time"
    else:  # arrivals
        seq_filter = ">"
        seq_func = "MIN"
        time_col = "arrival_time"

    results = []
    chunk_size = 500
    for i in range(0, len(trip_list), chunk_size):
        chunk = trip_list[i:i + chunk_size]
        trip_ph = ",".join("?" for _ in chunk)

        # Get time at this stop, excluding terminal stops
        rows = conn.execute(
            f"""SELECT st.trip_id, st.{time_col}, st.stop_sequence
                FROM stop_times st
                WHERE st.trip_id IN ({trip_ph}) AND st.stop_id IN ({stop_ph})
                AND st.stop_sequence {seq_filter} (
                    SELECT {seq_func}(stop_sequence) FROM stop_times WHERE trip_id = st.trip_id
                )""",
            chunk + list(stop_ids)
        ).fetchall()

        if not rows:
            continue

        # Get the other end: final stop for departures, first stop for arrivals
        matching_tids = list({r["trip_id"] for r in rows})
        mtid_ph = ",".join("?" for _ in matching_tids)
        if mode == "departures":
            end_func, end_col = "MAX", "stop_name"
        else:
            end_func, end_col = "MIN", "stop_name"

        end_rows = conn.execute(
            f"""SELECT st.trip_id, s.stop_name
                FROM stop_times st
                JOIN stops s ON st.stop_id = s.stop_id
                WHERE st.trip_id IN ({mtid_ph})
                AND st.stop_sequence = (
                    SELECT {end_func}(stop_sequence) FROM stop_times WHERE trip_id = st.trip_id
                )""",
            matching_tids
        ).fetchall()

        end_by_trip = {r["trip_id"]: r["stop_name"] for r in end_rows}

        for r in rows:
            tid = r["trip_id"]
            t = r[time_col]

            if after_time and t[:5] < after_time:
                continue
            if before_time and t[:5] > before_time:
                continue

            entry = {
                "trip_id": tid,
                "line": trip_to_line[tid],
                "time": t,
                "stop_name": stop_name,
            }
            if mode == "departures":
                entry["destination"] = end_by_trip.get(tid, "?")
            else:
                entry["origin"] = end_by_trip.get(tid, "?")

            results.append(entry)

    conn.close()
    results.sort(key=lambda r: r["time"])
    return results


def search_departures(
    db_path: Path,
    stop: str,
    line: str | None = None,
    date_str: str | None = None,
    after_time: str | None = None,
    before_time: str | None = None,
) -> list[dict]:
    """List all departures from a stop."""
    return _search_stop_board(db_path, stop, "departures", line, date_str, after_time, before_time)


def search_arrivals(
    db_path: Path,
    stop: str,
    line: str | None = None,
    date_str: str | None = None,
    after_time: str | None = None,
    before_time: str | None = None,
) -> list[dict]:
    """List all arrivals at a stop."""
    return _search_stop_board(db_path, stop, "arrivals", line, date_str, after_time, before_time)
