"""Positional uncertainty (RMSE) calculations.

Replaces original_program/arcgis_pro/add_field.py, which only added an empty
'UNCERTAINTY' float attribute to each shoreline feature class for an analyst
to fill in by hand later in ArcGIS. Here the radius is actually computed from
its components, per Wernette et al. (2017):

    Eq. 1:  RMSE_I = sqrt(sum(d^2) / n)
            -- interpretation/digitizing error from n transect offsets d
    Eq. 2:  RMSE_O = sqrt(RMSE_B^2 + RMSE_G^2 + RMSE_I^2)
            -- combines base-image (B), georeferencing (G), and interpretation (I) error
    Eq. 3:  RMSE95 = 1.7308 * RMSE_O
            -- NSSDA 95% circular/radial accuracy standard

RMSE95 becomes the buffer radius used by epsilon_bands.py (the "UNCERTAINTY"
attribute in the original scripts).
"""
from __future__ import annotations

import math
from typing import Iterable

from .config import ShorelineYear, UncertaintyComponents


def rmse_interpretation(distances: Iterable[float]) -> float:
    """Eq. 1: RMSE_I = sqrt(sum(d^2) / n)."""
    distances = list(distances)
    if not distances:
        raise ValueError("Need at least one distance to compute RMSE_I.")
    n = len(distances)
    return math.sqrt(sum(d ** 2 for d in distances) / n)


def rmse_overall(rmse_base: float, rmse_georef: float, rmse_interp: float) -> float:
    """Eq. 2: RMSE_O = sqrt(RMSE_B^2 + RMSE_G^2 + RMSE_I^2)."""
    return math.sqrt(rmse_base ** 2 + rmse_georef ** 2 + rmse_interp ** 2)


def rmse95(rmse_o: float) -> float:
    """Eq. 3: RMSE95 = 1.7308 * RMSE_O."""
    return 1.7308 * rmse_o


def compute_uncertainty_radius(components: UncertaintyComponents) -> float:
    """Compute the RMSE95 buffer radius from a set of RMSE components."""
    if components.rmse_interp is not None:
        rmse_i = components.rmse_interp
    elif components.interp_distances:
        rmse_i = rmse_interpretation(components.interp_distances)
    else:
        raise ValueError(
            "UncertaintyComponents needs either 'rmse_interp' or 'interp_distances'."
        )
    rmse_o = rmse_overall(components.rmse_base, components.rmse_georef, rmse_i)
    return rmse95(rmse_o)


def resolve_uncertainty_radius(shoreline_year: ShorelineYear) -> float:
    """Resolve the buffer radius for one shoreline year: a manual override
    takes precedence, otherwise compute it from RMSE components."""
    if shoreline_year.rmse95_override is not None:
        return float(shoreline_year.rmse95_override)
    if shoreline_year.uncertainty is None:
        raise ValueError(
            f"Shoreline year {shoreline_year.year} has neither 'rmse95_override' "
            "nor 'uncertainty' components defined in the config."
        )
    return compute_uncertainty_radius(shoreline_year.uncertainty)


def assign_uncertainty(site_config) -> dict:
    """Compute uncertainty radii for every shoreline year in a site.

    Returns {year: radius_in_map_units}, replacing the manual, per-feature
    UNCERTAINTY field population implied (but not automated) by add_field.py.
    """
    return {sy.year: resolve_uncertainty_radius(sy) for sy in site_config.shorelines}
