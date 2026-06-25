"""Tests for the QGIS-native port of geometry_utils.py, run against the
shapely-backed qgis stub (see qgis_stub.py / README.md in this directory).
Mirrors the same vertex-distance-stats / dissolve behavior the original
shapely-based module has, since QgsGeometry's own math is GEOS-backed."""
import pytest
from qgis.core import QgsGeometry, QgsPointXY

from shoreline_uncertainty_qgis.geometry_utils_qgis import (
    dissolve,
    extract_vertices,
    vertex_nearest_stats,
)


def _line(coords):
    return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in coords])


def test_extract_vertices_linestring():
    geom = _line([(0, 0), (1, 0), (2, 0)])
    verts = extract_vertices(geom)
    assert [(p.x(), p.y()) for p in verts] == [(0, 0), (1, 0), (2, 0)]


def test_extract_vertices_empty_geometry_returns_empty_list():
    assert extract_vertices(QgsGeometry()) == []


def test_vertex_nearest_stats_min_mean_max():
    line = _line([(0, 0), (0, 10)])
    other = _line([(5, 0), (5, 10)])  # parallel line, 5 units away everywhere
    stats = vertex_nearest_stats(line, other)
    assert stats.min_dist == pytest.approx(5.0)
    assert stats.mean_dist == pytest.approx(5.0)
    assert stats.max_dist == pytest.approx(5.0)


def test_vertex_nearest_stats_varying_distance():
    # Vertices at (0,0) and (10,0); other is the point (0, 3) -- distances
    # are 3 and sqrt(10**2 + 3**2).
    line = _line([(0, 0), (10, 0)])
    other = QgsGeometry.fromPointXY(QgsPointXY(0, 3))
    stats = vertex_nearest_stats(line, other)
    assert stats.min_dist == pytest.approx(3.0)
    assert stats.max_dist == pytest.approx((10**2 + 3**2) ** 0.5)
    assert stats.mean_dist == pytest.approx((3.0 + (10**2 + 3**2) ** 0.5) / 2)


def test_vertex_nearest_stats_raises_on_no_vertices():
    with pytest.raises(ValueError):
        vertex_nearest_stats(QgsGeometry(), _line([(0, 0), (1, 1)]))


def test_dissolve_unions_overlapping_buffers():
    a = _line([(0, 0), (10, 0)]).buffer(5, 16)
    b = _line([(5, 0), (15, 0)]).buffer(5, 16)
    merged = dissolve([a, b])
    # Union area should be less than the sum of the two (since they overlap)
    # but at least as large as either one alone.
    assert merged.area() < a.area() + b.area()
    assert merged.area() >= max(a.area(), b.area())


def test_dissolve_empty_list_returns_null_geometry():
    result = dissolve([])
    assert result.isNull()
