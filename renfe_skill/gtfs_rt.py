"""Fetch GTFS Realtime data: alerts, trip updates, vehicle positions."""

import requests
from google.transit import gtfs_realtime_pb2

from .config import (
    GTFS_RT_ALERTS,
    GTFS_RT_TRIP_UPDATES,
    GTFS_RT_TRIP_UPDATES_LD,
    GTFS_RT_VEHICLE_POSITIONS,
    GTFS_RT_VEHICLE_POSITIONS_LD,
)


def _fetch_feed(url: str) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


def _fetch_feed_safe(url: str) -> gtfs_realtime_pb2.FeedMessage | None:
    """Fetch a feed, returning None on error (e.g. 404)."""
    try:
        return _fetch_feed(url)
    except requests.HTTPError:
        return None


def get_alerts(route_ids: set[str] | None = None) -> list[dict]:
    """Fetch service alerts, optionally filtered to routes matching route_ids."""
    feed = _fetch_feed(GTFS_RT_ALERTS)
    results = []
    for entity in feed.entity:
        alert = entity.alert
        # Check if this alert affects any of our routes
        affected_routes = []
        for ie in alert.informed_entity:
            affected_routes.append(ie.route_id)

        if route_ids:
            if not any(r in route_ids for r in affected_routes):
                continue

        # Extract text
        header = ""
        if alert.header_text.translation:
            header = alert.header_text.translation[0].text
        description = ""
        if alert.description_text.translation:
            description = alert.description_text.translation[0].text

        periods = []
        for p in alert.active_period:
            periods.append({
                "start": p.start if p.start else None,
                "end": p.end if p.end else None,
            })

        results.append({
            "id": entity.id,
            "header": header,
            "description": description,
            "affected_routes": affected_routes,
            "active_periods": periods,
            "cause": str(alert.cause) if alert.cause else None,
            "effect": str(alert.effect) if alert.effect else None,
        })
    return results


def _parse_trip_updates(feed: gtfs_realtime_pb2.FeedMessage, trip_ids: set[str] | None = None) -> list[dict]:
    """Parse trip updates from a feed message."""
    results = []
    for entity in feed.entity:
        tu = entity.trip_update
        tid = tu.trip.trip_id

        if trip_ids and tid not in trip_ids:
            continue

        stop_updates = []
        for stu in tu.stop_time_update:
            stop_updates.append({
                "stop_id": stu.stop_id,
                "arrival_delay": stu.arrival.delay if stu.HasField("arrival") else None,
                "departure_delay": stu.departure.delay if stu.HasField("departure") else None,
            })

        results.append({
            "trip_id": tid,
            "delay_seconds": tu.delay,
            "stop_updates": stop_updates,
        })
    return results


def get_trip_updates(trip_ids: set[str] | None = None, include_ld: bool = True) -> list[dict]:
    """Fetch trip updates (delays), optionally filtered to specific trip_ids.

    Args:
        trip_ids: Only return updates for these trip_ids.
        include_ld: Also fetch from the LD (long distance) feed.
    """
    results = _parse_trip_updates(_fetch_feed(GTFS_RT_TRIP_UPDATES), trip_ids)
    if include_ld:
        ld_feed = _fetch_feed_safe(GTFS_RT_TRIP_UPDATES_LD)
        if ld_feed:
            results.extend(_parse_trip_updates(ld_feed, trip_ids))
    return results


def _parse_vehicle_positions(feed: gtfs_realtime_pb2.FeedMessage, trip_ids: set[str] | None = None) -> list[dict]:
    """Parse vehicle positions from a feed message."""
    status_map = {0: "INCOMING_AT", 1: "STOPPED_AT", 2: "IN_TRANSIT_TO"}
    results = []
    for entity in feed.entity:
        vp = entity.vehicle
        tid = vp.trip.trip_id

        if trip_ids and tid not in trip_ids:
            continue

        results.append({
            "trip_id": tid,
            "vehicle_id": vp.vehicle.id,
            "vehicle_label": vp.vehicle.label,
            "latitude": vp.position.latitude,
            "longitude": vp.position.longitude,
            "stop_id": vp.stop_id,
            "status": status_map.get(vp.current_status, str(vp.current_status)),
            "timestamp": vp.timestamp,
        })
    return results


def get_vehicle_positions(trip_ids: set[str] | None = None, include_ld: bool = True) -> list[dict]:
    """Fetch vehicle positions, optionally filtered to specific trip_ids.

    Args:
        trip_ids: Only return positions for these trip_ids.
        include_ld: Also fetch from the LD (long distance) feed.
    """
    results = _parse_vehicle_positions(_fetch_feed(GTFS_RT_VEHICLE_POSITIONS), trip_ids)
    if include_ld:
        ld_feed = _fetch_feed_safe(GTFS_RT_VEHICLE_POSITIONS_LD)
        if ld_feed:
            results.extend(_parse_vehicle_positions(ld_feed, trip_ids))
    return results
