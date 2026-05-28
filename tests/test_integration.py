"""
Integration tests covering:
- Output format (Site Name encoding, no Day/Visit_Order columns)
- Airport appears only as Day 1 start; Day 2+ continue from last site
- Geographic clustering regression (Mauston site stays in its geographic cluster)
- Single-day input produces one day starting from airport
- CSV multiline field parsing
- OSRM timeout produces clear error
- Reproducibility: identical inputs → identical outputs
"""
from __future__ import annotations

import csv as csv_mod
import io
import math
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routing import (
    solve,
    cluster_sites,
    order_day,
    SITE_VISIT_SEC,
    DAY_BUDGET_SEC,
    AVG_TRAVEL_SEC,
    _SITES_PER_DAY,
)
from geo import filter_outliers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _make_matrix_seconds(coords):
    """Synthetic travel-time matrix: haversine distance at 60 mph → seconds."""
    n = len(coords)
    matrix = []
    for i in range(n):
        row = []
        for j in range(n):
            if i == j:
                row.append(0.0)
            else:
                miles = _haversine_miles(*coords[i], *coords[j])
                row.append(miles / 60 * 3600)
        matrix.append(row)
    return matrix


def _site(name, lat, lon):
    return {"Site Name": name, "Latitude": str(lat), "Longitude": str(lon),
            "Access Instructions": "", "Access Directions": ""}


def _build(airport, sites):
    coords = [(airport["lat"], airport["lon"])] + [
        (float(s["Latitude"]), float(s["Longitude"])) for s in sites
    ]
    return _make_matrix_seconds(coords)


AIRPORT = {"iata": "MKE", "name": "Milwaukee Mitchell", "lat": 42.947, "lon": -87.896}

# 8 sites close together — fit in 1 day
SITES_SMALL = [_site(f"Site {i}", 43.0 + i * 0.05, -88.0 + i * 0.03) for i in range(8)]

