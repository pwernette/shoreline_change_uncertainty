"""Tests confirming CRS handling -- in particular that EPSG codes (as
strings like 'EPSG:32616', or as bare ints like 32616, however a YAML config
happens to parse them) are accepted everywhere a CRS is expected, and that
auto-UTM detection works when no target_crs is given."""
import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import LineString

from shoreline_uncertainty.io_utils import ensure_projected, read_shoreline, utm_epsg_for, write_vector


def _geographic_gdf():
    # A short line near Saginaw Bay, MI -- WGS84 lon/lat, well within UTM zone 17N.
    return gpd.GeoDataFrame(
        {"a": [1]}, geometry=[LineString([(-83.9, 43.6), (-83.8, 43.65)])], crs="EPSG:4326"
    )


def test_ensure_projected_accepts_epsg_string():
    out = ensure_projected(_geographic_gdf(), "EPSG:32616")
    assert CRS(out.crs).to_epsg() == 32616


def test_ensure_projected_accepts_bare_epsg_int():
    # YAML parses an unquoted `target_crs: 32616` as a Python int, not a str.
    out = ensure_projected(_geographic_gdf(), 32616)
    assert CRS(out.crs).to_epsg() == 32616


def test_ensure_projected_auto_detects_utm_when_no_target_given():
    out = ensure_projected(_geographic_gdf(), None)
    # centroid lon ~ -83.85 -> UTM zone 17N -> EPSG:32617
    assert CRS(out.crs).to_epsg() == 32617


def test_ensure_projected_passthrough_for_already_projected_data():
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[LineString([(0, 0), (100, 0)])], crs="EPSG:32616")
    out = ensure_projected(gdf, None)
    assert CRS(out.crs).to_epsg() == 32616


def test_utm_epsg_for_southern_hemisphere():
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[LineString([(151.2, -33.9), (151.3, -33.8)])], crs="EPSG:4326")
    # Sydney, Australia -> UTM zone 56S -> EPSG:32756
    assert utm_epsg_for(gdf) == 32756


def test_read_shoreline_requires_crs(tmp_path):
    # A GeoDataFrame written without a CRS, then read back, should raise --
    # mirrors the original requirement that input shapefiles carry a .prj.
    path = tmp_path / "no_crs.shp"
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[LineString([(0, 0), (1, 1)])])
    gdf.to_file(path)
    with pytest.raises(ValueError):
        read_shoreline(path)


def test_write_vector_then_read_shoreline_roundtrip_preserves_epsg(tmp_path):
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[LineString([(0, 0), (100, 0)])], crs="EPSG:32616")
    path = tmp_path / "roundtrip.shp"
    write_vector(gdf, path)
    back = read_shoreline(path)
    assert CRS(back.crs).to_epsg() == 32616
