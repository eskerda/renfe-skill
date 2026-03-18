"""Train type detection for RENFE services.

Classifies trains as MD (Media Distancia / express) or R (Rodalies / all-stops)
based on available signals. The detection strategy is pluggable — swap or combine
the classifier functions below.
"""

from enum import Enum


class TrainType(Enum):
    MD = "MD"           # Media Distancia / express — fewer stops
    R = "R"             # Rodalies / cercanías — all stops
    UNKNOWN = "?"


def classify_by_stop_ratio(
    trip_stop_count: int,
    max_stop_count: int,
    threshold: float = 0.6,
) -> TrainType:
    """Classify based on how many stops a trip makes relative to the max for the route.

    Args:
        trip_stop_count: Number of stops this trip makes between origin and destination.
        max_stop_count: Maximum stops any trip makes between the same origin and destination.
        threshold: Ratio below which a trip is considered express/MD.

    Returns:
        TrainType.MD if the trip stops at less than `threshold` of the max, else TrainType.R.
    """
    if max_stop_count <= 0:
        return TrainType.UNKNOWN
    ratio = trip_stop_count / max_stop_count
    if ratio < threshold:
        return TrainType.MD
    return TrainType.R


def classify_by_stop_count(
    trip_stop_count: int,
    md_max: int = 14,
) -> TrainType:
    """Classify based on absolute stop count.

    Args:
        trip_stop_count: Total number of stops in the trip.
        md_max: Maximum number of stops for an MD train.

    Returns:
        TrainType.MD if stop count <= md_max, else TrainType.R.
    """
    if trip_stop_count <= md_max:
        return TrainType.MD
    return TrainType.R


# ── Main classifier ──────────────────────────────────────────────────────────
# This is the single entry point used by the rest of the codebase.
# Change the implementation here to swap detection strategies.

def classify(
    trip_stop_count: int,
    max_stop_count: int,
) -> TrainType:
    """Classify a trip as MD or R.

    Currently uses stop ratio comparison. To change strategy, edit this function.
    """
    return classify_by_stop_ratio(trip_stop_count, max_stop_count)
