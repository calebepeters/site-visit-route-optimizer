"""
geo.py — Haversine distance, centroid calculation, and outlier filtering.
"""
from __future__ import annotations

import math

OUTLIER_THRESHOLD_MILES = 200


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in miles between two lat/lon points."""
    R = 3958.8  # Earth radius in miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def centroid(coords: list[tuple[float, float]]) -> tuple[float, float]:
    """Return the (lat, lon) centroid (arithmetic mean) of a list of coordinates."""
    if not coords:
        raise ValueError("Cannot compute centroid of empty coordinate list.")
    lat_mean = sum(c[0] for c in coords) / len(coords)
    lon_mean = sum(c[1] for c in coords) / len(coords)
    return lat_mean, lon_mean


def filter_outliers(
    sites: list[dict],
    threshold_miles: float = OUTLIER_THRESHOLD_MILES,
) -> tuple[list[dict], list[dict]]:
    """
    Split sites into (kept, outliers) based on distance from the cluster centroid.

    Parameters
    ----------
    sites : list of dicts with 'Latitude' and 'Longitude' keys (numeric or string).
    threshold_miles : sites farther than this from the centroid are outliers.

    Returns
    -------
    (kept, outliers) — both lists preserve all original dict fields.
    """
    if not sites:
        return [], []

    coords = [(float(s["Latitude"]), float(s["Longitude"])) for s in sites]
    clat, clon = centroid(coords)

    kept = []
    outliers = []
    for site, (lat, lon) in zip(sites, coords):
        dist = haversine_miles(clat, clon, lat, lon)
        if dist <= threshold_miles:
            kept.append(site)
        else:
            outliers.append(site)

    return kept, outliers
