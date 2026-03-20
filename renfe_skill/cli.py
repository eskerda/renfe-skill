"""RENFE Cercanías CLI — schedule lookups and service alerts."""

import argparse
import sys
from datetime import datetime

from .gtfs_static import download_gtfs, find_routes, find_trips, get_active_services, load_stops, search_schedule, search_departures, search_arrivals
from .gtfs_rt import get_alerts, get_trip_updates, get_vehicle_positions


def _get_train_numbers_for_lines(db_path, lines: set[str], services: set[str]) -> set[str]:
    """Extract train numbers for multiple lines from GTFS static trips in one query.

    Maps trip_ids like '5173X15778R11' to train numbers like '15778'.
    """
    all_routes = []
    for ln in lines:
        all_routes.extend(find_routes(db_path, line=ln))
    if not all_routes:
        return set()

    route_ids = {r["route_id"] for r in all_routes}
    trips = find_trips(db_path, route_ids, services)

    # Build short_name set for splitting
    short_names = {r["route_short_name"] for r in all_routes}

    train_numbers = set()
    for t in trips:
        tid = t["trip_id"]
        for short in short_names:
            if short in tid:
                num = tid.split(short)[0]
                for s in services:
                    if num.startswith(s):
                        num = num[len(s):]
                        break
                if num:
                    train_numbers.add(num)
    return train_numbers


def _match_rt_entities(entities: list[dict], lines: set[str], train_numbers: set[str]) -> list[dict]:
    """Filter RT entities by line names in trip_id (cercanías) or train number prefix (LD)."""
    lines_upper = {ln.upper() for ln in lines}
    results = []
    for e in entities:
        tid = e["trip_id"]
        tid_upper = tid.upper()
        if any(ln in tid_upper for ln in lines_upper):
            results.append(e)
        elif any(tid.startswith(num) for num in train_numbers):
            results.append(e)
    return results


def _parse_time_arg(value: str | None, default: str | None = None) -> str | None:
    """Parse a time argument: HH:MM, 'now', or relative like +1h, +30m, +1h30m.

    Returns HH:MM string or None.
    """
    if value is None:
        return default
    value = value.strip().lower()
    if value == "now":
        return datetime.now().strftime("%H:%M")
    if value.startswith("+"):
        import re
        match = re.match(r'\+(?:(\d+)h)?(?:(\d+)m)?$', value)
        if not match:
            raise ValueError(f"Invalid relative time: {value}. Use +1h, +30m, +1h30m")
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        from datetime import timedelta
        t = datetime.now() + timedelta(hours=hours, minutes=minutes)
        return t.strftime("%H:%M")
    # Assume HH:MM
    return value


def _fetch_delays(db_path, lines: set[str], date_str: str, skip_rt: bool = False) -> tuple[dict[str, int], set[str]]:
    """Fetch RT delays for a set of lines. Returns (delay_by_train, train_numbers).

    Train numbers are always resolved (for display). RT HTTP calls are skipped if skip_rt=True.
    """
    services = get_active_services(db_path, date_str)
    train_numbers = _get_train_numbers_for_lines(db_path, lines, services)
    if skip_rt:
        return {}, train_numbers
    delays = _match_rt_entities(get_trip_updates(), lines, train_numbers)
    delay_by_train: dict[str, int] = {}
    for d in delays:
        lbl = _train_label(d["trip_id"], train_numbers)
        delay_by_train[lbl] = d["delay_seconds"]
    return delay_by_train, train_numbers


def _train_label(trip_id: str, train_numbers: set[str]) -> str:
    """Extract a human-readable train number from a trip_id."""
    for num in sorted(train_numbers, key=len, reverse=True):
        if num in trip_id:
            return num
    for num in sorted(train_numbers, key=len, reverse=True):
        if trip_id.startswith(num):
            return num
    return trip_id


