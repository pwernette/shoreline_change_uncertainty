"""Tests for water_level.py (NOAA CO-OPS lookups) and the `water-levels` CLI
subcommand. All network calls are mocked -- nothing here makes a live HTTP
request, matching the rest of this test suite's offline/deterministic
convention even though the module under test is the one exception in the
package that calls out to a live API in normal use.
"""
from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import geopandas as gpd
import pytest
import yaml
from shapely.geometry import Point

from shoreline_uncertainty import water_level as wl
from shoreline_uncertainty.cli import _run_water_levels


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


def _mock_session(*payloads: dict) -> MagicMock:
    """A fake `requests`-like object whose .get() returns each payload in
    sequence on successive calls (so fallback-widening retries can be
    tested deterministically)."""
    session = MagicMock()
    session.get.side_effect = [_mock_response(p) for p in payloads]
    return session


SF_STATION = wl.WaterLevelStation(id="9414290", name="San Francisco, CA", lat=37.806, lng=-122.465, greatlakes=False)
ALPENA_STATION = wl.WaterLevelStation(id="9075065", name="Alpena, MI", lat=45.063, lng=-83.430, greatlakes=True)
NEARBY_STATION = wl.WaterLevelStation(id="9999999", name="Nearby, CA", lat=37.81, lng=-122.47, greatlakes=False)
FAR_STATION = wl.WaterLevelStation(id="1111111", name="Far Away", lat=0.0, lng=0.0, greatlakes=False)


# ---------------------------------------------------------------------------
# _haversine_nm / site_lat_lon
# ---------------------------------------------------------------------------


def test_haversine_nm_one_degree_latitude_is_about_60nm():
    # One degree of latitude is ~60 nautical miles by definition of the nm.
    d = wl._haversine_nm(0.0, 0.0, 1.0, 0.0)
    assert 59.0 < d < 61.0


def test_haversine_nm_zero_for_same_point():
    assert wl._haversine_nm(37.8, -122.4, 37.8, -122.4) == pytest.approx(0.0, abs=1e-9)


def test_site_lat_lon_reprojects_to_wgs84():
    # A point at UTM zone 16N's false-origin-relative (500000, 0) sits right
    # on the equator at -87 deg longitude (zone 16's central meridian).
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(500000.0, 0.0)], crs="EPSG:32616")
    lat, lon = wl.site_lat_lon(gdf)
    assert lat == pytest.approx(0.0, abs=0.01)
    assert lon == pytest.approx(-87.0, abs=0.01)


# ---------------------------------------------------------------------------
# fetch_station_list
# ---------------------------------------------------------------------------


def test_fetch_station_list_parses_and_caches(tmp_path):
    cache_path = tmp_path / "stations.json"
    payload = {
        "stations": [
            {"id": "9414290", "name": "San Francisco, CA", "lat": 37.806, "lng": -122.465, "greatlakes": False},
            {"id": "9075065", "name": "Alpena, MI", "lat": 45.063, "lng": -83.430, "greatlakes": True},
        ]
    }
    session = _mock_session(payload)
    stations = wl.fetch_station_list(cache_path=cache_path, session=session)
    assert len(stations) == 2
    assert stations[0].id == "9414290"
    assert stations[1].greatlakes is True
    assert session.get.call_count == 1

    # Cache hit on the second call -- no further network access, even with a
    # session whose .get would now raise if it were actually invoked again.
    session.get.side_effect = AssertionError("should not be called -- cache should have been used")
    stations_again = wl.fetch_station_list(cache_path=cache_path, session=session)
    assert len(stations_again) == 2


def test_fetch_station_list_refetches_corrupt_cache(tmp_path):
    cache_path = tmp_path / "stations.json"
    cache_path.write_text("not valid json{{{")
    payload = {"stations": [{"id": "1", "name": "X", "lat": 1.0, "lng": 2.0, "greatlakes": False}]}
    session = _mock_session(payload)
    stations = wl.fetch_station_list(cache_path=cache_path, session=session)
    assert len(stations) == 1
    assert session.get.call_count == 1


# ---------------------------------------------------------------------------
# find_nearest_station
# ---------------------------------------------------------------------------


