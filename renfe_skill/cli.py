"""RENFE Cercanías CLI — schedule lookups and service alerts."""

import argparse
import sys
from datetime import datetime

from .gtfs_static import download_gtfs, find_routes, load_stops, search_schedule
from .gtfs_rt import get_alerts, get_trip_updates


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

    print(f"Schedule for {args.line}: {results[0]['origin_stop']} → {results[0]['destination_stop']} on {date_str}")
    if after_time:
        print(f"(showing departures after {after_time})")
    print()
    print(f"{'Departure':>10}  {'Arrival':>10}  {'Type':>4}  {'Stops':>5}  Trip ID")
    print(f"{'─' * 10}  {'─' * 10}  {'─' * 4}  {'─' * 5}  {'─' * 20}")
    for r in results:
        tt = r.get('train_type', '?')
        st = r.get('intermediate_stops', '?')
        print(f"{r['departure_time']:>10}  {r['arrival_time']:>10}  {tt:>4}  {st:>5}  {r['trip_id']}")

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

    route_ids = {r["route_id"] for r in routes}

    # Get all trip updates and filter by route prefix
    # Trip IDs contain the route info, e.g. "5101M15770R11"
    updates = get_trip_updates()

    # Filter: trip_id ends with the line name pattern
    line_upper = args.line.upper()
    relevant = [u for u in updates if line_upper in u["trip_id"].upper()]

    stops = load_stops(zip_path)

    if not relevant:
        print(f"No current delays for line {args.line}")
        return

    print(f"Current delays for line {args.line}:")
    print()
    for u in relevant:
        delay_min = u["delay_seconds"] / 60
        sign = "+" if u["delay_seconds"] > 0 else ""
        print(f"  Trip {u['trip_id']}: {sign}{delay_min:.0f} min")
        for su in u["stop_updates"]:
            stop_name = stops.get(su["stop_id"], {}).get("stop_name", su["stop_id"])
            if su["arrival_delay"]:
                d = su["arrival_delay"] / 60
                print(f"    → {stop_name}: {'+' if d > 0 else ''}{d:.0f} min")
    print()
    print(f"{len(relevant)} trip(s) with updates.")


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
    from .gtfs_static import find_trips, find_stop_times
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
