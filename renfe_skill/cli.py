"""RENFE Cercanías CLI — schedule lookups and service alerts."""

import argparse
import sys
from datetime import datetime

from .gtfs_static import download_gtfs, find_routes, find_trips, get_active_services, load_stops, search_schedule
from .gtfs_rt import get_alerts, get_trip_updates, get_vehicle_positions


def _get_train_numbers(zip_path, routes, services) -> set[str]:
    """Extract train numbers for a line from GTFS static trips.

    Maps trip_ids like '5173X15778R11' to train numbers like '15778'.
    """
    route_ids = {r["route_id"] for r in routes}
    trips = find_trips(zip_path, route_ids, services)
    train_numbers = set()
    for t in trips:
        tid = t["trip_id"]
        for r in routes:
            short = r["route_short_name"]
            if short in tid:
                num = tid.split(short)[0]
                for s in services:
                    if num.startswith(s):
                        num = num[len(s):]
                        break
                if num:
                    train_numbers.add(num)
    return train_numbers


def _match_rt_entities(entities: list[dict], line: str, train_numbers: set[str]) -> list[dict]:
    """Filter RT entities by line name in trip_id (cercanías) or train number prefix (LD)."""
    line_upper = line.upper()
    results = []
    for e in entities:
        tid = e["trip_id"]
        if line_upper in tid.upper():
            results.append(e)
        elif any(tid.startswith(num) for num in train_numbers):
            results.append(e)
    return results


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
    after_time = args.after or None

    results = search_schedule(
        zip_path,
        line=args.line,
        origin=args.origin,
        destination=args.destination,
        date_str=date_str,
        after_time=after_time,
    )

    if not results:
        print(f"No trips found for {args.line} from '{args.origin}' to '{args.destination}' on {date_str}")
        return

    # Fetch live delays and match to schedule results
    routes = find_routes(zip_path, line=args.line)
    services = get_active_services(zip_path, date_str)
    train_numbers = _get_train_numbers(zip_path, routes, services)
    delays = _match_rt_entities(get_trip_updates(), args.line, train_numbers)
    delay_by_train = {}
    for d in delays:
        label = _train_label(d["trip_id"], train_numbers)
        delay_by_train[label] = d["delay_seconds"]

    def _format_time_with_delay(scheduled: str, delay_s: int | None) -> str:
        """Return expected time as HH:MM, adjusted by delay."""
        t = scheduled[:5]  # HH:MM
        if delay_s is None or delay_s == 0:
            return t
        h, m = int(t[:2]), int(t[3:5])
        total_min = h * 60 + m + (delay_s // 60)
        eh, em = divmod(total_min, 60)
        return f"~{eh:02d}:{em:02d}"

    # Check if any train has a delay — only show expected columns if so
    has_delays = any(
        delay_by_train.get(_train_label(r["trip_id"], train_numbers))
        for r in results
    )

    print(f"Schedule for {args.line}: {results[0]['origin_stop']} → {results[0]['destination_stop']} on {date_str}")
    if after_time:
        print(f"(showing departures after {after_time})")
    print()

    if has_delays:
        print(f"{'Departure':>10}  {'Expected':>9}  {'Arrival':>8}  {'Expected':>9}  {'Type':>4}  Trip ID")
        print(f"{'─' * 10}  {'─' * 9}  {'─' * 8}  {'─' * 9}  {'─' * 4}  {'─' * 20}")
    else:
        print(f"{'Departure':>10}  {'Arrival':>8}  {'Type':>4}  Trip ID")
        print(f"{'─' * 10}  {'─' * 8}  {'─' * 4}  {'─' * 20}")

    for r in results:
        tt = r.get('train_type', '?')
        label = _train_label(r["trip_id"], train_numbers)
        delay_s = delay_by_train.get(label)
        dep = r["departure_time"][:5]
        arr = r["arrival_time"][:5]

        if has_delays:
            if delay_s and delay_s != 0:
                exp_dep = _format_time_with_delay(r["departure_time"], delay_s)
                exp_arr = _format_time_with_delay(r["arrival_time"], delay_s)
            else:
                exp_dep = ""
                exp_arr = ""
            print(f"{dep:>10}  {exp_dep:>9}  {arr:>8}  {exp_arr:>9}  {tt:>4}  {r['trip_id']}")
        else:
            print(f"{dep:>10}  {arr:>8}  {tt:>4}  {r['trip_id']}")

    print(f"\n{len(results)} trips found.")


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
    train_numbers = _get_train_numbers(zip_path, routes, services)

    relevant = _match_rt_entities(get_trip_updates(), args.line, train_numbers)
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
    train_numbers = _get_train_numbers(zip_path, routes, services)

    relevant = _match_rt_entities(get_vehicle_positions(), args.line, train_numbers)
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
    sub = parser.add_subparsers(dest="command", required=True)

    # schedule
    p_sched = sub.add_parser("schedule", aliases=["s"], help="Search departures")
    p_sched.add_argument("--line", "-l", required=True, help="Line name (e.g. R11, C1)")
    p_sched.add_argument("--from", "-f", dest="origin", required=True, help="Origin stop (partial name)")
    p_sched.add_argument("--to", "-t", dest="destination", required=True, help="Destination stop (partial name)")
    p_sched.add_argument("--date", "-d", help="Date YYYYMMDD (default: today)")
    p_sched.add_argument("--after", "-a", help="Only show departures after HH:MM")
    p_sched.set_defaults(func=cmd_schedule)

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
