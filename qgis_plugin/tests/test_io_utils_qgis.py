"""Tests for the QGIS-native port of io_utils.py, run against the
shapely/geopandas-backed qgis stub (see qgis_stub.py / README.md in this
directory). Mirrors tests/test_io_utils.py in the standalone package --
same CRS-handling guarantees (bare EPSG ints accepted, missing-CRS is an
error, auto-UTM detection, projected-passthrough, roundtrip) -- just
exercised through QgsVectorLayer instead of GeoDataFrame."""
import geopandas as gpd
import pytest
from pyproj import CRS
from shapely.geometry import LineString

from shoreline_uncertainty_qgis.io_utils_qgis import (
    ensure_projected,
    read_shoreline,
    utm_epsg_for,
    write_vector,
)


def _geographic_shp(tmp_path, name="geo.shp"):
    # A short line near Saginaw Bay, MI -- WGS84 lon/lat, well within UTM zone 17N.
    path = tmp_path / name
    gdf = gpd.GeoDataFrame(
        {"a": [1]}, geometry=[LineString([(-83.9, 43.6), (-83.8, 43.65)])], crs="EPSG:4326"
    )
    gdf.to_file(path)
    return path


def test_ensure_projected_accepts_epsg_string(tmp_path):
    layer = read_shoreline(_geographic_shp(tmp_path))
    out = ensure_projected(layer, "EPSG:32616")
    assert CRS(out.crs().authid()).to_epsg() == 32616


def test_ensure_projected_accepts_bare_epsg_int(tmp_path):
    # YAML parses an unquoted `target_crs: 32616` as a Python int, not a str.
    layer = read_shoreline(_geographic_shp(tmp_path))
    out = ensure_projected(layer, 32616)
    assert CRS(out.crs().authid()).to_epsg() == 32616


def test_ensure_projected_auto_detects_utm_when_no_target_given(tmp_path):
    layer = read_shoreline(_geographic_shp(tmp_path))
    out = ensure_projected(layer, None)
    # centroid lon ~ -83.85 -> UTM zone 17N -> EPSG:32617
    assert CRS(out.crs().authid()).to_epsg() == 32617


def test_ensure_projected_passthrough_for_already_projected_data(tmp_path):
    path = tmp_path / "projected.shp"
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[LineString([(0, 0), (100, 0)])], crs="EPSG:32616")
    gdf.to_file(path)
    layer = read_shoreline(path)
    out = ensure_projected(layer, None)
    assert CRS(out.crs().authid()).to_epsg() == 32616


def test_utm_epsg_for_southern_hemisphere(tmp_path):
    path = tmp_path / "sydney.shp"
    gdf = gpd.GeoDataFrame(
        {"a": [1]}, geometry=[LineString([(151.2, -33.9), (151.3, -33.8)])], crs="EPSG:4326"
    )
    gdf.to_file(path)
    layer = read_shoreline(path)
    # Sydney, Australia -> UTM zone 56S -> EPSG:32756
    assert utm_epsg_for(layer) == 32756


def test_read_shoreline_requires_crs(tmp_path):
    # A file written without a CRS, then read back, should raise -- mirrors
    # the original requirement that input shapefiles carry a .prj.
    path = tmp_path / "no_crs.shp"
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[LineString([(0, 0), (1, 1)])])
    gdf.to_file(path)
    with pytest.raises(ValueError):
        read_shoreline(path)


def test_write_vector_then_read_shoreline_roundtrip_preserves_epsg(tmp_path):
    path = tmp_path / "src.shp"
    gdf = gpd.GeoDataFrame({"a": [1]}, geometry=[LineString([(0, 0), (100, 0)])], crs="EPSG:32616")
    gdf.to_file(path)
    layer = read_shoreline(path)

    out_path = tmp_path / "roundtrip.shp"
    write_vector(layer, out_path)
    back = read_shoreline(out_path)
    assert CRS(back.crs().authid()).to_epsg() == 32616


def test_write_vector_noop_for_empty_layer(tmp_path):
    # No layer/feature -- should not raise and should not create a file.
    out_path = tmp_path / "should_not_exist.shp"
    write_vector(None, out_path)
    assert not out_path.exists()
