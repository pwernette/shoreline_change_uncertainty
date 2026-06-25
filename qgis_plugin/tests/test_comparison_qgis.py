"""Tests for the QGIS-native port of comparison.py, run against the
shapely-backed qgis stub. Mirrors tests/test_comparison.py exactly."""
import pandas as pd
import pytest
from qgis.core import QgsGeometry, QgsPointXY

from shoreline_uncertainty_qgis.comparison_qgis import (
    compare_professionals_pairwise,
    compare_to_professionals,
    professional_summary,
)


def _line(coords):
    return QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in coords])


def test_compare_to_professionals_basic():
    primary = _line([(0, 0), (100, 0)])
    profs = {
        "acmoody": _line([(0, 1), (100, 1)]),
        "goodwin": _line([(0, -2), (100, -2)]),
    }
    df = compare_to_professionals("test", 2000, primary, profs)
    assert len(df) == 2
    assert set(df["TO_PROF"]) == {"acmoody", "goodwin"}
    assert (df["FROM"] == "PRIMARY").all()
    acmoody_row = df[df["TO_PROF"] == "acmoody"].iloc[0]
    goodwin_row = df[df["TO_PROF"] == "goodwin"].iloc[0]
    assert acmoody_row["MIN_DIST"] == pytest.approx(1.0)
    assert goodwin_row["MIN_DIST"] == pytest.approx(2.0)


def test_compare_professionals_pairwise_excludes_self_pairs():
    profs = {
        "acmoody": _line([(0, 0), (100, 0)]),
        "goodwin": _line([(0, 1), (100, 1)]),
        "lusch": _line([(0, -1), (100, -1)]),
    }
    df = compare_professionals_pairwise("test", 2000, profs)
    assert len(df) == 6
    assert not any(df["FROM_PROF"] == df["TO_PROF"])


def test_professional_summary_means_by_group():
    pairwise = pd.DataFrame([
        {"SITE": "test", "YEAR": 2000, "FROM_PROF": "a", "TO_PROF": "b", "MIN_DIST": 1, "MEAN_DIST": 2.0, "MAX_DIST": 3},
        {"SITE": "test", "YEAR": 2000, "FROM_PROF": "a", "TO_PROF": "b", "MIN_DIST": 1, "MEAN_DIST": 4.0, "MAX_DIST": 5},
    ])
    summary = professional_summary(pairwise)
    assert len(summary) == 1
    assert summary.iloc[0]["MEAN_DIST"] == pytest.approx(3.0)


def test_professional_summary_handles_empty():
    summary = professional_summary(pd.DataFrame())
    assert summary.empty
    assert list(summary.columns) == ["FROM_PROF", "TO_PROF", "YEAR", "MEAN_DIST"]
