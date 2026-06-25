import json

import pytest
import yaml

from shoreline_uncertainty.config import (
    RunConfig,
    ShorelineYear,
    SiteConfig,
    UncertaintyComponents,
    load_config,
    validate_config,
)


def _minimal_raw_config(tmp_path):
    return {
        "output_dir": str(tmp_path / "out"),
        "sites": [
            {
                "name": "test_site",
                "shorelines": [
                    {"year": 2000, "path": "a.shp", "rmse95_override": 2.0},
                    {"year": 2010, "path": "b.shp", "rmse95_override": 3.0},
                ],
            }
        ],
    }


def test_load_config_yaml(tmp_path):
    raw = _minimal_raw_config(tmp_path)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    run = load_config(path)
    assert isinstance(run, RunConfig)
    assert len(run.sites) == 1
    assert run.sites[0].name == "test_site"
    assert run.sites[0].shorelines[0].rmse95_override == 2.0


def test_load_config_json(tmp_path):
    raw = _minimal_raw_config(tmp_path)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    run = load_config(path)
    assert run.sites[0].name == "test_site"


def test_load_config_rejects_unknown_extension(tmp_path):
    path = tmp_path / "config.txt"
    path.write_text("{}")
    with pytest.raises(ValueError):
        load_config(path)


def test_validate_config_requires_at_least_one_site():
    run = RunConfig(sites=[])
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_requires_two_years_per_site():
    site = SiteConfig(name="s", shorelines=[ShorelineYear(year=2000, path="a.shp", rmse95_override=1.0)])
    run = RunConfig(sites=[site])
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_rejects_duplicate_years():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", rmse95_override=1.0),
            ShorelineYear(year=2000, path="b.shp", rmse95_override=1.0),
        ],
    )
    run = RunConfig(sites=[site])
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_rejects_bad_coordinate_priority():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", rmse95_override=1.0),
            ShorelineYear(year=2010, path="b.shp", rmse95_override=1.0),
        ],
        coordinate_priority="MIDDLE",
    )
    run = RunConfig(sites=[site])
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_rejects_bad_epsilon_band_method():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", rmse95_override=1.0),
            ShorelineYear(year=2010, path="b.shp", rmse95_override=1.0),
        ],
    )
    run = RunConfig(sites=[site], epsilon_band_method="bogus")
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_requires_uncertainty_or_override():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp"),  # neither override nor components
            ShorelineYear(year=2010, path="b.shp", rmse95_override=1.0),
        ],
    )
    run = RunConfig(sites=[site])
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_rejects_non_positive_prob_change_segment_length():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", rmse95_override=1.0),
            ShorelineYear(year=2010, path="b.shp", rmse95_override=1.0),
        ],
    )
    run = RunConfig(sites=[site], prob_change_segment_length=0.0)
    with pytest.raises(ValueError):
        validate_config(run)
    run = RunConfig(sites=[site], prob_change_segment_length=-10.0)
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_rejects_non_positive_rate_transect_spacing():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", rmse95_override=1.0),
            ShorelineYear(year=2010, path="b.shp", rmse95_override=1.0),
        ],
        rate_transect_spacing=0.0,
    )
    run = RunConfig(sites=[site])
    with pytest.raises(ValueError):
        validate_config(run)


def test_validate_config_accepts_compute_rate_of_change_and_custom_spacing():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", rmse95_override=1.0),
            ShorelineYear(year=2010, path="b.shp", rmse95_override=1.0),
        ],
        rate_transect_spacing=2.5,
    )
    run = RunConfig(sites=[site], compute_rate_of_change=True, prob_change_segment_length=25.0)
    validate_config(run)  # should not raise


def test_load_config_reads_new_rate_and_segment_options(tmp_path):
    raw = _minimal_raw_config(tmp_path)
    raw["compute_rate_of_change"] = True
    raw["prob_change_segment_length"] = 30.0
    raw["sites"][0]["rate_transect_spacing"] = 5.0
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    run = load_config(path)
    assert run.compute_rate_of_change is True
    assert run.prob_change_segment_length == pytest.approx(30.0)
    assert run.sites[0].rate_transect_spacing == pytest.approx(5.0)


def test_validate_config_passes_for_well_formed_config():
    site = SiteConfig(
        name="s",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", uncertainty=UncertaintyComponents(rmse_base=1, rmse_georef=1, rmse_interp=1)),
            ShorelineYear(year=2010, path="b.shp", rmse95_override=3.0),
        ],
    )
    run = RunConfig(sites=[site])
    validate_config(run)  # should not raise
