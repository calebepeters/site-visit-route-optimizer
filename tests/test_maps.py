"""Tests for maps.py — OSRM matrix fetch with caching (mocked)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock

import maps  # import the module so we can patch its globals


class TestCacheKey:
    """Test internal cache key stability and consistency."""

    def test_same_coords_same_key(self):
        from maps import _cache_key
        coords = [(40.0, -74.0), (34.0, -118.0)]
        assert _cache_key(coords) == _cache_key(coords)

    def test_different_coords_different_key(self):
        from maps import _cache_key
        coords1 = [(40.0, -74.0)]
        coords2 = [(41.0, -74.0)]
        assert _cache_key(coords1) != _cache_key(coords2)

    def test_order_independent(self):
        """Cache key should be order-independent (coords are sorted internally)."""
        from maps import _cache_key
        coords_a = [(40.0, -74.0), (34.0, -118.0)]
        coords_b = [(34.0, -118.0), (40.0, -74.0)]
        assert _cache_key(coords_a) == _cache_key(coords_b)


class TestGetTravelMatrix:
    """Test get_travel_matrix with mocked HTTP and temp cache files."""

    @pytest.fixture(autouse=True)
    def temp_cache(self, tmp_path, monkeypatch):
        """Redirect cache file to a temp directory."""
        cache_file = str(tmp_path / ".osrm_cache.json")
        monkeypatch.setattr(maps, "CACHE_FILE", cache_file)
        self.cache_file = cache_file

    def _mock_response(self, durations):
        """Build a mock requests.Response-like object."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": "Ok", "durations": durations}
        return mock_resp

    def test_returns_matrix_from_osrm(self):
        durations = [[0, 300], [280, 0]]
        coords = [(40.0, -74.0), (34.0, -118.0)]

        with patch("maps.requests.get", return_value=self._mock_response(durations)) as mock_get:
            result = maps.get_travel_matrix(coords)

        assert result == durations
        mock_get.assert_called_once()

    def test_caches_result_to_disk(self):
        durations = [[0, 600], [580, 0]]
        coords = [(41.0, -73.0), (35.0, -119.0)]

        with patch("maps.requests.get", return_value=self._mock_response(durations)):
            maps.get_travel_matrix(coords)

        assert os.path.exists(self.cache_file)
        with open(self.cache_file) as f:
            cache = json.load(f)
        assert len(cache) == 1

    def test_cache_hit_skips_http(self):
        durations = [[0, 900], [850, 0]]
        coords = [(42.0, -72.0), (36.0, -120.0)]

        with patch("maps.requests.get", return_value=self._mock_response(durations)) as mock_get:
            maps.get_travel_matrix(coords)  # first call — hits OSRM
            maps.get_travel_matrix(coords)  # second call — should use cache

        assert mock_get.call_count == 1  # only one real HTTP request

    def test_cache_returns_correct_data(self):
        durations = [[0, 1200], [1100, 0]]
        coords = [(43.0, -71.0), (37.0, -117.0)]

        with patch("maps.requests.get", return_value=self._mock_response(durations)):
            first_result = maps.get_travel_matrix(coords)

        with patch("maps.requests.get") as mock_get:
            second_result = maps.get_travel_matrix(coords)
            mock_get.assert_not_called()

        assert first_result == second_result

    def test_none_values_replaced_with_large_number(self):
        durations = [[0, None], [None, 0]]
        coords = [(44.0, -70.0), (38.0, -116.0)]

        with patch("maps.requests.get", return_value=self._mock_response(durations)):
            result = maps.get_travel_matrix(coords)

        assert result[0][1] == 9999999.0
        assert result[1][0] == 9999999.0
        assert result[0][0] == 0
        assert result[1][1] == 0

    def test_http_error_raises_runtime_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        coords = [(45.0, -69.0), (39.0, -115.0)]

        with patch("maps.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                maps.get_travel_matrix(coords)

    def test_osrm_error_code_raises_runtime_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": "InvalidQuery", "message": "Bad coordinates"}
        coords = [(46.0, -68.0), (40.0, -114.0)]

        with patch("maps.requests.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="InvalidQuery"):
                maps.get_travel_matrix(coords)

    def test_network_exception_raises_runtime_error(self):
        import requests as req_lib
        coords = [(47.0, -67.0), (41.0, -113.0)]

        with patch("maps.requests.get", side_effect=req_lib.ConnectionError("no network")):
            with pytest.raises(RuntimeError, match="OSRM request failed"):
                maps.get_travel_matrix(coords)

    def test_empty_coords_returns_empty(self):
        result = maps.get_travel_matrix([])
        assert result == []

    def test_single_coord_2x2_not_required(self):
        durations = [[0]]
        coords = [(48.0, -66.0)]

        with patch("maps.requests.get", return_value=self._mock_response(durations)):
            result = maps.get_travel_matrix(coords)

        assert result == [[0]]
