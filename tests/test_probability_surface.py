"""Tests for probability_surface.py -- the horizontal-direction analogue of
Wernette et al. (2020)'s vertical change-probability (CP) approach.

`gaussian_overlap_probability` is checked against:
  - the exact closed-form equal-variance overlap, 2*Phi(-|d|/(2*sigma)),
    across a sweep of separations;
  - brute-force numerical integration of min(pdf_a, pdf_b) for several
    unequal-variance cases (the general two-crossing-point case);
  - known boundary cases (identical distributions, very far apart);
  - this application's deliberate equal-mean override (Eq. 1's observed
    delta is exactly zero => P_real must be exactly 0, regardless of how
    the two sigmas compare).
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import integrate
from scipy.stats import norm
from shapely.geometry import LineString

from shoreline_uncertainty.probability_surface import (
    change_probability_raster,
    change_probability_table,
    gaussian_overlap_probability,
    position_probability_surfaces,
    rmse95_to_sigma,
    segment_line,
    segment_mean_probability,
    shoreline_change_probability_segments,
    signed_distance_raster,
)
from shoreline_uncertainty.raster_output import build_grid_transform
from shoreline_uncertainty.transects import baseline_center_direction


def numeric_p_real(mu_a, sigma_a, mu_b, sigma_b):
    """Brute-force ground truth for P_real: 1 - integral of
    min(pdf_a, pdf_b) (the true overlap area between the two curves)."""
    f = lambda x: min(norm.pdf(x, mu_a, sigma_a), norm.pdf(x, mu_b, sigma_b))
    span = 20.0 * max(sigma_a, sigma_b)
    lo = min(mu_a, mu_b) - span
    hi = max(mu_a, mu_b) + span
    overlap, _ = integrate.quad(f, lo, hi, limit=400)
    return 1.0 - overlap


# --- rmse95_to_sigma ---------------------------------------------------

def test_rmse95_to_sigma_basic():
    assert rmse95_to_sigma(2.4477) == pytest.approx(1.0, abs=1e-6)


def test_rmse95_to_sigma_allegan_values():
    # The real Allegan, MI 1938/2010 UNCERTAINT values used elsewhere in
    # this repo's example config.
    assert rmse95_to_sigma(13.2795) == pytest.approx(5.425297, abs=1e-5)
    assert rmse95_to_sigma(10.3848) == pytest.approx(4.242677, abs=1e-5)


# --- gaussian_overlap_probability: boundary cases -----------------------

def test_identical_distributions_give_zero_p_real():
    assert gaussian_overlap_probability(0.0, 2.0, 0.0, 2.0) == pytest.approx(0.0, abs=1e-9)


def test_far_apart_distributions_give_p_real_near_one():
    assert gaussian_overlap_probability(0.0, 1.0, 50.0, 1.0) == pytest.approx(1.0, abs=1e-9)


def test_equal_mean_unequal_sigma_is_overridden_to_zero():
    """Domain-specific rule: an exactly-zero observed difference (Eq. 1's
    delta) can never be "real" regardless of how the two sigmas compare,
    even though the generic overlap coefficient between N(0,5^2) and
    N(0,1^2) gives a nontrivial P_real (the two are statistically
    distinguishable as populations, just not as a single observed
    difference)."""
    assert gaussian_overlap_probability(0.0, 5.0, 0.0, 1.0) == pytest.approx(0.0, abs=1e-9)
    # Sanity: confirm the *generic* overlap-coefficient P_real really is
    # well above zero here, so this test is exercising the override and
    # not a degenerate input where the override happens not to matter.
    assert numeric_p_real(0.0, 5.0, 0.0, 1.0) == pytest.approx(0.647, abs=1e-2)


# --- gaussian_overlap_probability: equal-variance closed form ----------

@pytest.mark.parametrize("d", [0.0, 1.0, 2.0, 4.0, 8.0, 16.0])
def test_equal_sigma_matches_closed_form(d):
    sigma = 2.0
    expected_overlap = 2.0 * norm.cdf(-d / (2.0 * sigma))
    expected_p_real = 1.0 - expected_overlap
    got = gaussian_overlap_probability(0.0, sigma, d, sigma)
    assert got == pytest.approx(expected_p_real, abs=1e-9)


# --- gaussian_overlap_probability: unequal-variance general case -------

@pytest.mark.parametrize(
    "mu_a, sigma_a, mu_b, sigma_b",
    [
        (0.0, 1.0, 5.0, 3.0),
        (0.0, 2.0, 3.0, 0.5),
        (0.0, 1.0, 1.0, 1.0),  # equal sigma, exercised here too as a cross-check
        (-4.0, 3.0, 2.0, 1.0),
    ],
)
def test_unequal_sigma_matches_numerical_integration(mu_a, sigma_a, mu_b, sigma_b):
    got = float(gaussian_overlap_probability(mu_a, sigma_a, mu_b, sigma_b))
    expected_p_real = numeric_p_real(mu_a, sigma_a, mu_b, sigma_b)
    assert got == pytest.approx(expected_p_real, abs=1e-3)


def test_p_real_is_symmetric_in_a_and_b():
    p1 = float(gaussian_overlap_probability(0.0, 1.0, 5.0, 3.0))
    p2 = float(gaussian_overlap_probability(5.0, 3.0, 0.0, 1.0))
    assert p1 == pytest.approx(p2, abs=1e-12)


def test_p_real_always_in_unit_interval():
    rng = np.random.default_rng(0)
    mu_a = rng.uniform(-50, 50, size=200)
    mu_b = rng.uniform(-50, 50, size=200)
    sigma_a = rng.uniform(0.1, 20, size=200)
    sigma_b = rng.uniform(0.1, 20, size=200)
    p = gaussian_overlap_probability(mu_a, sigma_a, mu_b, sigma_b)
    assert np.all(p >= 0.0) and np.all(p <= 1.0)


def test_vectorized_input_matches_scalar_calls():
    mu_a = np.array([0.0, 0.0, 0.0])
    sigma_a = np.array([1.0, 2.0, 5.0])
    mu_b = np.array([5.0, 3.0, 0.0])
    sigma_b = np.array([3.0, 0.5, 1.0])
    vec_result = gaussian_overlap_probability(mu_a, sigma_a, mu_b, sigma_b)
    for i in range(3):
        scalar_result = gaussian_overlap_probability(
            float(mu_a[i]), float(sigma_a[i]), float(mu_b[i]), float(sigma_b[i])
        )
        assert vec_result[i] == pytest.approx(float(scalar_result), abs=1e-12)


# --- position_probability_surfaces / signed_distance_raster -------------

def test_position_probability_surfaces_peak_on_the_line():
    line = LineString([(0, 5), (10, 5)])
    transform, width, height = build_grid_transform((0, 0, 10, 10), cell_size=1)
    pdf, confidence = position_probability_surfaces(line, sigma=1.0, transform=transform, width=width, height=height)
    assert pdf.shape == (height, width)
    assert confidence.shape == (height, width)
    # Confidence is a normalized Gaussian peaking at 1.0 exactly on the line.
    assert confidence.max() == pytest.approx(1.0, abs=1e-6)
    assert confidence.min() >= 0.0
    assert confidence.max() <= 1.0 + 1e-9
    # The pdf's peak is confidence's peak scaled by 1/(sigma*sqrt(2*pi)).
    assert pdf.max() == pytest.approx(1.0 / np.sqrt(2.0 * np.pi), abs=1e-3)


def test_signed_distance_raster_has_both_signs_across_baseline():
    line = LineString([(0, 6), (10, 6)])
    baseline = LineString([(0, 5), (10, 5)])
    center, direction = baseline_center_direction(baseline)
    transform, width, height = build_grid_transform((0, 0, 10, 10), cell_size=1)
    signed = signed_distance_raster(line, center, direction, transform, width, height)
    assert signed.shape == (height, width)
    assert np.any(signed > 0)
    assert np.any(signed < 0)


# --- change_probability_raster / change_probability_table ---------------

def test_change_probability_raster_high_p_real_far_from_baseline_pair():
    line_a = LineString([(0, 0), (10, 0)])
    line_b = LineString([(0, 5), (10, 5)])  # 5m offset, well beyond tiny sigma
    baseline = LineString([(0, -5), (10, -5)])
    center, direction = baseline_center_direction(baseline)
    transform, width, height = build_grid_transform((-2, -2, 12, 12), cell_size=0.5)
    delta, p_real = change_probability_raster(
        line_a, 0.2, line_b, 0.2, center, direction, transform, width, height
    )
    assert delta.shape == p_real.shape == (height, width)
    # Right above either line, the offset between the two curves should
    # register as a real change given the small sigma relative to the gap.
    rows, cols = np.indices((height, width))
    xs = transform.c + (cols + 0.5) * transform.a
    ys = transform.f + (rows + 0.5) * transform.e
    near_a = (np.abs(xs - 5) < 1) & (np.abs(ys - 0) < 0.5)
    assert np.any(p_real[near_a] > 0.9)


def test_change_probability_table_adds_expected_columns():
    import pandas as pd

    wide = pd.DataFrame({"TRANSECT_ID": [0, 1, 2], "TO_2000": [0.0, 10.0, 20.0], "TO_2010": [0.0, 15.0, 21.0]})
    sigma_by_year = {2000: 2.0, 2010: 2.0}
    out = change_probability_table(wide, sigma_by_year)
    assert "DELTA_2000_2010" in out.columns
    assert "P_REAL_2000_2010" in out.columns
    assert out["DELTA_2000_2010"].tolist() == pytest.approx([0.0, 5.0, 1.0])
    # Row 0: identical TO values -> delta 0 -> P_real must be exactly 0.
    assert out["P_REAL_2000_2010"].iloc[0] == pytest.approx(0.0, abs=1e-9)
    # Row 1: 5m offset with sigma=2 each side -> clearly distinguishable.
    assert out["P_REAL_2000_2010"].iloc[1] > 0.75


# --- segment_line ---------------------------------------------------------

def test_segment_line_exact_multiple_gives_equal_length_segments():
    line = LineString([(0, 0), (100, 0)])
    segments = segment_line(line, 25.0)
    assert len(segments) == 4
    assert [s.length for s in segments] == pytest.approx([25.0, 25.0, 25.0, 25.0])


def test_segment_line_remainder_gives_shorter_final_segment():
    line = LineString([(0, 0), (90, 0)])
    segments = segment_line(line, 25.0)
    assert len(segments) == 4
    assert [s.length for s in segments] == pytest.approx([25.0, 25.0, 25.0, 15.0])


def test_segment_line_shorter_than_segment_length_gives_one_segment():
    line = LineString([(0, 0), (10, 0)])
    segments = segment_line(line, 25.0)
    assert len(segments) == 1
    assert segments[0].length == pytest.approx(10.0)


def test_segment_line_segments_cover_whole_line_contiguously():
    line = LineString([(0, 0), (10, 10), (40, 10)])
    segments = segment_line(line, 7.0)
    assert sum(s.length for s in segments) == pytest.approx(line.length)
    # Each segment's end should coincide with the next segment's start.
    for a, b in zip(segments[:-1], segments[1:]):
        end_a = a.coords[-1]
        start_b = b.coords[0]
        assert end_a == pytest.approx(start_b)


def test_segment_line_rejects_non_positive_segment_length():
    line = LineString([(0, 0), (10, 0)])
    with pytest.raises(ValueError):
        segment_line(line, 0.0)
    with pytest.raises(ValueError):
        segment_line(line, -5.0)


def test_segment_line_handles_multilinestring_without_spanning_gap():
    from shapely.geometry import MultiLineString

    multi = MultiLineString([[(0, 0), (10, 0)], [(100, 0), (110, 0)]])
    segments = segment_line(multi, 4.0)
    # 10m / 4m -> 3 segments per part (4,4,2), two disjoint parts -> 6 total,
    # and no segment should straddle the 90m gap between the two parts.
    assert len(segments) == 6
    assert sum(s.length for s in segments) == pytest.approx(20.0)
    for seg in segments:
        xs = [c[0] for c in seg.coords]
        assert max(xs) <= 110.0 and (max(xs) <= 10.0 or min(xs) >= 100.0)


# --- segment_mean_probability / shoreline_change_probability_segments ----

def test_shoreline_change_probability_segments_averages_raster_correctly():
    # A flat raster grid with two distinct cell values straddled by one
    # segment, to confirm per-segment averaging (not just nearest-cell
    # sampling).
    line = LineString([(0, 5), (20, 5)])
    transform, width, height = build_grid_transform((0, 0, 20, 10), cell_size=10)
    p_real = np.array([[0.7, 0.2]])  # one row, two 10-wide columns
    assert p_real.shape == (height, width)

    gdf = shoreline_change_probability_segments(line, 10.0, p_real, transform, width, height, crs="EPSG:32616")
    assert list(gdf.columns) == ["SEG_ID", "LENGTH", "PROB_CHANGE", "geometry"]
    assert len(gdf) == 2
    assert gdf["LENGTH"].tolist() == pytest.approx([10.0, 10.0])
    # First segment sits entirely over the 0.7 cell, second over the 0.2 cell.
    assert gdf["PROB_CHANGE"].iloc[0] == pytest.approx(0.7, abs=1e-6)
    assert gdf["PROB_CHANGE"].iloc[1] == pytest.approx(0.2, abs=1e-6)
    assert gdf.crs is not None


def test_shoreline_change_probability_segments_empty_line_returns_empty_gdf():
    line = LineString()
    transform, width, height = build_grid_transform((0, 0, 20, 10), cell_size=10)
    p_real = np.zeros((height, width))
    gdf = shoreline_change_probability_segments(line, 10.0, p_real, transform, width, height, crs="EPSG:32616")
    assert len(gdf) == 0
    assert list(gdf.columns) == ["SEG_ID", "LENGTH", "PROB_CHANGE", "geometry"]


def test_segment_mean_probability_matches_manual_average():
    line = LineString([(0, 5), (20, 5)])
    transform, width, height = build_grid_transform((0, 0, 20, 10), cell_size=10)
    p_real = np.array([[0.7, 0.2]])
    segments = segment_line(line, 10.0)
    means = segment_mean_probability(segments, p_real, transform, width, height)
    assert means == pytest.approx([0.7, 0.2], abs=1e-6)
