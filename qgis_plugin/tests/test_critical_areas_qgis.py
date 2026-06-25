"""Tests for the QGIS-native port of critical_areas.py, run against the
shapely-backed qgis stub. Mirrors tests/test_critical_areas.py, adapted to
read a QgsVectorLayer instead of a GeoDataFrame for the segments output."""
from qgis.core import QgsGeometry, QgsPointXY

from shoreline_uncertainty_qgis.critical_areas_qgis import identify_critical_areas


def _line(coords):
    return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in coords])


def test_identify_critical_areas_only_year_lt_k():
    geoms = {
        2000: _line([(0, 0), (100, 0)]),
        2010: _line([(0, 1), (100, 1)]),
        2020: _line([(0, 2), (100, 2)]),
    }
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616", step=0.25,
    )
    pairs = set(zip(summary["FROM_YEAR"], summary["TO_YEAR"]))
    assert pairs == {(2000, 2010), (2000, 2020), (2010, 2020)}
    assert (2010, 2000) not in pairs


def test_identify_critical_areas_returns_segments_layer():
    geoms = {
        2000: _line([(0, 0), (100, 0)]),
        2010: _line([(0, 1), (100, 1)]),
    }
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616", step=0.25,
    )
    assert segments.featureCount() >= 1
    assert segments.crs().isValid()
    assert {"SITE", "FROM_YEAR", "TO_YEAR", "PCT"} <= set(segments.fields().names())


def test_identify_critical_areas_export_table_false_still_returns_segments():
    geoms = {
        2000: _line([(0, 0), (100, 0)]),
        2010: _line([(0, 1), (100, 1)]),
    }
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616", step=0.25, export_table=False,
    )
    assert summary.empty
    assert segments.featureCount() >= 1


def test_identify_critical_areas_empty_when_no_pairs():
    geoms = {2000: _line([(0, 0), (100, 0)])}
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616",
    )
    assert summary.empty
    assert segments.featureCount() == 0
