import math

import pytest

from shoreline_uncertainty.config import ShorelineYear, UncertaintyComponents
from shoreline_uncertainty.uncertainty import (
    assign_uncertainty,
    compute_uncertainty_radius,
    resolve_uncertainty_radius,
    rmse95,
    rmse_interpretation,
    rmse_overall,
)


def test_rmse_interpretation_known_values():
    # d = [3, 4] -> sqrt((9+16)/2) = sqrt(12.5)
    assert rmse_interpretation([3, 4]) == pytest.approx(math.sqrt(12.5))


def test_rmse_interpretation_requires_data():
    with pytest.raises(ValueError):
        rmse_interpretation([])


def test_rmse_overall_pythagorean():
    # 3-4-5-ish combination: sqrt(3^2 + 4^2 + 0^2) = 5
    assert rmse_overall(3, 4, 0) == pytest.approx(5.0)


def test_rmse95_nssda_constant():
    assert rmse95(1.0) == pytest.approx(1.7308)
    assert rmse95(2.0) == pytest.approx(3.4616)


def test_compute_uncertainty_radius_from_distances():
    components = UncertaintyComponents(rmse_base=1.0, rmse_georef=1.0, interp_distances=[1.0, 1.0, 1.0])
    rmse_i = rmse_interpretation([1.0, 1.0, 1.0])
    expected = rmse95(rmse_overall(1.0, 1.0, rmse_i))
    assert compute_uncertainty_radius(components) == pytest.approx(expected)


def test_compute_uncertainty_radius_needs_interp_info():
    with pytest.raises(ValueError):
        compute_uncertainty_radius(UncertaintyComponents(rmse_base=1.0, rmse_georef=1.0))


def test_resolve_uncertainty_radius_override_wins():
    sy = ShorelineYear(year=2000, path="dummy.shp", rmse95_override=7.5,
                        uncertainty=UncertaintyComponents(rmse_base=1, rmse_georef=1, rmse_interp=1))
    assert resolve_uncertainty_radius(sy) == 7.5


def test_resolve_uncertainty_radius_from_components():
    sy = ShorelineYear(year=2000, path="dummy.shp",
                        uncertainty=UncertaintyComponents(rmse_base=0.5, rmse_georef=0.5, rmse_interp=0.5))
    expected = rmse95(rmse_overall(0.5, 0.5, 0.5))
    assert resolve_uncertainty_radius(sy) == pytest.approx(expected)


def test_resolve_uncertainty_radius_missing_everything():
    sy = ShorelineYear(year=2000, path="dummy.shp")
    with pytest.raises(ValueError):
        resolve_uncertainty_radius(sy)


def test_assign_uncertainty_for_site():
    from shoreline_uncertainty.config import SiteConfig

    site = SiteConfig(
        name="test",
        shorelines=[
            ShorelineYear(year=2000, path="a.shp", rmse95_override=2.0),
            ShorelineYear(year=2010, path="b.shp", rmse95_override=3.0),
        ],
    )
    radii = assign_uncertainty(site)
    assert radii == {2000: 2.0, 2010: 3.0}