def test_find_nearest_station_picks_closest():
    stations = [SF_STATION, NEARBY_STATION, FAR_STATION]
    # Query right at NEARBY_STATION's own coordinates, so it's unambiguously
    # the closest candidate (distance 0) regardless of SF_STATION's exact
    # offset.
    nearest = wl.find_nearest_station(NEARBY_STATION.lat, NEARBY_STATION.lng, stations=stations)
    assert nearest.id == NEARBY_STATION.id
    assert nearest.distance_nm is not None
    assert nearest.distance_nm < 1


def test_find_nearest_station_prefer_greatlakes_filters_candidates():
    stations = [SF_STATION, ALPENA_STATION]
    nearest = wl.find_nearest_station(45.0, -83.4, stations=stations, prefer_greatlakes=True)
    assert nearest.id == ALPENA_STATION.id


def test_find_nearest_station_empty_after_filter_raises():
    stations = [SF_STATION]
    with pytest.raises(wl.WaterLevelError):
        wl.find_nearest_station(45.0, -83.4, stations=stations, prefer_greatlakes=True)


def test_find_nearest_station_max_distance_raises():
    stations = [FAR_STATION]
    with pytest.raises(wl.WaterLevelError):
        wl.find_nearest_station(37.8, -122.46, stations=stations, max_distance_nm=10)


# ---------------------------------------------------------------------------
# get_water_level
# ---------------------------------------------------------------------------


def test_get_water_level_marine_uses_hourly_height_and_lst_no_fallback():
    payload = {"data": [{"t": "2020-06-15 00:00", "v": "1.0"}, {"t": "2020-06-15 01:00", "v": "3.0"}]}
    session = _mock_session(payload)
    result = wl.get_water_level(
        37.806, -122.465, "2020-06-15", stations=[SF_STATION], session=session,
    )
    assert result.value == pytest.approx(2.0)
    assert result.value_type == "hourly_height"
    assert result.fallback_used is None
    assert result.station.id == SF_STATION.id
    assert result.datum == "MSL"
    called_params = session.get.call_args.kwargs["params"]
    assert called_params["product"] == "hourly_height"
    assert called_params["time_zone"] == "lst"


def test_get_water_level_greatlakes_uses_daily_mean_and_igld_default():
    payload = {"data": [{"t": "2020-06-15", "v": "176.5"}]}
    session = _mock_session(payload)
    result = wl.get_water_level(
        45.063, -83.430, "2020-06-15", stations=[ALPENA_STATION], session=session,
    )
    assert result.value == pytest.approx(176.5)
    assert result.value_type == "daily_mean"
    assert result.datum == "IGLD"
    called_params = session.get.call_args.kwargs["params"]
    assert called_params["product"] == "daily_mean"


def test_get_water_level_widens_window_on_empty_data_and_records_fallback():
    empty_payload = {"data": []}
    good_payload = {"data": [{"t": "2020-06-14", "v": "2.5"}]}
    session = _mock_session(empty_payload, good_payload)
    result = wl.get_water_level(
        37.806, -122.465, "2020-06-15", stations=[SF_STATION], session=session, max_window_days=4,
    )
    assert result.value == pytest.approx(2.5)
    assert result.fallback_used is not None
    assert "widened" in result.fallback_used
    assert session.get.call_count == 2


def test_get_water_level_raises_after_exhausting_fallback():
    session = _mock_session({"data": []}, {"data": []}, {"data": []}, {"data": []})
    with pytest.raises(wl.WaterLevelError):
        wl.get_water_level(
            37.806, -122.465, "2020-06-15", stations=[SF_STATION], session=session, max_window_days=3,
        )


def test_get_water_level_accepts_date_object():
    import datetime

    payload = {"data": [{"t": "2020-06-15", "v": "1.0"}]}
    session = _mock_session(payload)
    result = wl.get_water_level(
        37.806, -122.465, datetime.date(2020, 6, 15), stations=[SF_STATION], session=session,
    )
    assert result.value == pytest.approx(1.0)


def test_get_water_level_propagates_explicit_datum_override():
    payload = {"data": [{"t": "2020-06-15", "v": "1.0"}]}
    session = _mock_session(payload)
    result = wl.get_water_level(
        37.806, -122.465, "2020-06-15", stations=[SF_STATION], session=session, datum="NAVD",
    )
    assert result.datum == "NAVD"


