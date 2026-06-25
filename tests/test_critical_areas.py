from shapely.geometry import LineString

from shoreline_uncertainty.critical_areas import identify_critical_areas


def test_identify_critical_areas_only_year_lt_k():
    geoms = {
        2000: LineString([(0, 0), (100, 0)]),
        2010: LineString([(0, 1), (100, 1)]),
        2020: LineString([(0, 2), (100, 2)]),
    }
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616", step=0.25,
    )
    # Only year < k pairs: (2000,2010), (2000,2020), (2010,2020) -- 3 rows.
    pairs = set(zip(summary["FROM_YEAR"], summary["TO_YEAR"]))
    assert pairs == {(2000, 2010), (2000, 2020), (2010, 2020)}
    assert (2010, 2000) not in pairs  # asymmetry vs. perkal is preserved


def test_identify_critical_areas_returns_segments_gdf():
    geoms = {
        2000: LineString([(0, 0), (100, 0)]),
        2010: LineString([(0, 1), (100, 1)]),
    }
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616", step=0.25,
    )
    assert len(segments) >= 1
    assert segments.crs is not None
    assert {"SITE", "FROM_YEAR", "TO_YEAR", "PCT", "geometry"} <= set(segments.columns)


def test_identify_critical_areas_export_table_false_still_returns_segments():
    geoms = {
        2000: LineString([(0, 0), (100, 0)]),
        2010: LineString([(0, 1), (100, 1)]),
    }
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616", step=0.25, export_table=False,
    )
    assert summary.empty
    assert len(segments) >= 1


def test_identify_critical_areas_empty_when_no_pairs():
    geoms = {2000: LineString([(0, 0), (100, 0)])}
    summary, segments = identify_critical_areas(
        "test", geoms, confidence_levels=[0.5], crs="EPSG:32616",
    )
    assert summary.empty
    assert len(segments) == 0
