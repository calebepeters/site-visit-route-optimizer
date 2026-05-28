"""Tests for airports.py — loading and nearest airport lookup."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import csv
import tempfile
import pytest
from airports import load_airports, nearest_airport


class TestLoadAirports:
    def test_loads_bundled_csv(self):
        airports = load_airports()
        assert len(airports) >= 50

    def test_bundled_csv_has_required_fields(self):
        airports = load_airports()
        for ap in airports:
            assert "iata" in ap
            assert "name" in ap
            assert "lat" in ap
            assert "lon" in ap

    def test_bundled_csv_lat_lon_are_floats(self):
        airports = load_airports()
        for ap in airports:
            assert isinstance(ap["lat"], float)
            assert isinstance(ap["lon"], float)

    def test_bundled_csv_contains_major_hubs(self):
        airports = load_airports()
        iatas = {ap["iata"] for ap in airports}
        for hub in ("ATL", "LAX", "ORD", "DFW", "DEN", "JFK", "SFO"):
            assert hub in iatas, f"{hub} not found in bundled airports"

    def test_custom_csv_path(self):
        rows = [
            {"iata": "TST", "name": "Test Airport", "lat": "35.0", "lon": "-90.0"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            writer = csv.DictWriter(f, fieldnames=["iata", "name", "lat", "lon"])
            writer.writeheader()
            writer.writerows(rows)
            tmp_path = f.name

        try:
            airports = load_airports(tmp_path)
            assert len(airports) == 1
            assert airports[0]["iata"] == "TST"
            assert airports[0]["lat"] == 35.0
        finally:
            os.unlink(tmp_path)

    def test_empty_csv_raises(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline=""
        ) as f:
            writer = csv.DictWriter(f, fieldnames=["iata", "name", "lat", "lon"])
            writer.writeheader()
            # No data rows
            tmp_path = f.name

        try:
            with pytest.raises(ValueError, match="No airports found"):
                load_airports(tmp_path)
        finally:
            os.unlink(tmp_path)


class TestNearestAirport:
    def _sample_airports(self):
        return [
            {"iata": "JFK", "name": "JFK Airport", "lat": 40.64, "lon": -73.78},
            {"iata": "LAX", "name": "LAX Airport", "lat": 33.94, "lon": -118.41},
            {"iata": "ORD", "name": "ORD Airport", "lat": 41.97, "lon": -87.91},
            {"iata": "ATL", "name": "ATL Airport", "lat": 33.64, "lon": -84.43},
            {"iata": "DEN", "name": "DEN Airport", "lat": 39.86, "lon": -104.67},
        ]

    def test_nearest_to_nyc_is_jfk(self):
        airports = self._sample_airports()
        result = nearest_airport(40.71, -74.01, airports)
        assert result["iata"] == "JFK"

    def test_nearest_to_chicago_is_ord(self):
        airports = self._sample_airports()
        result = nearest_airport(41.88, -87.63, airports)
        assert result["iata"] == "ORD"

    def test_nearest_to_la_is_lax(self):
        airports = self._sample_airports()
        result = nearest_airport(34.05, -118.24, airports)
        assert result["iata"] == "LAX"

    def test_nearest_to_denver_is_den(self):
        airports = self._sample_airports()
        result = nearest_airport(39.73, -104.99, airports)
        assert result["iata"] == "DEN"

    def test_returns_dict_with_all_fields(self):
        airports = self._sample_airports()
        result = nearest_airport(40.0, -74.0, airports)
        assert "iata" in result
        assert "name" in result
        assert "lat" in result
        assert "lon" in result

    def test_single_airport_always_returned(self):
        airports = [{"iata": "XYZ", "name": "Only Airport", "lat": 0.0, "lon": 0.0}]
        result = nearest_airport(90.0, 0.0, airports)
        assert result["iata"] == "XYZ"

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            nearest_airport(40.0, -74.0, [])

    def test_uses_bundled_airports(self):
        """Integration check: bundled list returns a sensible airport for known locations."""
        airports = load_airports()
        # Dallas area → DFW
        result = nearest_airport(32.90, -97.04, airports)
        assert result["iata"] in ("DFW", "DAL", "HOU", "SAT")  # nearby Texas airports
