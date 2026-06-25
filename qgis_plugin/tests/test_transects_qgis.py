"""Tests for the QGIS-native port of transects.py, run against the
shapely-backed qgis stub. Mirrors tests/test_transects.py's expectations,
adapted to build/read QgsGeometry and a QgsVectorLayer instead of shapely
geometries and a GeoDataFrame directly."""
import math

import numpy as np
import pandas as pd
import pytest
from qgis.core import QgsGeometry, QgsPointXY, QgsVectorLayer

from shoreline_uncertainty_qgis.transects_qgis import (
    Transect,
    build_baseline,
    generate_transects,
    intersect_transects_shorelines,
    nearest_transect_net_distance,
    order_transect_start,
    to_wide_table,
    transects_to_layer,
)


def _line(coords):
    return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in coords])


def _wavy_shoreline_layer():
    from qgis.core import QgsFeature

    xs = np.linspace(0.0, 1000.0, 60)
    ys = 2.0 * np.sin(xs / 120.0)
    layer = QgsVectorLayer("LineString?crs=EPSG:32616", "shoreline", "memory")
    feat = QgsFeature(layer.fields())
    feat.setGeometry(_line(list(zip(xs, ys))))
    layer.dataProvider().addFeatures([feat])
    return layer


def test_compute_baseline_direction_horizontal_line():
    from shoreline_uncertainty_qgis.transects_qgis import compute_baseline_direction

    layer = _wavy_shoreline_layer()
    center, direction = compute_baseline_direction(layer)
    # The synthetic shoreline is a gently wavy, roughly east-west line ->
    # dominant direction should be ~horizontal (|dx| >> |dy|).
    dx, dy = direction
    assert abs(dx) > abs(dy)


def test_build_baseline_length_and_center():
    line = build_baseline((0.0, 0.0), (1.0, 0.0), length=10.0)
    assert line.length() == pytest.approx(10.0)
    coords = line.asPolyline()
    assert (coords[0].x(), coords[0].y()) == pytest.approx((-5.0, 0.0))
    assert (coords[1].x(), coords[1].y()) == pytest.approx((5.0, 0.0))


@pytest.mark.parametrize("priority", ["UPPER_LEFT", "UPPER_RIGHT", "LOWER_LEFT", "LOWER_RIGHT"])
def test_order_transect_start_is_idempotent(priority):
    line = _line([(0, 0), (10, 10)])
    once = order_transect_start(line, priority)
    twice = order_transect_start(once, priority)
    once_coords = [(p.x(), p.y()) for p in once.asPolyline()]
    twice_coords = [(p.x(), p.y()) for p in twice.asPolyline()]
    assert once_coords == twice_coords


def test_order_transect_start_upper_left_picks_expected_endpoint():
    # UPPER_LEFT priority key is (x, -y); smaller x and larger y should win.
    line = _line([(10, 0), (0, 10)])
    oriented = order_transect_start(line, "UPPER_LEFT")
    first = oriented.asPolyline()[0]
    assert (first.x(), first.y()) == (0, 10)


def test_generate_transects_count_and_perpendicularity():
    baseline = _line([(0, 0), (100, 0)])
    transects = generate_transects(baseline, spacing=25.0, transect_length=20.0)
    # 100m baseline / 25m spacing -> 4 steps -> 5 transects (0,25,50,75,100)
    assert len(transects) == 5
    for t in transects:
        assert isinstance(t, Transect)
        assert t.geometry.length() == pytest.approx(20.0)
        # Each transect should be perpendicular to the (horizontal) baseline,
        # i.e. roughly vertical: dx ~ 0.
        coords = t.geometry.asPolyline()
        x0, y0 = coords[0].x(), coords[0].y()
        x1, y1 = coords[-1].x(), coords[-1].y()
        assert abs(x1 - x0) < 1e-6


def test_generate_transects_rejects_zero_length_baseline():
    baseline = _line([(5, 5), (5, 5)])
    with pytest.raises(ValueError):
        generate_transects(baseline, spacing=10.0, transect_length=10.0)