def cmd_schedule(args):
    """Search schedule: departures from origin to destination on a line."""
    zip_path = download_gtfs(force=args.refresh)

    date_str = args.date or datetime.now().strftime("%Y%m%d")
    after_time = _parse_time_arg(args.after)
    before_time = _parse_time_arg(args.before)
    line = args.line or None

    results = search_schedule(
        zip_path,
        line=line,
        origin=args.origin,
        destination=args.destination,
        date_str=date_str,
        after_time=after_time,
        before_time=before_time,
    )

    if not results:
        line_str = f" on {line}" if line else ""
        print(f"No trips found from '{args.origin}' to '{args.destination}'{line_str} on {date_str}")
        return

    lines_in_results = {r["line"] for r in results}
    delay_by_train, all_train_numbers = _fetch_delays(zip_path, lines_in_results, date_str, skip_rt=args.no_rt)

    multi_line = len(lines_in_results) > 1
    header_line = ", ".join(sorted(lines_in_results)) if multi_line else results[0].get("line", "")
    print(f"Schedule for {header_line}: {results[0]['origin_stop']} → {results[0]['destination_stop']} on {date_str}")
    time_filter = ""
    if after_time:
        time_filter += f"after {after_time}"
    if before_time:
        time_filter += f"{', ' if time_filter else ''}before {before_time}"
    if time_filter:
        print(f"({time_filter})")
    print()

    rt = not args.no_rt
    if multi_line:
        hdr = f"{'Train':>7}  {'Line':>4}  {'Departure':>10}  {'Arrival':>8}  {'Type':>4}"
        sep = f"{'─' * 7}  {'─' * 4}  {'─' * 10}  {'─' * 8}  {'─' * 4}"
    else:
        hdr = f"{'Train':>7}  {'Departure':>10}  {'Arrival':>8}  {'Type':>4}"
        sep = f"{'─' * 7}  {'─' * 10}  {'─' * 8}  {'─' * 4}"
    if rt:
        hdr += f"  {'Delay':>7}"
        sep += f"  {'─' * 7}"
    print(hdr)
    print(sep)

    for r in results:
        tt = r.get('train_type', '?')
        label = _train_label(r["trip_id"], all_train_numbers)
        delay_s = delay_by_train.get(label)
        dep = r["departure_time"][:5]
        arr = r["arrival_time"][:5]

        delay_str = ""
        if rt and delay_s and delay_s != 0:
            delay_min = delay_s / 60
            sign = "+" if delay_s > 0 else ""
            delay_str = f"{sign}{delay_min:.0f}m"
            dep = f"*{dep}"

        if multi_line:
            row = f"{label:>7}  {r['line']:>4}  {dep:>10}  {arr:>8}  {tt:>4}"
        else:
            row = f"{label:>7}  {dep:>10}  {arr:>8}  {tt:>4}"
        if rt:
            row += f"  {delay_str:>7}"
        print(row)

    print(f"\n{len(results)} trips found.")


def cmd_departures(args):
    """Station departures board: all trains from a stop."""
    db_path = download_gtfs(force=args.refresh)

    date_str = args.date or datetime.now().strftime("%Y%m%d")
    now_default = datetime.now().strftime("%H:%M")
    after_time = _parse_time_arg(args.after, default=now_default)
    before_time = _parse_time_arg(args.before)
    line = args.line or None

    results = search_departures(
        db_path,
        stop=args.stop,
        line=line,
        date_str=date_str,
        after_time=after_time,
        before_time=before_time,
    )

    if not results:
        print(f"No departures found from '{args.stop}' on {date_str}")
        return

    lines_in_results = {r["line"] for r in results}
    delay_by_train, all_train_numbers = _fetch_delays(db_path, lines_in_results, date_str, skip_rt=args.no_rt)

    stop_name = results[0]["stop_name"]
    print(f"Departures from {stop_name} on {date_str}")
    time_filter = ""
    if after_time:
        time_filter += f"after {after_time}"
    if before_time:
        time_filter += f"{', ' if time_filter else ''}before {before_time}"
    if time_filter:
        print(f"({time_filter})")
    print()
    rt = not args.no_rt
    hdr = f"{'Train':>7}  {'Line':>4}  {'Departure':>10}"
    sep = f"{'─' * 7}  {'─' * 4}  {'─' * 10}"
    if rt:
        hdr += f"  {'Delay':>7}"
        sep += f"  {'─' * 7}"
    hdr += "  Destination"
    sep += f"  {'─' * 30}"
    print(hdr)
    print(sep)

    for r in results:
        label = _train_label(r["trip_id"], all_train_numbers)
        delay_s = delay_by_train.get(label)
        dep = r["time"][:5]

        delay_str = ""
        if rt and delay_s and delay_s != 0:
            delay_min = delay_s / 60
            sign = "+" if delay_s > 0 else ""
            delay_str = f"{sign}{delay_min:.0f}m"
            dep = f"*{dep}"

        row = f"{label:>7}  {r['line']:>4}  {dep:>10}"
        if rt:
            row += f"  {delay_str:>7}"
        row += f"  {r['destination']}"
        print(row)

    print(f"\n{len(results)} departures.")


