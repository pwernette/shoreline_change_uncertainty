"""Tests for runner.py's execute_run_config -- ties a dialog-built RunConfig
to RunAnalysisAlgorithm and to result_loader.load_output_layers, the actual
run-and-load logic behind plugin.py's run() (task #76). Reuses the same
synthetic_site fixture and RunConfig-construction pattern as
test_processing_algorithm_qgis.py.

Uses a fresh QgsProject() instance (not QgsProject.instance(), the
process-wide singleton) as the `project` argument so these tests don't leak
layers into other tests/files that touch the singleton.
"""
from __future__ import annotations

import pytest
from qgis.core import QgsProcessingException, QgsProject, QgsRasterLayer, QgsVectorLayer

from shoreline_uncertainty_qgis.config_qgis import RunConfig, ShorelineYear, SiteConfig
from shoreline_uncertainty_qgis.runner import execute_run_config


def _build_run_config(synthetic_site, output_dir, sites=None):
    if sites is None:
        shorelines = [
            ShorelineYear(year=year, path=path, rmse95_override=synthetic_site["radii"][year])
            for year, path in synthetic_site["paths"].items()
        ]
        sites = [
            SiteConfig(
                name="synthetic_site",
                shorelines=shorelines,
                transect_spacing=100.0,
                transect_length=40.0,
            )
        ]
    return RunConfig(
        sites=sites,
        output_dir=str(output_dir),
        target_crs=synthetic_site["crs"],
        epsilon_band_method="odb",
        raster_cell_size=2.0,
    )


def test_execute_run_config_runs_pipeline_and_loads_layers(synthetic_site, tmp_path):
    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir)
    project = QgsProject()

    result = execute_run_config(run, project=project)

    assert result["output_dir"] == str(output_dir)
    assert len(result["layers"]) > 0
    assert all(isinstance(l, (QgsVectorLayer, QgsRasterLayer)) for l in result["layers"])
    assert all(l.isValid() for l in result["layers"])
    assert project.mapLayers() == result["layers"]

    # Sanity: the well-known files this config produces are actually
    # present and were picked up as layers (not just "some files exist").
    layer_names = {l.name() for l in result["layers"]}
    assert "transects" in layer_names


def test_execute_run_config_defaults_to_project_instance(synthetic_site, tmp_path, monkeypatch):
    output_dir = tmp_path / "pipeline_out"
    run = _build_run_config(synthetic_site, output_dir)

    fresh_project = QgsProject()
    monkeypatch.setattr(QgsProject, "_instance", None)
    monkeypatch.setattr(QgsProject, "instance", staticmethod(lambda: fresh_project))

    result = execute_run_config(run)

    assert fresh_project.mapLayers() == result["layers"]


def test_execute_run_config_propagates_bad_config_as_processing_exception(synthetic_site, tmp_path):
    run = _build_run_config(synthetic_site, tmp_path / "pipeline_out", sites=[])  # no sites -> invalid

    with pytest.raises(QgsProcessingException, match="at least one site"):
        execute_run_config(run, project=QgsProject())
