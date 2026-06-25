"""Unit tests for rate_of_change.py -- EPR (End Point Rate) and LRR (Linear
Regression Rate) shoreline change-rate statistics, computed directly on
small hand-constructed transects.to_wide_table-shaped DataFrames (mirroring
test_probability_surface.py's test_change_probability_table_adds_expected_columns
convention) rather than going through the full pipeline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from shoreline_uncertainty.rate_of_change import (
    build_rate_change_polygons,
    compute_rate_of_change,
    end_point_rate,
    linear_regression_rate,
)
from shoreline_uncertainty.transects import Transect


def _wide_table(rows, years):
    cols = {"TRANSECT_ID": list(range(len(rows)))}
    for i, year in enumerate(years):
        cols[f"TO_{year}"] = [row[i] for row in rows]
    return pd.DataFrame(cols)


# --- end_point_rate ---------------------------------------------------------

def test_end_point_rate_two_years_simple():
    # 0 -> 10 over 20 years => 0.5 m/yr, regardless of any value in between
    # (end_point_rate only ever looks at oldest/youngest).
    wide = _wide_table([[0.0, 10.0]], [2000, 2020])
    out = end_point_rate(wide)
    assert out["EPR_NET_DISTANCE"].tolist() == pytest.approx([10.0])
    assert out["EPR_RATE"].tolist() == pytest.approx([0.5])


def test_end_point_rate_uses_only_oldest_and_youngest_with_three_years():
    # Middle year's value (100, way off-trend) must not affect EPR at all.
    wide = _wide_table([[0.0, 100.0, 15.0]], [2000, 2010, 2020])
    out = end_point_rate(wide)
    assert out["EPR_NET_DISTANCE"].tolist() == pytest.approx([15.0])
    assert out["EPR_RATE"].tolist() == pytest.approx([0.75])


def test_end_point_rate_multiple_transects():
    wide = _wide_table([[0.0, 10.0], [5.0, 5.0], [-2.0, 8.0]], [2000, 2010])
    out = end_point_rate(wide)
    assert out["EPR_NET_DISTANCE"].tolist() == pytest.approx([10.0, 0.0, 10.0])
    assert out["EPR_RATE"].tolist() == pytest.approx([1.0, 0.0, 1.0])


def test_end_point_rate_requires_at_least_two_years():
    wide = _wide_table([[0.0]], [2000])
    with pytest.raises(ValueError):
        end_point_rate(wide)


# --- linear_regression_rate -------------------------------------------------

def test_linear_regression_rate_two_years_matches_end_point_rate():
    wide = _wide_table([[0.0, 10.0]], [2000, 2020])
    lrr = linear_regression_rate(wide)
    epr = end_point_rate(wide)
    assert lrr["LRR_RATE"].tolist() == pytest.approx(epr["EPR_RATE"].tolist())
    assert lrr["LRR_NET_DISTANCE"].tolist() == pytest.approx(epr["EPR_NET_DISTANCE"].tolist())
    # A line through exactly 2 points is an exact fit.
    assert lrr["LRR_R2"].tolist() == pytest.approx([1.0])


def test_linear_regression_rate_perfect_linear_trend_gives_r2_one():
    # Perfectly linear: 0, 5, 10 at 2000/2010/2020 -> slope 0.5, R^2 = 1.0.
    wide = _wide_table([[0.0, 5.0, 10.0]], [2000, 2010, 2020])
    out = linear_regression_rate(wide)
    assert out["LRR_RATE"].iloc[0] == pytest.approx(0.5)
    assert out["LRR_NET_DISTANCE"].iloc[0] == pytest.approx(10.0)
    assert out["LRR_R2"].iloc[0] == pytest.approx(1.0, abs=1e-9)


def test_linear_regression_rate_equally_spaced_years_middle_point_off_trend():
    # Years 2000/2010/2020 (equally spaced, 10 years apart each) with
    # relative values [0, 5, 15] -- mirrors the synthetic test fixture used
    # in test_pipeline.py (offsets 0/-5/-15, retreat accelerating from
    # 0.5 m/yr to 1.0 m/yr). For 3 EQUALLY-SPACED x-values, OLS slope is
    # mathematically guaranteed to equal the 2-point endpoint slope
    # regardless of the middle y-value (the middle x's deviation from the
    # mean x is exactly zero, contributing nothing to the slope's
    # covariance sum) -- so LRR_RATE must equal EPR_RATE = 15/20 = 0.75
    # exactly, while LRR_R2 is strictly < 1.0 (since the regression line
    # does NOT pass through the off-trend middle point).
    wide = _wide_table([[0.0, 5.0, 15.0]], [2000, 2010, 2020])
    lrr = linear_regression_rate(wide)
    epr = end_point_rate(wide)
    assert lrr["LRR_RATE"].iloc[0] == pytest.approx(epr["EPR_RATE"].iloc[0], abs=1e-9)
    assert lrr["LRR_RATE"].iloc[0] == pytest.approx(0.75, abs=1e-9)
    assert lrr["LRR_NET_DISTANCE"].iloc[0] == pytest.approx(15.0, abs=1e-9)
    # Hand-derived: mean_y = 20/3; predicted [-0.8333, 6.6667, 14.1667];
    # residuals [0.8333, -1.6667, 0.8333]; SS_res = 4.1667; SS_tot = 116.667;
    # R^2 = 1 - 4.1667/116.667 ~= 0.9643.
    assert lrr["LRR_R2"].iloc[0] == pytest.approx(0.9643, abs=1e-3)
    assert lrr["LRR_R2"].iloc[0] < 1.0


def test_linear_regression_rate_handles_missing_years_per_transect():
    wide = pd.DataFrame({
        "TRANSECT_ID": [0, 1],
        "TO_2000": [0.0, 0.0],
        "TO_2010": [5.0, np.nan],
        "TO_2020": [15.0, 10.0],
    })
    out = linear_regression_rate(wide)
    # Row 0: all 3 years present -> same as the equally-spaced case above.
    assert out["LRR_RATE"].iloc[0] == pytest.approx(0.75, abs=1e-9)
    # Row 1: only 2000/2020 present -> exact 2-point fit, R^2 == 1.0.
    assert out["LRR_RATE"].iloc[1] == pytest.approx(0.5, abs=1e-9)
    assert out["LRR_R2"].iloc[1] == pytest.approx(1.0, abs=1e-9)


def test_linear_regression_rate_nan_when_fewer_than_two_valid_years():
    wide = pd.DataFrame({
        "TRANSECT_ID": [0],
        "TO_2000": [np.nan],
        "TO_2010": [5.0],
        "TO_2020": [np.nan],
    })
    out = linear_regression_rate(wide)
    assert np.isnan(out["LRR_RATE"].iloc[0])
    assert np.isnan(out["LRR_NET_DISTANCE"].iloc[0])
    assert np.isnan(out["LRR_R2"].iloc[0])


def test_linear_regression_rate_requires_at_least_two_years():
    wide = _wide_table([[0.0]], [2000])
    with pytest.raises(ValueError):
        linear_regression_rate(wide)


# --- compute_rate_of_change (combined) --------------------------------------

def test_compute_rate_of_change_combines_epr_and_lrr_columns():
    wide = _wide_table([[0.0, 5.0, 15.0]], [2000, 2010, 2020])
    out = compute_rate_of_change(wide)
    for col in ["EPR_NET_DISTANCE", "EPR_RATE", "LRR_NET_DISTANCE", "LRR_RATE", "LRR_R2"]:
        assert col in out.columns
    assert out["EPR_RATE"].iloc[0] == pytest.approx(0.75, abs=1e-9)
    assert out["LRR_RATE"].iloc[0] == pytest.approx(0.75, abs=1e-9)
    assert out["LRR_R2"].iloc[0] == pytest.approx(0.9643, abs=1e-3)
    # Original wide_table columns must still be present (combined adds, not replaces).
    assert "TRANSECT_ID" in out.columns
    assert "TO_2000" in out.columns


# --- build_rate_change_polygons ---------------------------------------------

def _two_adjacent_transects(x_a=0.0, x_b=10.0, transect_id_a=0, transect_id_b=1):
    """Two parallel vertical transects, far enough apart in x to act as
    sequentially-adjacent rate transects (transect_id differs by exactly 1)."""
    return [
        Transect(transect_id=transect_id_a, geometry=LineString([(x_a, 0), (x_a, 100)]), baseline_point=(x_a, 0)),
        Transect(transect_id=transect_id_b, geometry=LineString([(x_b, 0), (x_b, 100)]), baseline_point=(x_b, 0)),
    ]


def test_build_rate_change_polygons_basic_geometry_and_attributes():
    transects = _two_adjacent_transects()
    wide = pd.DataFrame({
        "TRANSECT_ID": [0, 1],
        "TO_2000": [20.0, 20.0],
        "TO_2010": [25.0, 30.0],
    })
    sigma_by_year = {2000: 1.0, 2010: 1.0}
    out = build_rate_change_polygons(transects, wide, sigma_by_year, crs="EPSG:32616")

    assert len(out) == 1
    row = out.iloc[0]
    assert row["TRANSECT_A"] == 0
    assert row["TRANSECT_B"] == 1
    assert row["YEAR_A"] == 2000
    assert row["YEAR_B"] == 2010
    # MAGNITUDE = mean((25-20), (30-20)) = mean(5, 10) = 7.5; same sign
    # convention as EPR_NET_DISTANCE (positive here = accretion).
    assert row["MAGNITUDE"] == pytest.approx(7.5)
    assert row["RATE"] == pytest.approx(0.75)  # 7.5 / (2010 - 2000)
    # 7.5m of separation with sigma=1 on each side is overwhelmingly "real".
    assert row["PROB_CHANGE"] > 0.99
    # Quadrilateral bounded by (0,20)-(0,25)-(10,30)-(10,20): a trapezoid
    # with parallel sides of length 5 and 10, 10m apart.
    assert out.geometry.iloc[0].area == pytest.approx(75.0)
    assert out.crs is not None


def test_build_rate_change_polygons_skips_nonsequential_transect_ids():
    # transect_id 1 is entirely missing from the wide table -> the (0, 2)
    # pairing must be skipped (id gap of 2, not 1); only (2, 3) survives.
    transects = [
        Transect(transect_id=0, geometry=LineString([(0, 0), (0, 100)]), baseline_point=(0, 0)),
        Transect(transect_id=2, geometry=LineString([(20, 0), (20, 100)]), baseline_point=(20, 0)),
        Transect(transect_id=3, geometry=LineString([(30, 0), (30, 100)]), baseline_point=(30, 0)),
    ]
    wide = pd.DataFrame({
        "TRANSECT_ID": [0, 2, 3],
        "TO_2000": [10.0, 10.0, 10.0],
        "TO_2010": [12.0, 14.0, 16.0],
    })
    out = build_rate_change_polygons(transects, wide, {2000: 1.0, 2010: 1.0}, crs="EPSG:32616")
    assert len(out) == 1
    assert out.iloc[0][["TRANSECT_A", "TRANSECT_B"]].tolist() == [2, 3]


def test_build_rate_change_polygons_skips_missing_to_values():
    transects = _two_adjacent_transects()
    wide = pd.DataFrame({
        "TRANSECT_ID": [0, 1],
        "TO_2000": [20.0, np.nan],  # transect 1's TO_2000 missing
        "TO_2010": [25.0, 30.0],
    })
    out = build_rate_change_polygons(transects, wide, {2000: 1.0, 2010: 1.0}, crs="EPSG:32616")
    assert len(out) == 0
    assert list(out.columns) == [
        "TRANSECT_A", "TRANSECT_B", "YEAR_A", "YEAR_B", "MAGNITUDE", "RATE", "PROB_CHANGE", "geometry",
    ]


def test_build_rate_change_polygons_empty_with_fewer_than_two_years_or_transects():
    transects = _two_adjacent_transects()
    one_year_wide = pd.DataFrame({"TRANSECT_ID": [0, 1], "TO_2000": [20.0, 20.0]})
    out = build_rate_change_polygons(transects, one_year_wide, {2000: 1.0}, crs="EPSG:32616")
    assert len(out) == 0

    two_year_wide = pd.DataFrame({"TRANSECT_ID": [0], "TO_2000": [20.0], "TO_2010": [25.0]})
    out = build_rate_change_polygons(transects[:1], two_year_wide, {2000: 1.0, 2010: 1.0}, crs="EPSG:32616")
    assert len(out) == 0


def test_build_rate_change_polygons_multiple_year_pairs():
    transects = _two_adjacent_transects()
    wide = pd.DataFrame({
        "TRANSECT_ID": [0, 1],
        "TO_2000": [20.0, 20.0],
        "TO_2010": [25.0, 30.0],
        "TO_2020": [30.0, 50.0],
    })
    out = build_rate_change_polygons(transects, wide, {2000: 1.0, 2010: 1.0, 2020: 1.0}, crs="EPSG:32616")
    # 3 years -> 3 combinations: (2000,2010), (2000,2020), (2010,2020).
    assert len(out) == 3
    pairs = set(zip(out["YEAR_A"], out["YEAR_B"]))
    assert pairs == {(2000, 2010), (2000, 2020), (2010, 2020)}