def cmd_arrivals(args):
    """Station arrivals board: all trains arriving at a stop."""
    db_path = download_gtfs(force=args.refresh)

    date_str = args.date or datetime.now().strftime("%Y%m%d")
    now_default = datetime.now().strftime("%H:%M")
    after_time = _parse_time_arg(args.after, default=now_default)
    before_time = _parse_time_arg(args.before)
    line = args.line or None

    results = search_arrivals(
        db_path,
        stop=args.stop,
        line=line,
        date_str=date_str,
        after_time=after_time,
        before_time=before_time,
    )

    if not results:
        print(f"No arrivals found at '{args.stop}' on {date_str}")
        return

    lines_in_results = {r["line"] for r in results}
    delay_by_train, all_train_numbers = _fetch_delays(db_path, lines_in_results, date_str, skip_rt=args.no_rt)

    stop_name = results[0]["stop_name"]
    print(f"Arrivals at {stop_name} on {date_str}")
    time_filter = ""
    if after_time:
        time_filter += f"after {after_time}"
    if before_time:
        time_filter += f"{', ' if time_filter else ''}before {before_time}"
    if time_filter:
        print(f"({time_filter})")
    print()
    rt = not args.no_rt
    hdr = f"{'Train':>7}  {'Line':>4}  {'Arrival':>10}"
    sep = f"{'─' * 7}  {'─' * 4}  {'─' * 10}"
    if rt:
        hdr += f"  {'Delay':>7}"
        sep += f"  {'─' * 7}"
    hdr += "  Origin"
    sep += f"  {'─' * 30}"
    print(hdr)
    print(sep)

    for r in results:
        label = _train_label(r["trip_id"], all_train_numbers)
        delay_s = delay_by_train.get(label)
        arr = r["time"][:5]

        delay_str = ""
        if rt and delay_s and delay_s != 0:
            delay_min = delay_s / 60
            sign = "+" if delay_s > 0 else ""
            delay_str = f"{sign}{delay_min:.0f}m"
            arr = f"*{arr}"

        row = f"{label:>7}  {r['line']:>4}  {arr:>10}"
        if rt:
            row += f"  {delay_str:>7}"
        row += f"  {r['origin']}"
        print(row)

    print(f"\n{len(results)} arrivals.")


def cmd_alerts(args):
    """Show service alerts for a line."""
    zip_path = download_gtfs(force=args.refresh)

    # Get route_ids for the line
    routes = find_routes(zip_path, line=args.line)
    if not routes:
        print(f"No routes found for line {args.line}")
        return

    route_ids = {r["route_id"] for r in routes}
    alerts = get_alerts(route_ids)

    if not alerts:
        print(f"No active alerts for line {args.line}")
        return

    print(f"Active alerts for line {args.line}:")
    print()
    for a in alerts:
        print(f"⚠  {a['header']}")
        if a["description"]:
            print(f"   {a['description']}")
        if a["active_periods"]:
            for p in a["active_periods"]:
                start = datetime.fromtimestamp(p["start"]).strftime("%Y-%m-%d %H:%M") if p["start"] else "?"
                end = datetime.fromtimestamp(p["end"]).strftime("%Y-%m-%d %H:%M") if p["end"] else "ongoing"
                print(f"   Period: {start} → {end}")
        print()

    print(f"{len(alerts)} alert(s) found.")