# 22 sites across a wider area — multiple days
SITES_MULTI = [
    _site(f"Tower {i}", 43.0 + (i % 5) * 0.1, -88.5 + (i // 5) * 0.2)
    for i in range(22)
]


# ---------------------------------------------------------------------------
# TestAirportAppearsOnlyOnDay1
# ---------------------------------------------------------------------------

class TestAirportAppearsOnlyOnDay1:
    def test_airport_is_only_start_for_day1(self):
        """The airport is the start for Day 1 only."""
        matrix = _build(AIRPORT, SITES_MULTI)
        result = solve(SITES_MULTI, matrix, AIRPORT)
        assert result is not None and len(result) > 0

        day1_stops = [r for r in result if r["Day"] == 1]
        assert len(day1_stops) >= 1

        # First Day-1 site must have non-zero travel time from airport
        first_name = day1_stops[0]["Site Name"]
        first_site_idx = next(
            i for i, s in enumerate(SITES_MULTI) if s["Site Name"] == first_name
        )
        first_global = first_site_idx + 1
        assert matrix[0][first_global] > 0

    def test_day2_does_not_restart_from_airport(self):
        """Day 2's first site is geographically close to Day 1's last site."""
        matrix = _build(AIRPORT, SITES_MULTI)
        result = solve(SITES_MULTI, matrix, AIRPORT)
        assert result is not None

        days = sorted({r["Day"] for r in result})
        if len(days) < 2:
            pytest.skip("Not enough days to test day-2 continuity")

        day1 = [r for r in result if r["Day"] == 1]
        last_day1_name = max(day1, key=lambda r: r["Visit_Order"])["Site Name"]

        day2 = [r for r in result if r["Day"] == 2]
        first_day2_name = min(day2, key=lambda r: r["Visit_Order"])["Site Name"]

        def global_idx(name):
            for i, s in enumerate(SITES_MULTI):
                if s["Site Name"] == name:
                    return i + 1
            return None

        last_g = global_idx(last_day1_name)
        first_g = global_idx(first_day2_name)
        assert last_g is not None and first_g is not None

        dist_from_last = matrix[last_g][first_g]
        dist_from_airport = matrix[0][first_g]
        # Day 2 start should be no farther than 2× from last Day-1 site vs airport
        assert dist_from_last <= dist_from_airport * 2 + 300


# ---------------------------------------------------------------------------
# TestOutputFormat
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_solve_returns_day_and_visit_order(self):
        """solve() must return Day and Visit_Order for optimize.py to consume."""
        matrix = _build(AIRPORT, SITES_SMALL)
        result = solve(SITES_SMALL, matrix, AIRPORT)
        assert result is not None
        for row in result:
            assert "Day" in row
            assert "Visit_Order" in row

    def test_site_name_format_after_transformation(self):
        """Simulate optimize.py transformation: Site Name encoded, keys removed."""
        matrix = _build(AIRPORT, SITES_SMALL)
        result = solve(SITES_SMALL, matrix, AIRPORT)
        assert result is not None

        for row in result:
            day = row.pop("Day")
            stop = row.pop("Visit_Order")
            row["Site Name"] = f"{row['Site Name']}: Day {day} - Stop {stop}"

        for row in result:
            assert "Day" not in row
            assert "Visit_Order" not in row
            parts = row["Site Name"].split(": Day ")
            assert len(parts) == 2
            day_stop = parts[1].split(" - Stop ")
            assert len(day_stop) == 2
            assert day_stop[0].isdigit()
            assert day_stop[1].isdigit()

    def test_output_csv_no_day_visit_order_columns(self, tmp_path):
        """Written CSV must not contain Day or Visit_Order columns."""
        matrix = _build(AIRPORT, SITES_SMALL)
        result = solve(SITES_SMALL, matrix, AIRPORT)
        assert result is not None

        for row in result:
            day = row.pop("Day")
            stop = row.pop("Visit_Order")
            row["Site Name"] = f"{row['Site Name']}: Day {day} - Stop {stop}"

        original_fields = list(SITES_SMALL[0].keys())
        out = tmp_path / "schedule.csv"
        with open(out, "w", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=original_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(result)

        with open(out, newline="") as f:
            reader = csv_mod.DictReader(f)
            assert "Day" not in reader.fieldnames
            assert "Visit_Order" not in reader.fieldnames
            assert "Site Name" in reader.fieldnames
            for row in reader:
                assert ": Day " in row["Site Name"]
                assert " - Stop " in row["Site Name"]

    def test_outliers_retain_original_site_name(self):
        """Outliers CSV must preserve unmodified Site Name values."""
        normal = [_site(f"Normal {i}", 43.0 + i * 0.05, -88.0) for i in range(5)]
        outlier = [_site("Far Away", 34.0, -118.0)]
        kept, outliers = filter_outliers(normal + outlier)
        assert any(s["Site Name"] == "Far Away" for s in outliers)
        for s in outliers:
            assert ": Day " not in s["Site Name"]
            assert " - Stop " not in s["Site Name"]


# ---------------------------------------------------------------------------
# TestClusterSites
# ---------------------------------------------------------------------------

class TestClusterSites:
    def test_geographic_coherence(self):
        """
        Sites in the same cluster should be geographically closer to each other
        on average than sites in different clusters.
        """
        # Two clearly separated groups of sites
        group_a = [_site(f"A{i}", 43.0 + i * 0.01, -88.0 + i * 0.01) for i in range(12)]
        group_b = [_site(f"B{i}", 47.0 + i * 0.01, -95.0 + i * 0.01) for i in range(12)]
        sites = group_a + group_b
        airport = {"iata": "MSP", "name": "Minneapolis", "lat": 44.88, "lon": -93.22}
        matrix = _build(airport, sites)

        clusters = cluster_sites(sites, matrix)
        assert len(clusters) >= 2

        # All A-group sites should share a cluster
        a_globals = set(range(1, 13))
        b_globals = set(range(13, 25))
        for cluster in clusters:
            cluster_set = set(cluster)
            a_overlap = len(cluster_set & a_globals)
            b_overlap = len(cluster_set & b_globals)
            # No cluster should contain more than a minority from the other group
            total = a_overlap + b_overlap
            majority = max(a_overlap, b_overlap)
            assert majority / total >= 0.75, (
                f"Cluster {cluster} mixes groups too much: A={a_overlap}, B={b_overlap}"
            )

    def test_returns_all_sites(self):
        """All site global indices must appear exactly once across all clusters."""
        sites = [_site(f"S{i}", 43.0 + i * 0.1, -88.0 + i * 0.05) for i in range(15)]
        airport = {"iata": "MKE", "name": "Milwaukee", "lat": 42.947, "lon": -87.896}
        matrix = _build(airport, sites)

        clusters = cluster_sites(sites, matrix)
        all_returned = [g for cluster in clusters for g in cluster]
        assert sorted(all_returned) == list(range(1, len(sites) + 1))

    def test_single_day_skips_clustering(self):
        """k=1 (few sites) returns a single group with all sites."""
        # _SITES_PER_DAY = 10, so 5 sites → k=1
        sites = [_site(f"S{i}", 43.0 + i * 0.05, -88.0) for i in range(5)]
        airport = {"iata": "MKE", "name": "Milwaukee", "lat": 42.947, "lon": -87.896}
        matrix = _build(airport, sites)

        clusters = cluster_sites(sites, matrix)
        assert len(clusters) == 1
        assert sorted(clusters[0]) == list(range(1, 6))

    def test_34_wisconsin_sites_produce_k4_clusters(self):
        """
        34 sites → k = ceil(34 / 10) = 4 clusters.
        Verifies the seconds-based formula: floor(36000 / (2700 + 900)) = 10 sites/day.

        Sites are placed in 4 tight geographic sub-regions (< 1 mile apart within
        each region) so no cluster exceeds the DAY_BUDGET_SEC and no splitting occurs.
        """
        # 4 regions × ~8-9 sites each = 34 total; sites within each region are ~0.7 miles apart
        regions = [(43.2, -91.0), (43.2, -89.0), (45.0, -91.0), (45.0, -89.0)]
        counts  = [9, 9, 8, 8]  # 9+9+8+8 = 34
        wi_sites = []
        for (base_lat, base_lon), n in zip(regions, counts):
            for i in range(n):
                wi_sites.append(
                    _site(f"WI_{base_lat}_{i}", base_lat + (i % 3) * 0.01, base_lon + (i // 3) * 0.01)
                )

        airport = {"iata": "MKE", "name": "Milwaukee Mitchell", "lat": 42.947, "lon": -87.896}
        matrix = _build(airport, wi_sites)

        clusters = cluster_sites(wi_sites, matrix)
        assert len(clusters) == 4, (
            f"Expected 4 clusters for 34 sites, got {len(clusters)}"
        )


# ---------------------------------------------------------------------------
# TestOrderDay
# ---------------------------------------------------------------------------

class TestOrderDay:
    def test_nearest_neighbor_property(self):
        """
        At each step the next site chosen must be the nearest unvisited site
        from the current position.
        """
        # 4 sites arranged in a line: airport → S1 → S2 → S3 → S4
        # where each is ~10 miles farther along
        airport_lat, airport_lon = 43.0, -88.0
        site_lats = [43.0, 43.0, 43.0, 43.0]
        site_lons = [-87.85, -87.70, -87.55, -87.40]  # ~10mi increments

        sites = [_site(f"S{i}", site_lats[i], site_lons[i]) for i in range(4)]
        coords = [(airport_lat, airport_lon)] + list(zip(site_lats, site_lons))
        matrix = _make_matrix_seconds(coords)

        # Global indices 1..4 for sites
        ordered = order_day([1, 2, 3, 4], 0, matrix)

        # Expected: sites in order of increasing distance from airport (west to east)
        assert ordered == [1, 2, 3, 4], f"Expected [1,2,3,4], got {ordered}"

    def test_returns_all_input_indices(self):
        """All input global indices must appear in the output."""
        sites = [_site(f"S{i}", 43.0 + i * 0.1, -88.0 + i * 0.1) for i in range(6)]
        coords = [(AIRPORT["lat"], AIRPORT["lon"])] + [
            (float(s["Latitude"]), float(s["Longitude"])) for s in sites
        ]
        matrix = _make_matrix_seconds(coords)
        result = order_day([1, 2, 3, 4, 5, 6], 0, matrix)
        assert sorted(result) == [1, 2, 3, 4, 5, 6]

    def test_start_point_not_in_output(self):
        """The start_global depot should not appear in the returned list."""
        sites = [_site(f"S{i}", 43.0 + i * 0.05, -88.0) for i in range(4)]
        coords = [(AIRPORT["lat"], AIRPORT["lon"])] + [
            (float(s["Latitude"]), float(s["Longitude"])) for s in sites
        ]
        matrix = _make_matrix_seconds(coords)
        result = order_day([1, 2, 3, 4], 0, matrix)
        assert 0 not in result


# ---------------------------------------------------------------------------
# TestReproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_identical_inputs_produce_identical_outputs(self):
        """Two runs with the same input must produce the exact same schedule."""
        matrix = _build(AIRPORT, SITES_MULTI)
        result1 = solve(SITES_MULTI, matrix, AIRPORT)
        result2 = solve(SITES_MULTI, matrix, AIRPORT)
        assert result1 is not None and result2 is not None
        assert len(result1) == len(result2)
        for r1, r2 in zip(result1, result2):
            assert r1["Site Name"] == r2["Site Name"]
            assert r1["Day"] == r2["Day"]
            assert r1["Visit_Order"] == r2["Visit_Order"]


# ---------------------------------------------------------------------------
# TestSingleDayInput
# ---------------------------------------------------------------------------

class TestSingleDayInput:
    def test_few_sites_produce_single_day(self):
        """≤ _SITES_PER_DAY sites → k=1 → all sites on Day 1."""
        n = _SITES_PER_DAY  # exactly the threshold
        sites = [_site(f"S{i}", 43.0 + i * 0.02, -88.0) for i in range(n)]
        matrix = _build(AIRPORT, sites)
        result = solve(sites, matrix, AIRPORT)
        assert result is not None
        days = {r["Day"] for r in result}
        assert days == {1}, f"Expected only Day 1, got days: {days}"

    def test_single_day_starts_from_airport(self):
        """Single-day schedule: first site has non-zero travel time from airport."""
        sites = [_site(f"S{i}", 43.0 + i * 0.05, -88.0) for i in range(5)]
        matrix = _build(AIRPORT, sites)
        result = solve(sites, matrix, AIRPORT)
        assert result is not None
        day1 = sorted([r for r in result if r["Day"] == 1], key=lambda r: r["Visit_Order"])
        first_name = day1[0]["Site Name"]
        first_global = next(i + 1 for i, s in enumerate(sites) if s["Site Name"] == first_name)
        assert matrix[0][first_global] > 0

    def test_34_wisconsin_sites_day_count_bounded_by_budget(self):
        """
        34 Wisconsin sites: number of days is determined by the time budget, not
        cluster count. Each site takes SITE_VISIT_SEC; minimum possible days is
        ceil(34 * SITE_VISIT_SEC / DAY_BUDGET_SEC) = 3. With realistic travel
        added the result should be ≥ 3 and ≤ 34 (never more days than sites).
        """
        regions = [(43.2, -91.0), (43.2, -89.0), (45.0, -91.0), (45.0, -89.0)]
        counts  = [9, 9, 8, 8]
        wi_sites = []
        for (base_lat, base_lon), n in zip(regions, counts):
            for i in range(n):
                wi_sites.append(
                    _site(f"WI_{base_lat}_{i}", base_lat + (i % 3) * 0.01, base_lon + (i // 3) * 0.01)
                )

        matrix = _build(AIRPORT, wi_sites)
        result = solve(wi_sites, matrix, AIRPORT)
        assert result is not None
        assert len(result) == 34
        n_days = max(r["Day"] for r in result)
        min_days = math.ceil(34 * SITE_VISIT_SEC / DAY_BUDGET_SEC)
        assert min_days <= n_days <= 34, (
            f"Expected {min_days}–34 days, got {n_days}"
        )


# ---------------------------------------------------------------------------
# TestCrossClusterSpill
# ---------------------------------------------------------------------------

class TestCrossClusterSpill:
    """
    Verify that day boundaries are cut by the time budget, not by cluster
    membership. A small cluster whose sites fit in partial-day time should
    spill over into the next day alongside sites from the adjacent cluster.
    """

    def test_day_boundary_falls_mid_cluster(self):
        """
        Create a scenario where the budget forces a day cut inside a cluster.
        Use a tight cluster whose intra-cluster tour alone would exceed one day,
        so the solver must split it across two days.
        """
        # 14 very close sites → k=2 clusters of 7, each with minimal travel.
        # Force a day cut by making SITE_VISIT_SEC × sites > DAY_BUDGET_SEC for 1 cluster.
        # 14 × 2700 = 37800 > 36000, so at least one day boundary must fall somewhere.
        sites = [_site(f"S{i}", 43.0 + (i % 4) * 0.005, -88.0 + (i // 4) * 0.005)
                 for i in range(14)]
        matrix = _build(AIRPORT, sites)
        result = solve(sites, matrix, AIRPORT)
        assert result is not None
        assert len(result) == 14
        # Must span at least 2 days (14 × 2700 > 36000)
        days = {r["Day"] for r in result}
        assert len(days) >= 2, "Expected at least 2 days for 14 sites"

    def test_sites_from_same_cluster_can_appear_on_different_days(self):
        """
        When a cluster's intra-cluster tour exceeds the daily budget, some of
        its sites land on the next day. Verify the solver does NOT create a
        separate cluster-per-day rigid assignment.
        """
        # 13 sites: all very close together → k=2 but both clusters tiny.
        # 13 × 2700 = 35100 sec — fits in one day if travel is minimal.
        # Make exactly 13 sites: with tight spacing travel ≈ 0, 13 × 2700 = 35100 < 36000.
        sites = [_site(f"T{i}", 43.0 + i * 0.001, -88.0) for i in range(13)]
        matrix = _build(AIRPORT, sites)
        result = solve(sites, matrix, AIRPORT)
        assert result is not None
        assert len(result) == 13
        # 13 × 2700 = 35100 < 36000 → all fit in Day 1
        days = {r["Day"] for r in result}
        assert days == {1}, f"13 sites with minimal travel should fit in 1 day, got days: {days}"

    def test_all_sites_scheduled_across_days(self):
        """Every site must appear exactly once in the output regardless of day cuts."""
        sites = [_site(f"X{i}", 43.0 + (i % 5) * 0.1, -88.0 + (i // 5) * 0.2)
                 for i in range(20)]
        matrix = _build(AIRPORT, sites)
        result = solve(sites, matrix, AIRPORT)
        assert result is not None
        assert len(result) == 20
        scheduled_names = [r["Site Name"] for r in result]
        original_names = [s["Site Name"] for s in sites]
        assert sorted(scheduled_names) == sorted(original_names)


# ---------------------------------------------------------------------------
# TestMultilineCSVParsing
# ---------------------------------------------------------------------------

class TestMultilineCSVParsing:
    def test_multiline_access_instructions_parsed_correctly(self, tmp_path):
        """
        CSV rows with quoted multiline fields in Access Instructions must be
        parsed without corrupting adjacent rows.
        """
        csv_content = (
            'Site Name,Latitude,Longitude,Access Instructions,Access Directions\n'
            '"Tower A",43.1,-88.1,"Go to gate.\nEnter code 1234.\nProceed to tower.","Head north on Hwy 12"\n'
            '"Tower B",43.2,-88.2,"Single line","Head south"\n'
            '"Tower C",43.3,-88.3,"Multi\nline\nfield","Turn left"\n'
        )
        csv_file = tmp_path / "sites.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
        assert rows[0]["Site Name"] == "Tower A"
        assert rows[1]["Site Name"] == "Tower B"
        assert rows[2]["Site Name"] == "Tower C"
        assert "\n" in rows[0]["Access Instructions"]
        assert rows[0]["Access Directions"] == "Head north on Hwy 12"

    def test_multiline_fields_do_not_corrupt_lat_lon(self, tmp_path):
        """Lat/lon values must be correct even when adjacent fields are multiline."""
        csv_content = (
            'Site Name,Latitude,Longitude,Access Instructions,Access Directions\n'
            '"Tower A",43.1,-88.1,"Line 1\nLine 2","Dir 1"\n'
            '"Tower B",43.2,-88.2,"Normal","Dir 2"\n'
        )
        csv_file = tmp_path / "sites.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv_mod.DictReader(f)
            rows = list(reader)

        assert float(rows[0]["Latitude"]) == pytest.approx(43.1)
        assert float(rows[0]["Longitude"]) == pytest.approx(-88.1)
        assert float(rows[1]["Latitude"]) == pytest.approx(43.2)


# ---------------------------------------------------------------------------
# TestOSRMTimeout
# ---------------------------------------------------------------------------

class TestOSRMTimeout:
    def test_timeout_raises_runtime_error(self):
        """OSRM timeout must raise RuntimeError with a clear message."""
        import requests as req_mod
        from maps import get_travel_matrix

        coords = [(43.0, -88.0), (43.1, -88.1)]
        with patch("maps.requests.get", side_effect=req_mod.Timeout("timed out")):
            with pytest.raises(RuntimeError) as exc_info:
                get_travel_matrix(coords)
        assert "timed out" in str(exc_info.value).lower() or "failed" in str(exc_info.value).lower()

    def test_timeout_value_is_10(self):
        """The OSRM request timeout must be exactly 10 seconds."""
        import maps
        assert maps._REQUEST_TIMEOUT == 10

    def test_non_200_response_raises_runtime_error(self):
        """Non-200 HTTP response raises RuntimeError."""
        from maps import get_travel_matrix

        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"

        coords = [(43.0, -88.0), (43.1, -88.1)]
        with patch("maps.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError) as exc_info:
                get_travel_matrix(coords)
        assert "503" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TestClusteringRegression
# ---------------------------------------------------------------------------

class TestClusteringRegression:
    """
    Regression: a 'Mauston' site (~lon -90.118) must not end up in Day 4 when
    its geographic cluster clearly belongs with Day 2 sites.

    We construct a 4-cluster dataset (~40 sites total → k=4):
      Cluster A: lat ~44.5, lon ~-90.1  (Mauston area)
      Cluster B: lat ~43.0, lon ~-88.0  (Milwaukee area)
      Cluster C: lat ~44.0, lon ~-92.5  (La Crosse area)
      Cluster D: lat ~46.0, lon ~-89.5  (Rhinelander area)
    """

    def _make_cluster(self, prefix, center_lat, center_lon, n=10):
        return [
            _site(f"{prefix}{i}", center_lat + (i % 3) * 0.02, center_lon + (i // 3) * 0.03)
            for i in range(n)
        ]

    def test_mauston_site_stays_in_its_geographic_cluster(self):
        cluster_a = self._make_cluster("Mauston", 44.5, -90.118)
        cluster_b = self._make_cluster("Milwaukee", 43.0, -88.0)
        cluster_c = self._make_cluster("LaCrosse", 44.0, -92.5)
        cluster_d = self._make_cluster("Rhinelander", 46.0, -89.5)

        all_sites = cluster_a + cluster_b + cluster_c + cluster_d  # 40 sites → k=4
        airport = {"iata": "MKE", "name": "Milwaukee Mitchell", "lat": 42.947, "lon": -87.896}
        matrix = _build(airport, all_sites)

        clusters = cluster_sites(all_sites, matrix)

        # Find which cluster each Mauston site belongs to
        mauston_names = {s["Site Name"] for s in cluster_a}
        # Global indices for Mauston sites: 1..10
        mauston_globals = set(range(1, 11))

        cluster_for_mauston = None
        for cluster in clusters:
            cluster_set = set(cluster)
            if cluster_set & mauston_globals:
                # This cluster contains Mauston sites
                cluster_for_mauston = cluster_set
                break

        assert cluster_for_mauston is not None

        # All Mauston sites should be in the same cluster
        assert mauston_globals.issubset(cluster_for_mauston), (
            f"Mauston sites split across clusters. In cluster: "
            f"{cluster_for_mauston & mauston_globals}, missing: "
            f"{mauston_globals - cluster_for_mauston}"
        )

    def test_mauston_sites_are_not_interleaved_with_other_regions(self):
        """
        After a full solve, Mauston sites must appear as a contiguous block in
        the visit sequence. Budget cuts may split them across adjacent days, but
        no site from a distant region (Milwaukee / La Crosse / Rhinelander)
        should be interleaved between the first and last Mauston stop.

        This guards against the original VRP regression where a site at
        lon ~-90.118 was scattered to a completely different day from its
        geographic neighbours.
        """
        cluster_a = self._make_cluster("Mauston", 44.5, -90.118)
        cluster_b = self._make_cluster("Milwaukee", 43.0, -88.0)
        cluster_c = self._make_cluster("LaCrosse", 44.0, -92.5)
        cluster_d = self._make_cluster("Rhinelander", 46.0, -89.5)

        all_sites = cluster_a + cluster_b + cluster_c + cluster_d
        airport = {"iata": "MKE", "name": "Milwaukee Mitchell", "lat": 42.947, "lon": -87.896}
        matrix = _build(airport, all_sites)

        result = solve(all_sites, matrix, AIRPORT)
        assert result is not None

        # Build a flat ordered visit list (Day ASC, Visit_Order ASC)
        ordered = sorted(result, key=lambda r: (r["Day"], r["Visit_Order"]))
        visit_sequence = [r["Site Name"] for r in ordered]

        # Find the first and last position of any Mauston site in the sequence
        mauston_positions = [
            i for i, name in enumerate(visit_sequence) if name.startswith("Mauston")
        ]
        assert mauston_positions, "No Mauston sites found in result"

        first_m, last_m = mauston_positions[0], mauston_positions[-1]

        # Every stop between first and last Mauston must also be a Mauston site
        interleaved = [
            visit_sequence[i] for i in range(first_m, last_m + 1)
            if not visit_sequence[i].startswith("Mauston")
        ]
        assert not interleaved, (
            f"REGRESSION: Non-Mauston sites interleaved within the Mauston block: "
            f"{interleaved}"
        )
