import pytest
from shapely.geometry import LineString

from shoreline_uncertainty.epsilon_bands import (
    grow_buffer_to_threshold,
    overlapping_double_buffer,
    run_odb_for_site,
    run_perkal_for_site,
)


def test_odb_far_apart_lines_are_significant():
    # Two parallel lines 5m apart, small 0.5m buffers each -> buffers don't
    # touch -> Ps == 0 -> significant change.
    line_a = LineString([(0, 0), (100, 0)])
    line_b = LineString([(0, 5), (100, 5)])
    result = overlapping_double_buffer(line_a, 0.5, line_b, 0.5, threshold=0.05)
    assert result.prop_ab_overlap == pytest.approx(0.0, abs=1e-9)
    assert result.significant_change is True


def test_odb_identical_lines_large_buffer_not_significant():
    # Identical line buffered by itself -> total overlap -> Ps == 1.0
    line = LineString([(0, 0), (100, 0)])
    result = overlapping_double_buffer(line, 5.0, line, 5.0, threshold=0.05)
    assert result.prop_ab_overlap == pytest.approx(1.0, abs=1e-6)
    assert result.significant_change is False


def test_odb_threshold_is_sensitive():
    line_a = LineString([(0, 0), (100, 0)])
    line_b = LineString([(0, 3), (100, 3)])
    # Buffers of 2m each partially overlap (Ps somewhere in (0, 1)) -- whether
    # that counts as "significant" depends entirely on the chosen threshold T.
    strict = overlapping_double_buffer(line_a, 2.0, line_b, 2.0, threshold=0.01)
    lenient = overlapping_double_buffer(line_a, 2.0, line_b, 2.0, threshold=0.99)
    assert strict.prop_ab_overlap == lenient.prop_ab_overlap  # same geometry -> same Ps
    assert 0.0 < strict.prop_ab_overlap < 1.0
    assert strict.significant_change is False  # Ps > 0.01 -> not significant at a strict threshold
    assert lenient.significant_change is True  # Ps < 0.99 -> significant at a lenient threshold


def test_run_odb_for_site_produces_all_pairs():
    geoms = {
        2000: LineString([(0, 0), (100, 0)]),
        2010: LineString([(0, 5), (100, 5)]),
        2020: LineString([(0, 15), (100, 15)]),
    }
    radii = {2000: 1.0, 2010: 1.0, 2020: 1.0}
    df = run_odb_for_site("test", geoms, radii, threshold=0.05)
    # 3 years -> 3 choose 2 == 3 pairs
    assert len(df) == 3
    assert set(zip(df["YEAR_A"], df["YEAR_B"])) == {(2000, 2010), (2000, 2020), (2010, 2020)}
    assert "SIGNIFICANT_CHANGE" in df.columns


def test_grow_buffer_to_threshold_converges():
    shoreline = LineString([(0, 0), (100, 0)])
    adjacent = LineString([(0, 1), (100, 1)])
    bufdist, threshold, obs_length, iterations = grow_buffer_to_threshold(
        shoreline, adjacent, confidence_level=0.5, step=0.25,
    )
    assert bufdist >= 1.0  # must grow at least past the 1m gap to intersect 'adjacent'
    assert obs_length >= threshold
    assert iterations > 0


def test_run_perkal_for_site_all_ordered_pairs():
    geoms = {
        2000: LineString([(0, 0), (100, 0)]),
        2010: LineString([(0, 2), (100, 2)]),
    }
    df = run_perkal_for_site("test", geoms, confidence_levels=[0.5], step=0.5)
    # 2 years, ordered pairs (year != k): (2000,2010) and (2010,2000) == 2 rows
    assert len(df) == 2
    assert set(zip(df["FROM_YEAR"], df["TO_YEAR"])) == {(2000, 2010), (2010, 2000)}