def cmd_delays(args):
    """Show current delays/trip updates for a line."""
    zip_path = download_gtfs(force=args.refresh)

    routes = find_routes(zip_path, line=args.line)
    if not routes:
        print(f"No routes found for line {args.line}")
        return

    today = datetime.now().strftime("%Y%m%d")
    services = get_active_services(zip_path, today)
    train_numbers = _get_train_numbers_for_lines(zip_path, {args.line}, services)

    relevant = _match_rt_entities(get_trip_updates(), {args.line}, train_numbers)
    stops = load_stops(zip_path)

    if not relevant:
        print(f"No current delays for line {args.line}")
        return

    print(f"Current delays for line {args.line}:")
    print()
    for u in relevant:
        label = _train_label(u["trip_id"], train_numbers)
        delay_min = u["delay_seconds"] / 60
        sign = "+" if u["delay_seconds"] > 0 else ""
        print(f"  Train {label}: {sign}{delay_min:.0f} min")
        for su in u["stop_updates"]:
            stop_name = stops.get(su["stop_id"], {}).get("stop_name", su["stop_id"])
            if su["arrival_delay"]:
                d = su["arrival_delay"] / 60
                print(f"    → {stop_name}: {'+' if d > 0 else ''}{d:.0f} min")
    print()
    print(f"{len(relevant)} train(s) with updates.")


def cmd_positions(args):
    """Show current vehicle positions for a line."""
    zip_path = download_gtfs(force=args.refresh)

    routes = find_routes(zip_path, line=args.line)
    if not routes:
        print(f"No routes found for line {args.line}")
        return

    today = datetime.now().strftime("%Y%m%d")
    services = get_active_services(zip_path, today)
    train_numbers = _get_train_numbers_for_lines(zip_path, {args.line}, services)

    relevant = _match_rt_entities(get_vehicle_positions(), {args.line}, train_numbers)
    stops = load_stops(zip_path)

    if not relevant:
        print(f"No active trains for line {args.line}")
        return

    print(f"Active trains on line {args.line}:")
    print()
    print(f"{'Train':>8}  {'Status':<14}  {'Stop':<30}  {'Lat':>9}  {'Lon':>9}")
    print(f"{'─' * 8}  {'─' * 14}  {'─' * 30}  {'─' * 9}  {'─' * 9}")
    for v in relevant:
        label = _train_label(v["trip_id"], train_numbers)
        stop_name = stops.get(v["stop_id"], {}).get("stop_name", v["stop_id"])
        print(f"{label:>8}  {v['status']:<14}  {stop_name:<30}  {v['latitude']:>9.5f}  {v['longitude']:>9.5f}")
    print()
    print(f"{len(relevant)} train(s) active.")


def cmd_stops(args):
    """List stops served by a line."""
    zip_path = download_gtfs(force=args.refresh)

    routes = find_routes(zip_path, line=args.line)
    if not routes:
        print(f"No routes found for line {args.line}")
        return

    print(f"Routes for line {args.line}:")
    for r in routes:
        print(f"  {r['route_id']}: {r['route_long_name']} ({r['nucleus']})")

    # Get one trip per route direction to show stops
    from .gtfs_static import find_stop_times
    route_ids = {r["route_id"] for r in routes}

    # Just grab first available trip per route
    trips = find_trips(zip_path, route_ids)
    if not trips:
        print("No trips found.")
        return

    # One trip per route_id
    seen_routes = set()
    sample_trips = []
    for t in trips:
        if t["route_id"] not in seen_routes:
            seen_routes.add(t["route_id"])
            sample_trips.append(t)

    trip_ids = {t["trip_id"] for t in sample_trips}
    all_st = find_stop_times(zip_path, trip_ids)
    stops = load_stops(zip_path)

    for t in sample_trips:
        route = next(r for r in routes if r["route_id"] == t["route_id"])
        print(f"\n{route['route_short_name']} — {route['route_long_name']}:")
        st_list = all_st.get(t["trip_id"], [])
        for st in st_list:
            name = stops.get(st["stop_id"], {}).get("stop_name", st["stop_id"])
            print(f"  {st['stop_sequence']:>3}. {name}")