# ---------------------------------------------------------------------------
# get_annual_water_level
# ---------------------------------------------------------------------------


def test_get_annual_water_level_averages_monthly_means():
    payload = {"data": [{"year": "2010", "month": str(m), "v": str(m)} for m in range(1, 13)]}
    session = _mock_session(payload)
    result = wl.get_annual_water_level(37.806, -122.465, 2010, stations=[SF_STATION], session=session)
    assert result.value == pytest.approx(sum(range(1, 13)) / 12)
    assert result.value_type == "monthly_mean"
    assert result.period_start == "2010-01-01"
    assert result.period_end == "2010-12-31"


def test_get_annual_water_level_raises_when_no_data():
    session = _mock_session({"data": []})
    with pytest.raises(wl.WaterLevelError):
        wl.get_annual_water_level(37.806, -122.465, 1880, stations=[SF_STATION], session=session)


def test_request_datagetter_raises_on_error_payload():
    session = _mock_session({"error": {"message": "No data was found."}})
    with pytest.raises(wl.WaterLevelError, match="No data was found"):
        wl._request_datagetter({"station": "9414290"}, session=session)


# ---------------------------------------------------------------------------
# `water-levels` CLI subcommand
# ---------------------------------------------------------------------------


def test_run_water_levels_cli_writes_csv_for_annual_and_date_specific(monkeypatch, synthetic_site, tmp_path):
    paths = synthetic_site["paths"]
    raw_config = {
        "output_dir": str(tmp_path / "out"),
        "sites": [
            {
                "name": "test_site",
                "shorelines": [
                    {"year": 2000, "path": paths[2000], "rmse95_override": 2.0},
                    {
                        "year": 2010,
                        "path": paths[2010],
                        "rmse95_override": 2.0,
                        "acquisition_date": "2010-07-04",
                    },
                ],
            }
        ],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw_config))

    annual_result = wl.WaterLevelResult(
        station=SF_STATION, datum="MSL", units="metric", value=1.23, value_type="monthly_mean",
        period_start="2000-01-01", period_end="2000-12-31", n_observations=12, fallback_used=None,
    )
    date_result = wl.WaterLevelResult(
        station=SF_STATION, datum="MSL", units="metric", value=4.56, value_type="hourly_height",
        period_start="2010-07-04", period_end="2010-07-04", n_observations=24, fallback_used=None,
    )

    monkeypatch.setattr("shoreline_uncertainty.cli.get_annual_water_level", lambda *a, **k: annual_result)
    monkeypatch.setattr("shoreline_uncertainty.cli.get_water_level", lambda *a, **k: date_result)

    args = argparse.Namespace(
        config=str(config_path), out=None, datum=None, window_days=0, sleep=0.0,
    )
    df = _run_water_levels(args)

    assert len(df) == 2
    assert df["error"].isna().all()
    row_2000 = df[df["year"] == 2000].iloc[0]
    row_2010 = df[df["year"] == 2010].iloc[0]
    assert row_2000["water_level"] == pytest.approx(1.23)
    assert row_2000["value_type"] == "monthly_mean"
    assert row_2010["water_level"] == pytest.approx(4.56)
    assert row_2010["value_type"] == "hourly_height"
    assert row_2010["acquisition_date"] == "2010-07-04"

    out_path = tmp_path / "out" / "water_levels.csv"
    assert out_path.exists()


def test_run_water_levels_cli_records_error_without_aborting(monkeypatch, synthetic_site, tmp_path):
    paths = synthetic_site["paths"]
    raw_config = {
        "output_dir": str(tmp_path / "out"),
        "sites": [
            {
                "name": "test_site",
                "shorelines": [
                    {"year": 2000, "path": paths[2000], "rmse95_override": 2.0},
                    {"year": 2010, "path": paths[2010], "rmse95_override": 2.0},
                ],
            }
        ],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(raw_config))

    def _boom(*a, **k):
        raise wl.WaterLevelError("no station nearby")

    monkeypatch.setattr("shoreline_uncertainty.cli.get_annual_water_level", _boom)

    args = argparse.Namespace(
        config=str(config_path), out=str(tmp_path / "wl.csv"), datum=None, window_days=0, sleep=0.0,
    )
    df = _run_water_levels(args)

    assert len(df) == 2
    assert (df["error"] == "no station nearby").all()
