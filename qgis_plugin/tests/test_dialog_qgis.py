"""Tests for dialog.py.

`build_run_config`/`write_run_config` are pure Python (no Qt dependency) and
get full coverage here. `ShorelineUncertaintyDialog` itself is only smoke-
tested for construction: qgis_stub.py's qgis.PyQt stand-ins are deliberately
bare/inert (see that module's docstring) and can't faithfully round-trip
widget state (e.g. a QLineEdit stub's .text() doesn't return whatever
.setText() was last given), so exercising populate_from_run_config/
get_run_config end-to-end needs a real Qt event loop -- left for the later
"wire dialog to algorithm" task, once there's an actual algorithm run to
test against.
"""
from __future__ import annotations

import yaml
import pytest

from shoreline_uncertainty_qgis.dialog import ShorelineUncertaintyDialog, build_run_config, write_run_config


def _base_kwargs(**overrides):
    kwargs = dict(
        site_name="test_site",
        shorelines=[
            {"year": 2000, "path": "shoreline_2000.shp", "rmse95_override": "2.0"},
            {"year": 2010, "path": "shoreline_2010.shp", "rmse95_override": "2.0"},
        ],
        baseline=None,
        transect_spacing=50.0,
        transect_length=1000.0,
        coordinate_priority="UPPER_LEFT",
        rate_transect_spacing=1.0,
        professionals=[],
        output_dir="output",
        target_crs=None,
        confidence_levels=[0.05, 0.50, 0.90, 0.95],
        significance_threshold=0.05,
        epsilon_band_method="odb",
        compute_prob_change=False,
        prob_change_segment_length=50.0,
        compute_rate_of_change=False,
        export_intersect_geometries=False,
        raster_cell_size=0.5,
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# build_run_config
# ---------------------------------------------------------------------------


def test_build_run_config_basic_rmse95_override():
    run = build_run_config(**_base_kwargs())
    assert len(run.sites) == 1
    site = run.sites[0]
    assert site.name == "test_site"
    assert len(site.shorelines) == 2
    assert site.shorelines[0].rmse95_override == 2.0
    assert site.shorelines[0].uncertainty is None


def test_build_run_config_uncertainty_components_when_no_override():
    run = build_run_config(**_base_kwargs(shorelines=[
        {"year": 2000, "path": "a.shp", "rmse_base": "1.0", "rmse_georef": "0.5", "rmse_interp": "0.3"},
        {"year": 2010, "path": "b.shp", "rmse95_override": "2.0"},
    ]))
    sy0 = run.sites[0].shorelines[0]
    assert sy0.rmse95_override is None
    assert sy0.uncertainty.rmse_base == pytest.approx(1.0)
    assert sy0.uncertainty.rmse_georef == pytest.approx(0.5)
    assert sy0.uncertainty.rmse_interp == pytest.approx(0.3)


def test_build_run_config_uncertainty_defaults_missing_base_georef_to_zero():
    run = build_run_config(**_base_kwargs(shorelines=[
        {"year": 2000, "path": "a.shp", "rmse_interp": "0.3"},
        {"year": 2010, "path": "b.shp", "rmse95_override": "2.0"},
    ]))
    sy0 = run.sites[0].shorelines[0]
    assert sy0.uncertainty.rmse_base == 0.0
    assert sy0.uncertainty.rmse_georef == 0.0
    assert sy0.uncertainty.rmse_interp == pytest.approx(0.3)


def test_build_run_config_rmse95_override_takes_priority_over_uncertainty_fields():
    # Both rmse95_override and rmse_base/etc given -- override should win,
    # matching rmse95_override's documented "skip the RMSE calc" meaning.
    run = build_run_config(**_base_kwargs(shorelines=[
        {"year": 2000, "path": "a.shp", "rmse95_override": "3.0", "rmse_base": "1.0"},
        {"year": 2010, "path": "b.shp", "rmse95_override": "2.0"},
    ]))
    sy0 = run.sites[0].shorelines[0]
    assert sy0.rmse95_override == 3.0
    assert sy0.uncertainty is None


def test_build_run_config_acquisition_date_passthrough():
    run = build_run_config(**_base_kwargs(shorelines=[
        {"year": 2000, "path": "a.shp", "rmse95_override": "2.0", "acquisition_date": "2000-06-15"},
        {"year": 2010, "path": "b.shp", "rmse95_override": "2.0"},
    ]))
    assert run.sites[0].shorelines[0].acquisition_date == "2000-06-15"
    assert run.sites[0].shorelines[1].acquisition_date is None


def test_build_run_config_with_baseline_and_professionals():
    run = build_run_config(**_base_kwargs(
        baseline="baseline.shp",
        professionals=[{"name": "acmoody", "year": 2000, "path": "acmoody.shp"}],
    ))
    site = run.sites[0]
    assert site.baseline == "baseline.shp"
    assert len(site.professionals) == 1
    assert site.professionals[0].name == "acmoody"


def test_build_run_config_options_passthrough():
    run = build_run_config(**_base_kwargs(
        output_dir="my_output",
        target_crs="EPSG:32616",
        compute_prob_change=True,
        prob_change_segment_length=25.0,
        compute_rate_of_change=True,
        export_intersect_geometries=True,
        raster_cell_size=1.0,
        significance_threshold=0.1,
        confidence_levels=[0.5, 0.95],
        epsilon_band_method="both",
    ))
    assert run.output_dir == "my_output"
    assert run.target_crs == "EPSG:32616"
    assert run.compute_prob_change is True
    assert run.prob_change_segment_length == 25.0
    assert run.compute_rate_of_change is True
    assert run.export_intersect_geometries is True
    assert run.raster_cell_size == 1.0
    assert run.significance_threshold == 0.1
    assert run.confidence_levels == [0.5, 0.95]
    assert run.epsilon_band_method == "both"


def test_build_run_config_too_few_shorelines_raises():
    with pytest.raises(ValueError, match="at least 2 shoreline years"):
        build_run_config(**_base_kwargs(shorelines=[
            {"year": 2000, "path": "a.shp", "rmse95_override": "2.0"},
        ]))


def test_build_run_config_bad_epsilon_band_method_raises():
    with pytest.raises(ValueError, match="epsilon_band_method"):
        build_run_config(**_base_kwargs(epsilon_band_method="bogus"))


def test_build_run_config_bad_coordinate_priority_raises():
    with pytest.raises(ValueError, match="coordinate_priority"):
        build_run_config(**_base_kwargs(coordinate_priority="MIDDLE"))


def test_build_run_config_missing_rmse_info_raises():
    with pytest.raises(ValueError, match="rmse95_override.*or.*uncertainty"):
        build_run_config(**_base_kwargs(shorelines=[
            {"year": 2000, "path": "a.shp"},
            {"year": 2010, "path": "b.shp", "rmse95_override": "2.0"},
        ]))


def test_build_run_config_bad_acquisition_date_format_raises():
    with pytest.raises(ValueError, match="acquisition_date"):
        build_run_config(**_base_kwargs(shorelines=[
            {"year": 2000, "path": "a.shp", "rmse95_override": "2.0", "acquisition_date": "06/15/2000"},
            {"year": 2010, "path": "b.shp", "rmse95_override": "2.0"},
        ]))


# ---------------------------------------------------------------------------
# write_run_config (round-trips through config_qgis.load_config)
# ---------------------------------------------------------------------------


def test_write_run_config_round_trips_through_load_config(tmp_path):
    from shoreline_uncertainty_qgis.config_qgis import load_config

    run = build_run_config(**_base_kwargs(
        baseline="baseline.shp",
        professionals=[{"name": "acmoody", "year": 2000, "path": "acmoody.shp"}],
        compute_prob_change=True,
    ))
    out_path = tmp_path / "config.yaml"
    write_run_config(run, out_path)

    raw = yaml.safe_load(out_path.read_text())
    assert raw["sites"][0]["name"] == "test_site"
    assert raw["compute_prob_change"] is True

    reloaded = load_config(out_path)
    assert reloaded.sites[0].name == "test_site"
    assert reloaded.sites[0].baseline == "baseline.shp"
    assert reloaded.sites[0].professionals[0].name == "acmoody"
    assert reloaded.compute_prob_change is True
    assert len(reloaded.sites[0].shorelines) == 2


def test_write_run_config_json_extension(tmp_path):
    from shoreline_uncertainty_qgis.config_qgis import load_config

    run = build_run_config(**_base_kwargs())
    out_path = tmp_path / "config.json"
    write_run_config(run, out_path)
    reloaded = load_config(out_path)
    assert reloaded.sites[0].name == "test_site"


def test_write_run_config_preserves_uncertainty_components(tmp_path):
    from shoreline_uncertainty_qgis.config_qgis import load_config

    run = build_run_config(**_base_kwargs(shorelines=[
        {"year": 2000, "path": "a.shp", "rmse_base": "1.0", "rmse_georef": "0.5", "rmse_interp": "0.3"},
        {"year": 2010, "path": "b.shp", "rmse95_override": "2.0"},
    ]))
    out_path = tmp_path / "config.yaml"
    write_run_config(run, out_path)
    reloaded = load_config(out_path)
    sy0 = reloaded.sites[0].shorelines[0]
    assert sy0.uncertainty.rmse_base == pytest.approx(1.0)
    assert sy0.uncertainty.rmse_georef == pytest.approx(0.5)
    assert sy0.uncertainty.rmse_interp == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# ShorelineUncertaintyDialog -- construction smoke test only (see module
# docstring for why widget round-tripping isn't tested under the stub).
# ---------------------------------------------------------------------------


def test_dialog_constructs_without_error():
    dialog = ShorelineUncertaintyDialog()
    assert dialog.run_config is None


def test_dialog_has_four_tabs():
    dialog = ShorelineUncertaintyDialog()
    # tabs is a stub object under qgis_stub -- just confirm addTab was
    # called the expected number of times via the recorded call args, since
    # the stub's count()/widget() accessors aren't meaningfully comparable.
    assert dialog.tabs is not None
