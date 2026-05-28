"""Tests for geo.py — haversine, centroid, outlier filtering."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
from geo import haversine_miles, centroid, filter_outliers, OUTLIER_THRESHOLD_MILES


class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine_miles(40.0, -74.0, 40.0, -74.0) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_nyc_to_la(self):
        # NYC (40.71, -74.01) to LA (34.05, -118.24) ≈ 2445 miles
        dist = haversine_miles(40.71, -74.01, 34.05, -118.24)
        assert 2400 < dist < 2500

    def test_short_distance(self):
        # Two points ~1 mile apart along a latitude line
        # 1 degree latitude ≈ 69 miles, so 1/69 degree ≈ 1 mile
        dist = haversine_miles(40.0, -74.0, 40.0 + 1 / 69, -74.0)
        assert dist == pytest.approx(1.0, rel=0.05)

    def test_symmetry(self):
        d1 = haversine_miles(35.0, -90.0, 41.0, -87.0)
        d2 = haversine_miles(41.0, -87.0, 35.0, -90.0)
        assert d1 == pytest.approx(d2, rel=1e-9)

    def test_returns_float(self):
        result = haversine_miles(0, 0, 0, 1)
        assert isinstance(result, float)


class TestCentroid:
    def test_single_point(self):
        result = centroid([(10.0, 20.0)])
        assert result == pytest.approx((10.0, 20.0))

    def test_two_symmetric_points(self):
        result = centroid([(0.0, -10.0), (0.0, 10.0)])
        assert result == pytest.approx((0.0, 0.0))

    def test_multiple_points(self):
        coords = [(10.0, 20.0), (20.0, 30.0), (30.0, 40.0)]
        lat, lon = centroid(coords)
        assert lat == pytest.approx(20.0)
        assert lon == pytest.approx(30.0)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            centroid([])

    def test_returns_tuple_of_two_floats(self):
        lat, lon = centroid([(1.0, 2.0), (3.0, 4.0)])
        assert isinstance(lat, float)
        assert isinstance(lon, float)


class TestFilterOutliers:
    def _make_site(self, name, lat, lon):
        return {
            "Site Name": name,
            "Latitude": str(lat),
            "Longitude": str(lon),
            "Access Instructions": "",
            "Access Directions": "",
        }

    def test_no_outliers_when_all_close(self):
        sites = [
            self._make_site("A", 40.0, -74.0),
            self._make_site("B", 40.1, -74.1),
            self._make_site("C", 39.9, -73.9),
        ]
        kept, outliers = filter_outliers(sites)
        assert len(kept) == 3
        assert len(outliers) == 0

    def test_outlier_far_away(self):
        # Verify that a site far from a tight cluster is identified as an outlier.
        # Use sites in a small geographic area vs one clearly remote site, and
        # use a small threshold so the math is deterministic.
        # Five sites within a mile of each other near Atlanta (33.75, -84.39)
        atlanta_sites = [
            self._make_site("ATL1", 33.750, -84.390),
            self._make_site("ATL2", 33.751, -84.391),
            self._make_site("ATL3", 33.749, -84.389),
            self._make_site("ATL4", 33.752, -84.388),
            self._make_site("ATL5", 33.748, -84.392),
        ]
        # One site ~50 miles away
        remote = self._make_site("REMOTE", 34.27, -84.39)  # ~37 miles north
        sites = atlanta_sites + [remote]
        kept, outliers = filter_outliers(sites, threshold_miles=20)
        assert len(outliers) == 1
        assert outliers[0]["Site Name"] == "REMOTE"
        assert len(kept) == 5

    def test_empty_input(self):
        kept, outliers = filter_outliers([])
        assert kept == []
        assert outliers == []

    def test_single_site_always_kept(self):
        sites = [self._make_site("Only", 35.0, -90.0)]
        kept, outliers = filter_outliers(sites)
        assert len(kept) == 1
        assert len(outliers) == 0

    def test_custom_threshold(self):
        # Tight threshold: 10 miles — second site is 50 miles away, should be outlier
        sites = [
            self._make_site("Center", 40.0, -74.0),
            self._make_site("Far", 40.72, -74.0),  # ~50 miles north
        ]
        kept, outliers = filter_outliers(sites, threshold_miles=10)
        # centroid is halfway; each is ~25 miles from centroid — both within 25 miles
        # Let's use a very tight threshold
        kept2, outliers2 = filter_outliers(sites, threshold_miles=5)
        # Both should be outliers since they're ~25 miles from the centroid
        assert len(outliers2) == 2

    def test_preserves_all_fields(self):
        sites = [
            {
                "Site Name": "Alpha",
                "Latitude": "40.0",
                "Longitude": "-74.0",
                "Access Instructions": "Gate code 1234",
                "Access Directions": "Turn left",
            }
        ]
        kept, _ = filter_outliers(sites)
        assert kept[0]["Access Instructions"] == "Gate code 1234"
        assert kept[0]["Access Directions"] == "Turn left"

    def test_uses_default_threshold_constant(self):
        assert OUTLIER_THRESHOLD_MILES == 200