def cmd_routes(args):
    """List available lines/routes."""
    zip_path = download_gtfs(force=args.refresh)
    routes = find_routes(zip_path, line=args.line, nucleus=args.nucleus)

    if not routes:
        print("No routes found.")
        return

    # Group by line
    by_line: dict[str, list] = {}
    for r in routes:
        key = f"{r['route_short_name']} ({r['nucleus']})"
        by_line.setdefault(key, []).append(r)

    print(f"{'Line':<25} {'Routes':>6}  Sample")
    print(f"{'─' * 25} {'─' * 6}  {'─' * 40}")
    for key in sorted(by_line):
        sample = by_line[key][0]["route_long_name"]
        print(f"{key:<25} {len(by_line[key]):>6}  {sample}")


def main():
    parser = argparse.ArgumentParser(
        prog="renfe",
        description="RENFE Cercanías schedule and alerts via GTFS",
    )
    parser.add_argument("--refresh", action="store_true", help="Force refresh GTFS data")
    parser.add_argument("--no-rt", action="store_true", help="Skip realtime delay lookups (faster)")
    sub = parser.add_subparsers(dest="command", required=True)

    # schedule
    p_sched = sub.add_parser("schedule", aliases=["s"], help="Search departures")
    p_sched.add_argument("--line", "-l", help="Line name (e.g. R11, C1). Omit to search all lines.")
    p_sched.add_argument("--from", "-f", dest="origin", required=True, help="Origin stop (partial name)")
    p_sched.add_argument("--to", "-t", dest="destination", required=True, help="Destination stop (partial name)")
    p_sched.add_argument("--date", "-d", help="Date YYYYMMDD (default: today)")
    p_sched.add_argument("--after", "-a", help="Show departures after TIME (HH:MM, now, +1h, +30m)")
    p_sched.add_argument("--before", "-b", help="Show departures before TIME")
    p_sched.set_defaults(func=cmd_schedule)

    # departures
    p_dep = sub.add_parser("departures", aliases=["dep"], help="Station departures board")
    p_dep.add_argument("--stop", "-s", required=True, help="Stop name (partial match)")
    p_dep.add_argument("--line", "-l", help="Filter by line")
    p_dep.add_argument("--date", "-d", help="Date YYYYMMDD (default: today)")
    p_dep.add_argument("--after", "-a", help="Show departures after TIME (default: now)")
    p_dep.add_argument("--before", "-b", help="Show departures before TIME")
    p_dep.set_defaults(func=cmd_departures)

    # arrivals
    p_arr = sub.add_parser("arrivals", aliases=["arr"], help="Station arrivals board")
    p_arr.add_argument("--stop", "-s", required=True, help="Stop name (partial match)")
    p_arr.add_argument("--line", "-l", help="Filter by line")
    p_arr.add_argument("--date", "-d", help="Date YYYYMMDD (default: today)")
    p_arr.add_argument("--after", "-a", help="Show arrivals after TIME (default: now)")
    p_arr.add_argument("--before", "-b", help="Show arrivals before TIME")
    p_arr.set_defaults(func=cmd_arrivals)

    # alerts
    p_alerts = sub.add_parser("alerts", aliases=["a"], help="Service alerts for a line")
    p_alerts.add_argument("--line", "-l", required=True, help="Line name (e.g. R11)")
    p_alerts.set_defaults(func=cmd_alerts)

    # delays
    p_delays = sub.add_parser("delays", aliases=["d"], help="Current delays for a line")
    p_delays.add_argument("--line", "-l", required=True, help="Line name (e.g. R11)")
    p_delays.set_defaults(func=cmd_delays)

    # positions
    p_pos = sub.add_parser("positions", aliases=["p"], help="Live train positions")
    p_pos.add_argument("--line", "-l", required=True, help="Line name (e.g. R11)")
    p_pos.set_defaults(func=cmd_positions)

    # stops
    p_stops = sub.add_parser("stops", help="List stops on a line")
    p_stops.add_argument("--line", "-l", required=True, help="Line name (e.g. R11)")
    p_stops.set_defaults(func=cmd_stops)

    # routes
    p_routes = sub.add_parser("routes", aliases=["r"], help="List available lines")
    p_routes.add_argument("--line", "-l", help="Filter by line name")
    p_routes.add_argument("--nucleus", "-n", help="Filter by network/city (e.g. Madrid, Barcelona)")
    p_routes.set_defaults(func=cmd_routes)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
