"""Tests for processing_algorithm.py: RunAnalysisAlgorithm and
WaterLevelLookupAlgorithm, both QgsProcessingAlgorithm subclasses. Uses the
qgis_stub.py QgsProcessingAlgorithm/QgsProcessingFeedback stand-ins (see
that module's docstring) -- parameterAs*() reads straight from a plain
`parameters` dict, bypassing the real Processing framework's own parameter
resolution, so each algorithm's own processAlgorithm logic is exercised
directly without a live Processing context.

RunAnalysisAlgorithm tests reuse the same synthetic_site fixture and
RunConfig-construction pattern as test_pipeline_qgis.py, writing it to a
real YAML file via dialog.write_run_config so the algorithm is exercised
through its actual config-file-path parameter rather than a pre-built
RunConfig object.

WaterLevelLookupAlgorithm tests mock out get_annual_water_level/
get_water_level the same way tests/test_water_level.py's CLI section does:
monkeypatching the *importing* module's (processing_algorithm's) own
namespace reference, so no live network call is ever made.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest
from qgis.core import QgsProcessingException, QgsProcessingFeedback

from shoreline_uncertainty_qgis import water_level_qgis as wl
from shoreline_uncertainty_qgis.config_qgis import RunConfig, ShorelineYear, SiteConfig
from shoreline_uncertainty_qgis.dialog import write_run_config
from shoreline_uncertainty_qgis.processing_algorithm import RunAnalysisAlgorithm, WaterLevelLookupAlgorithm


def _build_run_config(synthetic_site, output_dir):
    shorelines = [
        ShorelineYear(year=year, path=path, rmse95_override=synthetic_site["radii"][year])
        for year, path in synthetic_site["paths"].items()
    ]
    site = SiteConfig(
        name="synthetic_site",
        shorelines=shorelines,
        transect_spacing=100.0,
        transect_length=40.0,
    )
    return RunConfig(
        sites=[site],
        output_dir=str(output_dir),
        target_crs=synthetic_site["crs"],
        epsilon_band_method="odb",
        raster_cell_size=2.0,
    )


# ---------------------------------------------------------------------------
# RunAnalysisAlgorithm
# ---------------------------------------------------------------------------


def test_run_analysis_algorithm_metadata():
    alg = RunAnalysisAlgorithm()
    assert alg.name() == "run_analysis"
    assert alg.groupId() == "shoreline_uncertainty"
    alg.initAlgorithm()
    names = {p.name() for p in alg.parameterDefinitions()}
    assert names == {"CONFIG", "OUTPUT_DIR"}


def test_run_analysis_algorithm_runs_pipeline(synthetic_site, tmp_path):
    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir)
    config_path = tmp_path / "config.yaml"
    write_run_config(run, config_path)

    alg = RunAnalysisAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    result = alg.processAlgorithm({"CONFIG": str(config_path)}, None, feedback)

    assert result["OUTPUT_DIR"] == str(output_dir)
    site_dir = output_dir / "synthetic_site"
    assert (site_dir / "odb_overlapping_buffer_table.csv").exists()
    assert (site_dir / "transects.shp").exists()


def test_run_analysis_algorithm_output_dir_override(synthetic_site, tmp_path):
    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir)
    config_path = tmp_path / "config.yaml"
    write_run_config(run, config_path)

    override_dir = tmp_path / "override_out"
    alg = RunAnalysisAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    result = alg.processAlgorithm(
        {"CONFIG": str(config_path), "OUTPUT_DIR": str(override_dir)}, None, feedback
    )

    assert result["OUTPUT_DIR"] == str(override_dir)
    assert (override_dir / "synthetic_site" / "transects.shp").exists()
    assert not (output_dir / "synthetic_site").exists()


def test_run_analysis_algorithm_missing_config_raises():
    alg = RunAnalysisAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    with pytest.raises(QgsProcessingException):
        alg.processAlgorithm({"CONFIG": ""}, None, feedback)


def test_run_analysis_algorithm_bad_config_raises_processing_exception(tmp_path):
    bad_path = tmp_path / "bad_config.yaml"
    bad_path.write_text("sites: []\n")  # fails validate_config: needs >=1 site

    alg = RunAnalysisAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    with pytest.raises(QgsProcessingException, match="at least one site"):
        alg.processAlgorithm({"CONFIG": str(bad_path)}, None, feedback)


# ---------------------------------------------------------------------------
# WaterLevelLookupAlgorithm
# ---------------------------------------------------------------------------


SF_STATION = wl.WaterLevelStation(id="9414290", name="San Francisco, CA", lat=37.806, lng=-122.465, greatlakes=False)


def _annual_result(value=176.5):
    return wl.WaterLevelResult(
        station=SF_STATION, datum="MSL", units="metric", value=value, value_type="monthly_mean",
        period_start="2000-01-01", period_end="2000-12-31", n_observations=12, fallback_used=None,
    )


def test_water_level_lookup_algorithm_metadata():
    alg = WaterLevelLookupAlgorithm()
    assert alg.name() == "water_level_lookup"
    alg.initAlgorithm()
    names = {p.name() for p in alg.parameterDefinitions()}
    assert names == {"CONFIG", "OUT", "DATUM", "WINDOW_DAYS", "SLEEP"}


def test_water_level_lookup_algorithm_writes_csv(synthetic_site, tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        "shoreline_uncertainty_qgis.processing_algorithm.get_annual_water_level",
        lambda *a, **k: _annual_result(),
    )

    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir)
    config_path = tmp_path / "config.yaml"
    write_run_config(run, config_path)
    out_path = tmp_path / "water_levels.csv"

    alg = WaterLevelLookupAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    result = alg.processAlgorithm(
        {"CONFIG": str(config_path), "OUT": str(out_path), "WINDOW_DAYS": 0, "SLEEP": 0.0}, None, feedback
    )

    assert result["OUT"] == str(out_path)
    assert out_path.exists()
    df = pd.read_csv(out_path)
    assert len(df) == len(synthetic_site["paths"])  # one row per shoreline year
    assert df["error"].isna().all()
    assert (df["water_level"] == 176.5).all()


def test_water_level_lookup_algorithm_default_out_path(synthetic_site, tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        "shoreline_uncertainty_qgis.processing_algorithm.get_annual_water_level",
        lambda *a, **k: _annual_result(),
    )

    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir)
    config_path = tmp_path / "config.yaml"
    write_run_config(run, config_path)

    alg = WaterLevelLookupAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    result = alg.processAlgorithm(
        {"CONFIG": str(config_path), "WINDOW_DAYS": 0, "SLEEP": 0.0}, None, feedback
    )

    expected = output_dir / "water_levels.csv"
    assert result["OUT"] == str(expected)
    assert expected.exists()


def test_water_level_lookup_algorithm_records_errors_per_row(synthetic_site, tmp_path, monkeypatch):
    def _raise(*a, **k):
        raise wl.WaterLevelError("no nearby station")

    monkeypatch.setattr(time, "sleep", lambda *_: None)
    monkeypatch.setattr("shoreline_uncertainty_qgis.processing_algorithm.get_annual_water_level", _raise)

    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir)
    config_path = tmp_path / "config.yaml"
    write_run_config(run, config_path)
    out_path = tmp_path / "water_levels.csv"

    alg = WaterLevelLookupAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    alg.processAlgorithm(
        {"CONFIG": str(config_path), "OUT": str(out_path), "WINDOW_DAYS": 0, "SLEEP": 0.0}, None, feedback
    )

    df = pd.read_csv(out_path)
    assert (df["error"] == "no nearby station").all()


def test_water_level_lookup_algorithm_missing_config_raises():
    alg = WaterLevelLookupAlgorithm()
    alg.initAlgorithm()
    feedback = QgsProcessingFeedback()
    with pytest.raises(QgsProcessingException):
        alg.processAlgorithm({"CONFIG": ""}, None, feedback)
