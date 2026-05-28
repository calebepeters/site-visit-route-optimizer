# Site Visit Route Optimizer

Takes a CSV of tower sites and produces an optimized multi-day visit schedule for a single technician. Outputs a schedule CSV ready to import into Google My Maps.

---

## How It Works

1. **Outlier filtering** — Sites more than 200 miles from the geographic center of the group are removed and written to a separate file.
2. **Airport detection** — Finds the nearest commercial airport to the site cluster. The technician starts Day 1 from there.
3. **Geographic clustering** — Groups sites into geographically coherent regions using k-means, aiming for ~10 sites per day.
4. **Route optimization** — Orders clusters to form a loop (start near the airport, sweep out, return near the airport by the last day). Within each cluster, visits sites in nearest-neighbor order.
5. **Day budgeting** — Cuts day boundaries when the 10-hour clock runs out, including real driving time between sites fetched from OSRM. The next day resumes from wherever the technician stopped.

**Constraints:**
- 45 minutes per site visit
- 10-hour maximum work day (travel + service time)
- No return to airport required at end of each day

**Output format:** `Site Name` is encoded as `<name>: Day N - Stop N` for direct use as Google My Maps pin labels.

---

## Requirements

- Python 3.11 or higher
- Internet connection (for OSRM driving time lookups on first run)
- No API keys required

---

## Installation

**1. Download or clone the project**

```bash
git clone <repo-url>
cd "Routing Site Audits"
```

Or unzip the folder and open a terminal inside it.

**2. Install dependencies**

```bash
pip3 install -r requirements.txt
```

That installs `scikit-learn` and `requests`. Nothing else is needed.

---

## Running the Tool

```bash
python3 optimize.py path/to/your/sites.csv
```

**Example:**
```bash
python3 optimize.py "Site Visit.csv"
```

The tool prints progress as it runs and writes two files next to your input CSV:

| File | Contents |
|---|---|
| `<name>_schedule.csv` | Full optimized schedule with Day and Stop encoded in Site Name |
| `<name>_outliers.csv` | Sites excluded for being >200 miles from the cluster centroid |

---

## Input CSV Format

Your CSV must have exactly these column headers:

| Column | Description |
|---|---|
| `Site Name` | Label for the site (used as the Google My Maps pin name) |
| `Latitude` | Decimal degrees |
| `Longitude` | Decimal degrees |
| `Access Instructions` | Passed through to output unchanged |
| `Access Directions` | Passed through to output unchanged |

All other columns are ignored. Fields can contain commas or line breaks if they are properly quoted.

---

## Re-running on the Same Sites

Driving times are cached locally in `.osrm_cache.json` after the first run. Subsequent runs on the same set of sites are instant — no internet call needed.

If you add or move sites significantly, delete the cache file to force a fresh fetch:

```bash
rm .osrm_cache.json
```

---

## Project Structure

```
├── optimize.py       # Entry point — run this
├── routing.py        # Clustering and day-budget logic
├── maps.py           # OSRM driving time fetcher and cache
├── airports.py       # Nearest airport lookup
├── geo.py            # Haversine distance, centroid, outlier filtering
├── data/
│   └── airports.csv  # ~100 US commercial airports
├── requirements.txt
└── tests/            # Automated test suite
```

---

## Running the Tests

```bash
python3 -m pytest tests/
```

All 71 tests should pass before deploying any changes.

---

## Adjustable Settings

These constants can be changed at the top of their respective files:

| Setting | File | Default | What it does |
|---|---|---|---|
| `OUTLIER_THRESHOLD_MILES` | `geo.py` | `200` | Miles from centroid before a site is excluded |
| `SITE_VISIT_SEC` | `routing.py` | `2700` (45 min) | Time spent at each site |
| `DAY_BUDGET_SEC` | `routing.py` | `36000` (10 hrs) | Maximum work day length |
| `AVG_TRAVEL_SEC` | `routing.py` | `900` (15 min) | Estimated drive time used to compute number of days |
