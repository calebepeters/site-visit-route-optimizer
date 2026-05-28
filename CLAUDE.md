# Site Visit Route Optimizer

A CLI tool that takes a CSV of tower sites (lat/long) and produces an optimized
multi-day visit schedule for a single technician. It minimizes total travel time
while respecting daily work-hour limits, using real driving times from the free
OSRM public demo server.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the optimizer

```bash
python optimize.py path/to/sites.csv
```

The tool will:
1. Load and validate the CSV
2. Filter geographic outliers (>200 miles from the cluster centroid)
3. Find the nearest commercial airport to the site cluster
4. Fetch a full driving-time matrix from OSRM (cached locally in `.osrm_cache.json`)
5. Solve a Vehicle Routing Problem with OR-Tools
6. Write outputs next to the input file

### 3. Outputs

| File | Description |
|------|-------------|
| `<stem>_schedule.csv` | All sites with `Day` and `Visit_Order` columns added |
| `<stem>_outliers.csv` | Sites filtered before routing (>200 miles from centroid) |

## Input CSV Format

Required columns (exact names):

| Column | Description |
|--------|-------------|
| `Site Name` | Unique identifier for the site |
| `Latitude` | Decimal degrees (e.g. `33.4500`) |
| `Longitude` | Decimal degrees (e.g. `-112.0100`) |
| `Access Instructions` | Free-text access notes |
| `Access Directions` | Free-text driving directions |

## Constraints

- 45 minutes per site visit (on-site time)
- 10-hour maximum work day (600 minutes total, including travel)
- 1 technician (single vehicle in the VRP)
- Each day starts from the nearest commercial airport to the site cluster centroid
- No requirement to return to the airport at end of day (open route)

## Configurable Constants

| File | Constant | Default | Description |
|------|----------|---------|-------------|
| `geo.py` | `OUTLIER_THRESHOLD_MILES` | `200` | Sites beyond this distance from the centroid are excluded |
| `routing.py` | `SERVICE_TIME_MINUTES` | `45` | On-site visit duration |
| `routing.py` | `MAX_DAY_MINUTES` | `600` | Maximum work day length |
| `maps.py` | `OSRM_BASE` | OSRM public demo URL | Routing server base URL |
| `maps.py` | `CACHE_FILE` | `.osrm_cache.json` | Local travel-matrix cache |

## Project Structure

```
.
├── optimize.py          # Entry point and orchestration
├── routing.py           # OR-Tools VRP setup and solver
├── maps.py              # OSRM Table API calls + caching
├── airports.py          # Airport list loading and nearest-airport lookup
├── geo.py               # Haversine distance, centroid, outlier filtering
├── data/
│   └── airports.csv     # Bundled list of ~100 US commercial airports
├── requirements.txt
├── CLAUDE.md            # This file
└── tests/
    ├── test_geo.py       # Unit tests for geo functions
    ├── test_airports.py  # Unit tests for airport loading/lookup
    └── test_maps.py      # Unit tests for maps.py (mocked OSRM)
```

## Running Tests

```bash
# From the project root
python -m pytest tests/ -v
```

## Notes

- The OSRM public demo server (`router.project-osrm.org`) is rate-limited and
  intended for testing. For production use with large site lists, consider running
  a local OSRM instance and updating `OSRM_BASE` in `maps.py`.
- Travel matrices are cached in `.osrm_cache.json`. Delete this file to force a
  fresh fetch from OSRM.
- The OR-Tools solver runs for up to 30 seconds. For very large site lists
  (100+ sites), this may produce a sub-optimal but valid solution.
