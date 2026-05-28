"""
airports.py — Load bundled airport list and find the nearest airport to a centroid.
"""
from __future__ import annotations

import csv
import os
from typing import Optional

from geo import haversine_miles

_DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "data", "airports.csv")


def load_airports(csv_path: Optional[str] = None) -> list[dict]:
    """
    Load airports from a CSV file.

    Parameters
    ----------
    csv_path : path to the airports CSV. Defaults to the bundled data/airports.csv.

    Returns
    -------
    List of dicts with keys: iata, name, lat, lon (lat/lon as floats).
    """
    path = csv_path or _DEFAULT_CSV
    airports = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            airports.append(
                {
                    "iata": row["iata"].strip(),
                    "name": row["name"].strip(),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                }
            )
    if not airports:
        raise ValueError(f"No airports found in {path}")
    return airports


def nearest_airport(
    centroid_lat: float,
    centroid_lon: float,
    airports: list[dict],
) -> dict:
    """
    Return the airport dict closest (by haversine) to the given centroid coordinates.
    """
    if not airports:
        raise ValueError("Airport list is empty.")
    return min(
        airports,
        key=lambda a: haversine_miles(centroid_lat, centroid_lon, a["lat"], a["lon"]),
    )