def test_intersect_transects_shorelines_and_wide_pivot():
    baseline = _line([(0, 0), (100, 0)])
    transects = generate_transects(baseline, spacing=50.0, transect_length=20.0)
    shorelines_by_year = {
        2000: _line([(-10, 1), (110, 1)]),
        2010: _line([(-10, -2), (110, -2)]),
    }
    long_table = intersect_transects_shorelines(transects, shorelines_by_year)
    assert set(long_table["YEAR"]) == {2000, 2010}
    assert {"TRANSECT_ID", "YEAR", "DISTANCE", "X", "Y"} <= set(long_table.columns)

    wide = to_wide_table(long_table)
    assert "TO_2000" in wide.columns
    assert "TO_2010" in wide.columns
    assert len(wide) == len(transects)


def test_to_wide_table_empty_passthrough():
    empty = pd.DataFrame(columns=["TRANSECT_ID", "YEAR", "DISTANCE", "X", "Y"])
    assert to_wide_table(empty).empty


def test_transects_to_layer_crs_and_columns():
    baseline = _line([(0, 0), (50, 0)])
    transects = generate_transects(baseline, spacing=25.0, transect_length=10.0)
    from qgis.core import QgsCoordinateReferenceSystem

    layer = transects_to_layer(transects, QgsCoordinateReferenceSystem("EPSG:32616"))
    assert layer.crs().authid() == "EPSG:32616"
    assert "TRANSECT_ID" in layer.fields().names()
    assert layer.featureCount() == len(transects)


# --- nearest_transect_net_distance -----------------------------------------

def _three_transects():
    """Three vertical transects at x=0, x=10, x=20 (transect_id 0/1/2)."""
    return [
        Transect(transect_id=0, geometry=_line([(0, 0), (0, 100)]), baseline_point=(0, 0)),
        Transect(transect_id=1, geometry=_line([(10, 0), (10, 100)]), baseline_point=(10, 0)),
        Transect(transect_id=2, geometry=_line([(20, 0), (20, 100)]), baseline_point=(20, 0)),
    ]


def _wide_table_for_three_transects():
    return pd.DataFrame({
        "TRANSECT_ID": [0, 1, 2],
        "TO_2000": [10.0, 12.0, np.nan],
        "TO_2010": [16.0, 7.0, 20.0],
    })


def test_nearest_transect_net_distance_picks_closest_transect_and_signs_correctly():
    transects = _three_transects()
    wide = _wide_table_for_three_transects()
    # Closest to transect 0 (x=0) -> TO_2010 - TO_2000 = 16 - 10 = 6 (accretion-signed positive).
    point_near_0 = QgsGeometry.fromPointXY(QgsPointXY(1.0, 50.0))
    assert nearest_transect_net_distance(point_near_0, transects, wide, 2000, 2010) == pytest.approx(6.0)
    # Closest to transect 1 (x=10) -> 7 - 12 = -5 (erosion-signed negative).
    point_near_1 = QgsGeometry.fromPointXY(QgsPointXY(9.0, 50.0))
    assert nearest_transect_net_distance(point_near_1, transects, wide, 2000, 2010) == pytest.approx(-5.0)


def test_nearest_transect_net_distance_nan_when_value_missing():
    transects = _three_transects()
    wide = _wide_table_for_three_transects()
    # Closest to transect 2 (x=20), whose TO_2000 is NaN.
    point_near_2 = QgsGeometry.fromPointXY(QgsPointXY(21.0, 50.0))
    assert math.isnan(nearest_transect_net_distance(point_near_2, transects, wide, 2000, 2010))


def test_nearest_transect_net_distance_nan_when_column_missing():
    transects = _three_transects()
    wide = _wide_table_for_three_transects()
    point = QgsGeometry.fromPointXY(QgsPointXY(1.0, 50.0))
    assert math.isnan(nearest_transect_net_distance(point, transects, wide, 2000, 2099))


def test_nearest_transect_net_distance_nan_when_row_missing():
    transects = _three_transects()
    wide = _wide_table_for_three_transects().iloc[[1, 2]]  # drop transect 0's row entirely
    point = QgsGeometry.fromPointXY(QgsPointXY(1.0, 50.0))
    assert math.isnan(nearest_transect_net_distance(point, transects, wide, 2000, 2010))
