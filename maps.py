"""
maps.py — OSRM Table API calls with local JSON caching.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

import requests

OSRM_BASE = "http://router.project-osrm.org/table/v1/driving/"
CACHE_FILE = ".osrm_cache.json"
_REQUEST_TIMEOUT = 10  # seconds


def _cache_key(coords: list[tuple[float, float]]) -> str:
    """Stable hash for a sorted list of (lat, lon) pairs."""
    sorted_coords = sorted(coords)
    payload = json.dumps(sorted_coords, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_cache(cache: dict) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def get_travel_matrix(coords: list[tuple[float, float]]) -> list[list[float]]:
    """
    Fetch or retrieve from cache an NxN travel-time matrix (in seconds).

    Parameters
    ----------
    coords : list of (lat, lon) tuples.

    Returns
    -------
    NxN list of lists; matrix[i][j] is travel time in seconds from i to j.

    Raises
    ------
    RuntimeError on OSRM API errors or unexpected response formats.
    """
    if not coords:
        return []

    key = _cache_key(coords)
    cache = _load_cache()
    if key in cache:
        print(f"  [maps] Cache hit for {len(coords)}-coord matrix.")
        return cache[key]

    # Build OSRM coordinate string: lon,lat;lon,lat;...
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"{OSRM_BASE}{coord_str}"

    print(f"  [maps] Fetching {len(coords)}x{len(coords)} travel matrix from OSRM...")
    try:
        resp = requests.get(url, params={"annotations": "duration"}, timeout=_REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"OSRM request failed: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"OSRM returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error code '{data.get('code')}': {data.get('message', '')}")

    durations = data.get("durations")
    if durations is None:
        raise RuntimeError("OSRM response missing 'durations' field.")

    # Replace None values (unreachable pairs) with a very large number
    LARGE = 9999999.0
    matrix = [
        [cell if cell is not None else LARGE for cell in row]
        for row in durations
    ]

    cache[key] = matrix
    _save_cache(cache)
    print(f"  [maps] Matrix cached.")
    return matrix
