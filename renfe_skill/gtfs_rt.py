"""Fetch GTFS Realtime data: alerts, trip updates, vehicle positions."""

import requests
from google.transit import gtfs_realtime_pb2

from .config import GTFS_RT_ALERTS, GTFS_RT_TRIP_UPDATES, GTFS_RT_VEHICLE_POSITIONS


def _fetch_feed(url: str) -> gtfs_realtime_pb2.FeedMessage:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed


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


def get_trip_updates(trip_ids: set[str] | None = None) -> list[dict]:
    """Fetch trip updates (delays), optionally filtered to specific trip_ids."""
    feed = _fetch_feed(GTFS_RT_TRIP_UPDATES)
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


def get_vehicle_positions(trip_ids: set[str] | None = None) -> list[dict]:
    """Fetch vehicle positions, optionally filtered to specific trip_ids."""
    feed = _fetch_feed(GTFS_RT_VEHICLE_POSITIONS)
    results = []
    for entity in feed.entity:
        vp = entity.vehicle
        tid = vp.trip.trip_id

        if trip_ids and tid not in trip_ids:
            continue

        status_map = {0: "INCOMING_AT", 1: "STOPPED_AT", 2: "IN_TRANSIT_TO"}

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
