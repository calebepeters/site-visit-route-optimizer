#!/usr/bin/env python3
"""
optimize.py — Site Visit Route Optimizer entry point.

Usage:
    python optimize.py <path/to/sites.csv>
"""
import csv
import os
import sys

from airports import load_airports, nearest_airport
from geo import centroid, filter_outliers
from maps import get_travel_matrix
from routing import solve

REQUIRED_COLUMNS = {"Site Name", "Latitude", "Longitude", "Access Instructions", "Access Directions"}


def load_sites(csv_path: str) -> list[dict]:
    """Load sites from CSV, validate required columns."""
    if not os.path.exists(csv_path):
        print(f"ERROR: File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("ERROR: CSV file is empty or has no header row.", file=sys.stderr)
            sys.exit(1)

        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            print(
                f"ERROR: CSV is missing required columns: {', '.join(sorted(missing))}",
                file=sys.stderr,
            )
            sys.exit(1)

        sites = list(reader)

    if not sites:
        print("ERROR: CSV has no data rows.", file=sys.stderr)
        sys.exit(1)

    # Validate lat/lon are numeric
    for i, site in enumerate(sites, start=2):  # row 2 = first data row
        for col in ("Latitude", "Longitude"):
            try:
                float(site[col])
            except (ValueError, TypeError):
                print(
                    f"ERROR: Row {i}: invalid {col} value '{site[col]}'.",
                    file=sys.stderr,
                )
                sys.exit(1)

    return sites


def write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    """Write rows to a CSV file with given column order."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python optimize.py <path/to/sites.csv>", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    stem = os.path.splitext(input_path)[0]
    schedule_path = f"{stem}_schedule.csv"
    outliers_path = f"{stem}_outliers.csv"

    print(f"Loading sites from: {input_path}")
    sites = load_sites(input_path)
    print(f"  Loaded {len(sites)} site(s).")

    # --- Outlier filtering ---
    print("Filtering geographic outliers (>200 miles from centroid)...")
    kept, outliers = filter_outliers(sites)
    print(f"  Kept {len(kept)} site(s), {len(outliers)} outlier(s).")

    if outliers:
        write_csv(outliers_path, outliers, list(sites[0].keys()))
        print(f"  Outliers written to: {outliers_path}")
    else:
        # Write empty outliers file with header
        write_csv(outliers_path, [], list(sites[0].keys()))
        print(f"  No outliers. Empty file written to: {outliers_path}")

    if not kept:
        print("ERROR: All sites were filtered as outliers. Cannot build schedule.", file=sys.stderr)
        sys.exit(1)

    # --- Nearest airport ---
    print("Finding nearest commercial airport...")
    airports = load_airports()
    coords = [(float(s["Latitude"]), float(s["Longitude"])) for s in kept]
    cen_lat, cen_lon = centroid(coords)
    airport = nearest_airport(cen_lat, cen_lon, airports)
    print(f"  Airport: {airport['name']} ({airport['iata']})")

    # --- Travel matrix ---
    # Prepend airport as node 0 in the coordinate list
    all_coords = [(airport["lat"], airport["lon"])] + coords
    print(f"Building {len(all_coords)}x{len(all_coords)} travel-time matrix...")
    try:
        matrix = get_travel_matrix(all_coords)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Solve ---
    print("Solving routing problem...")
    result = solve(kept, matrix, airport)

    if result is None:
        print("ERROR: OR-Tools found no feasible solution.", file=sys.stderr)
        sys.exit(1)

    n_days = max(r["Day"] for r in result)
    print(f"  Solution found: {len(result)} sites across {n_days} day(s).")

    # --- Format Site Name in-place; drop Day / Visit_Order columns ---
    for row in result:
        day = row.pop("Day")
        stop = row.pop("Visit_Order")
        row["Site Name"] = f"{row['Site Name']}: Day {day} - Stop {stop}"

    # --- Write schedule ---
    original_fields = list(sites[0].keys())
    write_csv(schedule_path, result, original_fields)

    # --- Summary ---
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Starting airport : {airport['name']} ({airport['iata']})")
    print(f"  Sites scheduled  : {len(result)}")
    print(f"  Days required    : {n_days}")
    print(f"  Schedule file    : {schedule_path}")
    print(f"  Outliers file    : {outliers_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
