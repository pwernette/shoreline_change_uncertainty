import math

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from shoreline_uncertainty.transects import (
    Transect,
    _corner_key,
    build_baseline,
    compute_baseline_direction,
    generate_transects,
    intersect_transects_shorelines,
    nearest_transect_net_distance,
    order_transect_start,
    to_wide_table,
    transects_to_gdf,
)


def test_compute_baseline_direction_horizontal_line(synthetic_site):
    import geopandas as gpd
    gdf = gpd.read_file(synthetic_site["paths"][2000])
    center, direction = compute_baseline_direction(gdf)
    # The synthetic shoreline is a gently wavy, roughly east-west line ->
    # dominant direction should be ~horizontal (|dx| >> |dy|).
    dx, dy = direction
    assert abs(dx) > abs(dy)


def test_compute_baseline_direction_needs_points():
    import geopandas as gpd
    gdf = gpd.GeoDataFrame({"geometry": [LineString([(0, 0), (1, 0)])]}, crs="EPSG:32616")
    # A single 2-point line still has >= 2 points, so this should succeed.
    compute_baseline_direction(gdf)


def test_build_baseline_length_and_center():
    line = build_baseline((0.0, 0.0), (1.0, 0.0), length=10.0)
    assert line.length == pytest.approx(10.0)
    assert line.coords[0] == pytest.approx((-5.0, 0.0))
    assert line.coords[1] == pytest.approx((5.0, 0.0))


@pytest.mark.parametrize("priority", ["UPPER_LEFT", "UPPER_RIGHT", "LOWER_LEFT", "LOWER_RIGHT"])
def test_order_transect_start_is_idempotent(priority):
    line = LineString([(0, 0), (10, 10)])
    once = order_transect_start(line, priority)
    twice = order_transect_start(once, priority)
    assert list(once.coords) == list(twice.coords)


def test_order_transect_start_upper_left_picks_expected_endpoint():
    # UPPER_LEFT priority key is (x, -y); smaller x and larger y should win.
    line = LineString([(10, 0), (0, 10)])
    oriented = order_transect_start(line, "UPPER_LEFT")
    assert oriented.coords[0] == (0, 10)


def test_generate_transects_count_and_perpendicularity():
    baseline = LineString([(0, 0), (100, 0)])
    transects = generate_transects(baseline, spacing=25.0, transect_length=20.0)
    # 100m baseline / 25m spacing -> 4 steps -> 5 transects (0,25,50,75,100)
    assert len(transects) == 5
    for t in transects:
        assert isinstance(t, Transect)
        assert t.geometry.length == pytest.approx(20.0)
        # Each transect should be perpendicular to the (horizontal) baseline,
        # i.e. roughly vertical: dx ~ 0.
        x0, y0 = t.geometry.coords[0]
        x1, y1 = t.geometry.coords[-1]
        assert abs(x1 - x0) < 1e-6


def test_generate_transects_rejects_zero_length_baseline():
    baseline = LineString([(5, 5), (5, 5)])
    with pytest.raises(ValueError):
        generate_transects(baseline, spacing=10.0, transect_length=10.0)


def test_intersect_transects_shorelines_and_wide_pivot():
    baseline = LineString([(0, 0), (100, 0)])
    transects = generate_transects(baseline, spacing=50.0, transect_length=20.0)
    shorelines_by_year = {
        2000: LineString([(-10, 1), (110, 1)]),
        2010: LineString([(-10, -2), (110, -2)]),
    }
    long_table = intersect_transects_shorelines(transects, shorelines_by_year)
    assert set(long_table["YEAR"]) == {2000, 2010}
    assert {"TRANSECT_ID", "YEAR", "DISTANCE", "X", "Y"} <= set(long_table.columns)

    wide = to_wide_table(long_table)
    assert "TO_2000" in wide.columns
    assert "TO_2010" in wide.columns
    assert len(wide) == len(transects)


def test_to_wide_table_empty_passthrough():
    import pandas as pd
    empty = pd.DataFrame(columns=["TRANSECT_ID", "YEAR", "DISTANCE", "X", "Y"])
    assert to_wide_table(empty).empty


def test_transects_to_gdf_crs_and_columns():
    baseline = LineString([(0, 0), (50, 0)])
    transects = generate_transects(baseline, spacing=25.0, transect_length=10.0)
    gdf = transects_to_gdf(transects, "EPSG:32616")
    assert str(gdf.crs) in ("EPSG:32616", "epsg:32616") or gdf.crs.to_epsg() == 32616
    assert "TRANSECT_ID" in gdf.columns
    assert len(gdf) == len(transects)


# --- nearest_transect_net_distance -----------------------------------------

def _three_transects():
    """Three vertical transects at x=0, x=10, x=20 (transect_id 0/1/2)."""
    return [
        Transect(transect_id=0, geometry=LineString([(0, 0), (0, 100)]), baseline_point=(0, 0)),
        Transect(transect_id=1, geometry=LineString([(10, 0), (10, 100)]), baseline_point=(10, 0)),
        Transect(transect_id=2, geometry=LineString([(20, 0), (20, 100)]), baseline_point=(20, 0)),
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
    point_near_0 = Point(1.0, 50.0)
    assert nearest_transect_net_distance(point_near_0, transects, wide, 2000, 2010) == pytest.approx(6.0)
    # Closest to transect 1 (x=10) -> 7 - 12 = -5 (erosion-signed negative).
    point_near_1 = Point(9.0, 50.0)
    assert nearest_transect_net_distance(point_near_1, transects, wide, 2000, 2010) == pytest.approx(-5.0)


def test_nearest_transect_net_distance_nan_when_value_missing():
    transects = _three_transects()
    wide = _wide_table_for_three_transects()
    # Closest to transect 2 (x=20), whose TO_2000 is NaN.
    point_near_2 = Point(21.0, 50.0)
    assert math.isnan(nearest_transect_net_distance(point_near_2, transects, wide, 2000, 2010))


def test_nearest_transect_net_distance_nan_when_column_missing():
    transects = _three_transects()
    wide = _wide_table_for_three_transects()
    assert math.isnan(nearest_transect_net_distance(Point(1.0, 50.0), transects, wide, 2000, 2099))


def test_nearest_transect_net_distance_nan_when_row_missing():
    transects = _three_transects()
    wide = _wide_table_for_three_transects().iloc[[1, 2]]  # drop transect 0's row entirely
    assert math.isnan(nearest_transect_net_distance(Point(1.0, 50.0), transects, wide, 2000, 2010))
