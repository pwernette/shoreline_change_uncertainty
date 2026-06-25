"""End-to-end test: build a RunConfig pointing at the synthetic shapefiles
from conftest.py, run the full pipeline, and confirm every expected output
(CSV tables, shapefiles, GeoTIFF rasters) is actually written to disk."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
import rasterio

from shoreline_uncertainty.config import RunConfig, ShorelineYear, SiteConfig
from shoreline_uncertainty.pipeline import run_pipeline
from shoreline_uncertainty.transects import Transect, nearest_transect_net_distance


def _build_run_config(
    synthetic_site, output_dir, *,
    method="odb", professionals=None, compute_prob_change=False,
    prob_change_segment_length=50.0, compute_rate_of_change=False, rate_transect_spacing=1.0,
):
    shorelines = [
        ShorelineYear(year=year, path=path, rmse95_override=synthetic_site["radii"][year])
        for year, path in synthetic_site["paths"].items()
    ]
    site = SiteConfig(
        name="synthetic_site",
        shorelines=shorelines,
        transect_spacing=100.0,
        transect_length=40.0,
        professionals=professionals or [],
        rate_transect_spacing=rate_transect_spacing,
    )
    return RunConfig(
        sites=[site],
        output_dir=str(output_dir),
        target_crs=synthetic_site["crs"],
        epsilon_band_method=method,
        compute_prob_change=compute_prob_change,
        prob_change_segment_length=prob_change_segment_length,
        compute_rate_of_change=compute_rate_of_change,
        significance_threshold=0.05,
        raster_cell_size=2.0,
    )


def test_run_pipeline_odb_writes_expected_outputs(synthetic_site, tmp_path):
    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir, method="odb")
    results = run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    assert (site_dir / "odb_overlapping_buffer_table.csv").exists()
    assert (site_dir / "synthetic_site_OVERLAPPING_BANDS.txt").exists()
    assert (site_dir / "transects.shp").exists()
    assert (site_dir / "transect_intersections.csv").exists()
    assert (site_dir / "similarity_index.tif").exists()
    assert (site_dir / "significant_change.tif").exists()

    odb_df = results["synthetic_site"]["odb"]
    # 3 years -> 3 pairs; the far-apart 2000/2020 pair (15m offset, larger
    # combined buffer) and the near 2000/2010 pair should both be present.
    assert len(odb_df) == 3
    assert "SIGNIFICANT_CHANGE" in odb_df.columns

    with rasterio.open(site_dir / "similarity_index.tif") as src:
        data = src.read(1)
        assert data.sum() > 0


def test_run_pipeline_odb_with_compute_prob_change_writes_both(synthetic_site, tmp_path):
    """compute_prob_change must be combinable with epsilon_band_method="odb"
    (or perkal/both) -- regression test for the bug where prob_change rasters
    were only ever written when epsilon_band_method was exactly "prob_change",
    making it mutually exclusive with the ODB similarity/significance outputs."""
    output_dir = tmp_path / "pipeline_out_odb_prob_change"
    run = _build_run_config(synthetic_site, output_dir, method="odb", compute_prob_change=True)
    results = run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    # ODB outputs still present.
    assert (site_dir / "odb_overlapping_buffer_table.csv").exists()
    assert (site_dir / "similarity_index.tif").exists()
    assert (site_dir / "significant_change.tif").exists()

    # prob_change outputs also present, alongside the ODB ones.
    years = sorted(synthetic_site["paths"])
    for year in years:
        assert (site_dir / f"position_probability_density_{year}.tif").exists()
        assert (site_dir / f"position_confidence_{year}.tif").exists()
    for i, year_a in enumerate(years):
        for year_b in years[i + 1:]:
            assert (site_dir / f"position_delta_{year_a}_{year_b}.tif").exists()
            assert (site_dir / f"change_probability_{year_a}_{year_b}.tif").exists()
    assert (site_dir / "transect_change_probability.csv").exists()
    assert "prob_change" in results["synthetic_site"]

    with rasterio.open(site_dir / f"position_confidence_{years[0]}.tif") as src:
        data = src.read(1)
        assert data.max() > 0.9  # peaks near 1.0 on the digitized line


def test_run_pipeline_prob_change_segments_writes_segment_shapefiles(synthetic_site, tmp_path):
    """Part A: each shoreline in a year pair must be broken into
    change_probability_segments_<a>_vs_<b>.shp / _<b>_vs_<a>.shp, each
    segment carrying a PROB_CHANGE (truncated to PROB_CHANG by the ESRI
    Shapefile driver) attribute equal to the mean change_probability raster
    value sampled along that segment."""
    output_dir = tmp_path / "pipeline_out_prob_change_segments"
    # Baseline is ~1000m long; a 100m segment length gives several segments
    # per shoreline (not just one giant line) while staying fast.
    run = _build_run_config(
        synthetic_site, output_dir, method="odb", compute_prob_change=True, prob_change_segment_length=100.0,
    )
    results = run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    years = sorted(synthetic_site["paths"])
    for i, year_a in enumerate(years):
        for year_b in years[i + 1:]:
            path_ab = site_dir / f"change_probability_segments_{year_a}_vs_{year_b}.shp"
            path_ba = site_dir / f"change_probability_segments_{year_b}_vs_{year_a}.shp"
            assert path_ab.exists()
            assert path_ba.exists()
            for path in (path_ab, path_ba):
                gdf = gpd.read_file(path)
                # ESRI Shapefile driver truncates field names > 10 chars:
                # PROB_CHANGE (11 chars) -> PROB_CHANG (10 chars).
                assert "PROB_CHANG" in gdf.columns
                assert "SEG_ID" in gdf.columns
                assert "LENGTH" in gdf.columns
                # 1000m baseline / 100m segments -> multiple segments, not
                # one giant unsegmented line.
                assert len(gdf) > 1
                valid = gdf["PROB_CHANG"].dropna()
                assert (valid >= 0.0).all() and (valid <= 1.0).all()

    assert ("prob_change_segments" in results["synthetic_site"])


def test_run_pipeline_prob_change_segments_includes_magnitude_column(synthetic_site, tmp_path):
    """Each change_probability_segments_*.shp segment must also carry a
    MAGNITUDE attribute (negative = erosion, positive = accretion), sourced
    from transects.nearest_transect_net_distance against the *general*
    transect grid -- deliberately not derived from the change_probability
    raster's own delta, whose sign is not a reliable erosion/accretion
    indicator (see probability_surface.py's module docstring). This test
    recomputes the expected value independently from transects.shp +
    transect_distances_wide.csv and confirms it matches what pipeline.py
    wrote to each segment.
    """
    output_dir = tmp_path / "pipeline_out_magnitude"
    run = _build_run_config(
        synthetic_site, output_dir, method="odb", compute_prob_change=True, prob_change_segment_length=100.0,
    )
    run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    transects_gdf = gpd.read_file(site_dir / "transects.shp")
    wide = pd.read_csv(site_dir / "transect_distances_wide.csv")
    # ESRI Shapefile driver truncates TRANSECT_ID (11 chars) -> TRANSECT_I.
    id_col = "TRANSECT_I" if "TRANSECT_I" in transects_gdf.columns else "TRANSECT_ID"
    transects = [
        Transect(transect_id=int(row[id_col]), geometry=row.geometry, baseline_point=(0.0, 0.0))
        for _, row in transects_gdf.iterrows()
    ]
    if "TRANSECT_I" in wide.columns:
        wide = wide.rename(columns={"TRANSECT_I": "TRANSECT_ID"})

    years = sorted(synthetic_site["paths"])
    checked_any = False
    for i, year_a in enumerate(years):
        for year_b in years[i + 1:]:
            for suffix in (f"{year_a}_vs_{year_b}", f"{year_b}_vs_{year_a}"):
                gdf = gpd.read_file(site_dir / f"change_probability_segments_{suffix}.shp")
                assert "MAGNITUDE" in gdf.columns
                for _, seg_row in gdf.iterrows():
                    midpoint = seg_row.geometry.interpolate(0.5, normalized=True)
                    expected = nearest_transect_net_distance(midpoint, transects, wide, year_a, year_b)
                    if pd.isna(expected):
                        assert pd.isna(seg_row["MAGNITUDE"])
                    else:
                        assert seg_row["MAGNITUDE"] == pytest.approx(expected, abs=1e-6)
                        checked_any = True
    assert checked_any  # sanity check that the loop actually exercised real values


def test_run_pipeline_rate_of_change_writes_expected_outputs(synthetic_site, tmp_path):
    """Part B: a separate, denser transect grid (rate_transect_spacing)
    feeds EPR/LRR rate-of-change outputs, independent of compute_prob_change
    / epsilon_band_method. Uses the synthetic fixture's known geometry
    (years 2000/2010/2020, each 10 years apart, offsets 0/-5/-15 -- a
    constant retreat-acceleration pattern identical at every x along the
    baseline) to assert exact, derived numeric values rather than vague
    existence checks:
      - EPR_RATE = (TO_2020 - TO_2000) / 20 = 15/20 = 0.75 m/yr for every
        transect.
      - LRR_RATE must equal EPR_RATE exactly, a guaranteed property of OLS
        regression on 3 equally-spaced x-values (the middle year's
        deviation from the mean year is exactly zero, so it cannot affect
        the slope).
      - LRR_R2 ~= 0.9643 for every transect (hand-derived from relative
        y-values [0, 5, 15] at x=[2000, 2010, 2020]).
    """
    output_dir = tmp_path / "pipeline_out_rate_of_change"
    # Override the 1m default with something coarser for test speed -- the
    # synthetic baseline is roughly 1000m+ long.
    run = _build_run_config(
        synthetic_site, output_dir, method="odb", compute_rate_of_change=True, rate_transect_spacing=50.0,
    )
    results = run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    assert (site_dir / "rate_transects.shp").exists()
    assert (site_dir / "rate_transect_intersections.csv").exists()
    assert (site_dir / "transect_rate_of_change.csv").exists()

    rate_df = pd.read_csv(site_dir / "transect_rate_of_change.csv")
    for col in ["EPR_NET_DISTANCE", "EPR_RATE", "LRR_NET_DISTANCE", "LRR_RATE", "LRR_R2"]:
        assert col in rate_df.columns
    assert len(rate_df) > 1

    assert rate_df["EPR_RATE"].abs().to_numpy() == pytest.approx(0.75, abs=1e-3)
    assert rate_df["LRR_RATE"].to_numpy() == pytest.approx(rate_df["EPR_RATE"].to_numpy(), abs=1e-9)
    assert rate_df["LRR_R2"].to_numpy() == pytest.approx(0.9643, abs=5e-3)
    assert (rate_df["LRR_R2"] < 1.0).all()

    assert "rate_of_change" in results["synthetic_site"]


def test_run_pipeline_rate_of_change_writes_rate_change_polygons(synthetic_site, tmp_path):
    """build_rate_change_polygons' output -- the polygon area between each
    pair of sequentially-adjacent rate transects, carrying MAGNITUDE/RATE/
    PROB_CHANGE -- must be written (rate_change_polygons.shp) alongside
    transect_rate_of_change.csv whenever compute_rate_of_change is set.
    Uses the same constant-rate synthetic fixture as the EPR/LRR test above
    (every transect has |EPR_RATE| == 0.75 m/yr for the 2000-2020 pair), so
    every adjacent-pair polygon's RATE must match too.
    """
    output_dir = tmp_path / "pipeline_out_rate_polygons"
    run = _build_run_config(
        synthetic_site, output_dir, method="odb", compute_rate_of_change=True, rate_transect_spacing=50.0,
    )
    results = run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    path = site_dir / "rate_change_polygons.shp"
    assert path.exists()
    gdf = gpd.read_file(path)
    assert len(gdf) > 0
    for col in ["TRANSECT_A", "TRANSECT_B", "YEAR_A", "YEAR_B", "MAGNITUDE", "RATE"]:
        assert col in gdf.columns
    # ESRI Shapefile driver truncates PROB_CHANGE (11 chars) -> PROB_CHANG.
    assert "PROB_CHANG" in gdf.columns

    pair = gdf[(gdf["YEAR_A"] == 2000) & (gdf["YEAR_B"] == 2020)]
    assert len(pair) > 0
    assert pair["RATE"].abs().to_numpy() == pytest.approx(0.75, abs=1e-2)
    assert (pair["PROB_CHANG"] >= 0.0).all() and (pair["PROB_CHANG"] <= 1.0).all()
    assert (gdf.geometry.area > 0).all()

    assert "rate_change_polygons" in results["synthetic_site"]


def test_run_pipeline_perkal_writes_critical_areas(synthetic_site, tmp_path):
    output_dir = tmp_path / "pipeline_out_perkal"
    run = _build_run_config(synthetic_site, output_dir, method="perkal")
    run.confidence_levels = [0.5]
    run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    assert (site_dir / "perkal_shoreline_buffer_table.csv").exists()
    assert (site_dir / "critical_areas_summary.csv").exists()


def test_run_pipeline_with_professionals_writes_comparison_tables(synthetic_site, synthetic_professionals, tmp_path):
    from shoreline_uncertainty.config import ProfessionalDelineation

    output_dir = tmp_path / "pipeline_out_prof"
    professionals = [
        ProfessionalDelineation(name=name, year=synthetic_professionals["year"], path=path)
        for name, path in synthetic_professionals["paths"].items()
    ]
    run = _build_run_config(synthetic_site, output_dir, method="odb", professionals=professionals)
    run_pipeline(run)

    site_dir = output_dir / "synthetic_site"
    assert (site_dir / "professional_comparison_me_to_prof.csv").exists()
    assert (site_dir / "professional_comparison_prof_to_prof.csv").exists()
    assert (site_dir / "professional_comparison_summary.csv").exists()


def test_run_pipeline_multiple_sites_get_separate_dirs(synthetic_site, tmp_path):
    output_dir = tmp_path / "pipeline_out_multi"
    shorelines = [
        ShorelineYear(year=year, path=path, rmse95_override=synthetic_site["radii"][year])
        for year, path in synthetic_site["paths"].items()
    ]
    site_a = SiteConfig(name="site_a", shorelines=shorelines, transect_spacing=100.0, transect_length=40.0)
    site_b = SiteConfig(name="site_b", shorelines=shorelines, transect_spacing=100.0, transect_length=40.0)
    run = RunConfig(sites=[site_a, site_b], output_dir=str(output_dir), target_crs=synthetic_site["crs"])
    results = run_pipeline(run)

    assert set(results) == {"site_a", "site_b"}
    assert (output_dir / "site_a").exists()
    assert (output_dir / "site_b").exists()
