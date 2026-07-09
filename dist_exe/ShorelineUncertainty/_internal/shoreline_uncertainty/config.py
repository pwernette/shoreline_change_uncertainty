"""Configuration loading and validation for the shoreline_uncertainty pipeline.

Replaces the hardcoded site/year lists copy-pasted across nearly every script
in original_program/arcgis_pro/ (e.g. `locations = ['alcona','allegan',
'manistee','sanilac']` plus a per-site `*_years` list, repeated almost
verbatim in add_field.py, perkal_bands.py, Identify_Critical_Areas.py,
intersecting_epsilon_bands.py, transect_analysis.py, raster_buffers_analysis.py,
etc.) with a single YAML or JSON run configuration that works for any number
of sites, years, and shapefiles.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class UncertaintyComponents:
    """Per-shoreline RMSE inputs used to compute positional uncertainty.

    Mirrors Wernette et al. (2017) Eqs. 1-3:
        RMSE_I = sqrt(sum(d^2) / n)                     -- interpretation/digitizing error
        RMSE_O = sqrt(RMSE_B^2 + RMSE_G^2 + RMSE_I^2)    -- combined positional error
        RMSE95 = 1.7308 * RMSE_O                          -- NSSDA 95% radial accuracy

    Provide either `rmse_interp` directly, or `interp_distances` (the raw
    digitizing/transect offsets `d`) and it will be computed for you.
    """

    rmse_base: float = 0.0
    rmse_georef: float = 0.0
    rmse_interp: Optional[float] = None
    interp_distances: Optional[list] = None


@dataclass
class ShorelineYear:
    """One year's shoreline for one site."""

    year: int
    path: str
    uncertainty: Optional[UncertaintyComponents] = None
    rmse95_override: Optional[float] = None  # skip the RMSE calc, use this buffer radius directly
    # Optional actual capture date ("YYYY-MM-DD"), separate from the label
    # `year` above. Not used anywhere in the core RMSE/epsilon-band pipeline
    # -- it only matters to water_level.get_water_level (via the
    # `water-levels` CLI subcommand), which needs the real day a shoreline
    # was digitized to look up the water level at that moment, not just its
    # label year. Leave unset to only support year-level water-level lookups
    # (water_level.get_annual_water_level) for this shoreline.
    acquisition_date: Optional[str] = None


@dataclass
class ProfessionalDelineation:
    """An independently-delineated ('professional') shoreline used for
    inter-analyst comparison, replacing professional_comparison.py's
    hardcoded `professionals = ['acmoody','goodwin','lusch']` list."""

    name: str
    year: int
    path: str


@dataclass
class SiteConfig:
    """One physical study site: its shoreline years, baseline, transect
    geometry, and (optionally) professional-delineation comparison data.
    A RunConfig holds a list of these -- one run can process any number of
    sites, each independently configured.
    """

    name: str
    shorelines: list  # list[ShorelineYear]
    baseline: Optional[str] = None
    transect_spacing: float = 50.0
    transect_length: float = 1000.0
    # Mirrors arcpy CreateRoutes_lr's `coordinate_priority` -- which corner of
    # the bounding box the route/transect "starts" from, which controls the
    # sign/direction of along-transect distance.
    coordinate_priority: str = "UPPER_LEFT"
    professionals: list = field(default_factory=list)  # list[ProfessionalDelineation]
    # Spacing (site CRS units, usually meters) for the separate, denser
    # transect grid used by RunConfig.compute_rate_of_change's EPR/LRR
    # rate-of-change calculations (rate_of_change.py) -- independent of
    # transect_spacing, which drives the general-purpose transects.shp /
    # transect_distances_wide.csv outputs above. Defaults to 1m.
    rate_transect_spacing: float = 1.0


@dataclass
class RunConfig:
    """Top-level run configuration: which sites to process and which
    analysis stages to run for all of them. Built either directly (e.g. in
    tests) or via `load_config(path)`, which reads one of these from a YAML/
    JSON file. Passed to `pipeline.run_pipeline(run)`.
    """

    sites: list  # list[SiteConfig]
    output_dir: str = "output"
    target_crs: Optional[str] = None  # e.g. "EPSG:32616"; auto-UTM per site if None
    confidence_levels: list = field(default_factory=lambda: [0.05, 0.50, 0.90, 0.95])
    significance_threshold: float = 0.05  # T: Ps below this => statistically real change
    # "odb" (published), "perkal" (legacy), "both" (odb + perkal), or
    # "prob_change" (continuous probabilistic position/change-probability
    # surfaces -- see probability_surface.py, run on their own with nothing
    # else).
    epsilon_band_method: str = "odb"
    # Independent of epsilon_band_method: if True, also compute the
    # probabilistic position/change-probability surfaces (probability_surface.py)
    # *alongside* whatever epsilon_band_method produces -- e.g. set
    # epsilon_band_method: odb and compute_prob_change: true to get both the
    # ODB similarity_index/significant_change rasters AND the Gaussian
    # position-probability/change-probability rasters from the same run.
    # (epsilon_band_method: prob_change still works as a standalone shorthand
    # for "only prob_change, nothing else" without setting this flag.)
    compute_prob_change: bool = False
    # Length (site CRS units, usually meters) of the segments each shoreline
    # in a year pair is broken into for the change_probability_segments_*.shp
    # outputs, whose PROB_CHANGE attribute is the change_probability raster's
    # mean value sampled along that segment. Only used when prob_change
    # surfaces are computed (compute_prob_change or epsilon_band_method ==
    # "prob_change"). Defaults to 50m.
    prob_change_segment_length: float = 50.0
    # Independent of everything above: if True, also compute End Point Rate
    # (EPR) and Linear Regression Rate (LRR) shoreline change-rate statistics
    # (rate_of_change.py) along a separate, denser transect grid (see
    # SiteConfig.rate_transect_spacing). Defaults to False.
    compute_rate_of_change: bool = False
    export_intersect_geometries: bool = False
    raster_cell_size: float = 0.5  # grid cell size in target_crs units (usually meters)


_VALID_PRIORITIES = {"UPPER_LEFT", "UPPER_RIGHT", "LOWER_LEFT", "LOWER_RIGHT"}
_VALID_METHODS = {"odb", "perkal", "both", "prob_change"}


def _build_uncertainty(d: Optional[dict]) -> Optional[UncertaintyComponents]:
    """Build an UncertaintyComponents from a raw dict (the `uncertainty:`
    block under a shoreline year in the YAML/JSON config), or return None
    if that block is absent (e.g. when `rmse95_override` is used instead).
    """
    if d is None:
        return None
    return UncertaintyComponents(**d)


def _build_shoreline_year(d: dict) -> ShorelineYear:
    """Build one ShorelineYear from its raw dict under a site's
    `shorelines:` list, defaulting optional fields that are absent."""
    return ShorelineYear(
        year=int(d["year"]),
        path=d["path"],
        uncertainty=_build_uncertainty(d.get("uncertainty")),
        rmse95_override=d.get("rmse95_override"),
        acquisition_date=d.get("acquisition_date"),
    )


def _build_professional(d: dict) -> ProfessionalDelineation:
    """Build one ProfessionalDelineation from its raw dict under a site's
    `professionals:` list."""
    return ProfessionalDelineation(name=d["name"], year=int(d["year"]), path=d["path"])


def _build_site(d: dict) -> SiteConfig:
    """Build one SiteConfig from its raw dict under the top-level `sites:`
    list, applying the same defaults as the SiteConfig dataclass itself
    (so behavior is identical whether a SiteConfig is built directly in
    Python or loaded from a config file)."""
    return SiteConfig(
        name=d["name"],
        shorelines=[_build_shoreline_year(s) for s in d["shorelines"]],
        baseline=d.get("baseline"),
        transect_spacing=float(d.get("transect_spacing", 50.0)),
        transect_length=float(d.get("transect_length", 1000.0)),
        coordinate_priority=d.get("coordinate_priority", "UPPER_LEFT"),
        professionals=[_build_professional(p) for p in d.get("professionals", [])],
        rate_transect_spacing=float(d.get("rate_transect_spacing", 1.0)),
    )


def load_config(path: str | Path) -> RunConfig:
    """Load a YAML (.yaml/.yml) or JSON (.json) run configuration file."""
    path = Path(path)
    text = path.read_text()
    if path.suffix.lower() in (".yaml", ".yml"):
        raw = yaml.safe_load(text)
    elif path.suffix.lower() == ".json":
        raw = json.loads(text)
    else:
        raise ValueError(f"Unsupported config file extension: {path.suffix}")

    run = RunConfig(
        sites=[_build_site(s) for s in raw["sites"]],
        output_dir=raw.get("output_dir", "output"),
        target_crs=raw.get("target_crs"),
        confidence_levels=raw.get("confidence_levels", [0.05, 0.50, 0.90, 0.95]),
        significance_threshold=raw.get("significance_threshold", 0.05),
        epsilon_band_method=raw.get("epsilon_band_method", "odb"),
        compute_prob_change=raw.get("compute_prob_change", False),
        prob_change_segment_length=raw.get("prob_change_segment_length", 50.0),
        compute_rate_of_change=raw.get("compute_rate_of_change", False),
        export_intersect_geometries=raw.get("export_intersect_geometries", False),
        raster_cell_size=raw.get("raster_cell_size", 0.5),
    )
    validate_config(run)
    return run


def validate_config(run: RunConfig) -> None:
    """Raise ValueError on the first structural problem found in `run`:
    missing sites, an unrecognized epsilon_band_method, non-positive
    prob_change_segment_length or rate_transect_spacing, too few/duplicate
    shoreline years for a site, a bad coordinate_priority, or a shoreline
    year with neither `rmse95_override` nor `uncertainty` components set.
    Called automatically by `load_config`; callers building a RunConfig by
    hand should call this themselves before passing it to run_pipeline.
    """
    if not run.sites:
        raise ValueError("Config must define at least one site under 'sites'.")
    if run.epsilon_band_method not in _VALID_METHODS:
        raise ValueError(f"epsilon_band_method must be one of {_VALID_METHODS}")
    if run.prob_change_segment_length <= 0:
        raise ValueError("prob_change_segment_length must be > 0")
    for site in run.sites:
        if len(site.shorelines) < 2:
            raise ValueError(f"Site '{site.name}' needs at least 2 shoreline years.")
        years = [s.year for s in site.shorelines]
        if len(years) != len(set(years)):
            raise ValueError(f"Site '{site.name}' has duplicate years: {years}")
        if site.coordinate_priority not in _VALID_PRIORITIES:
            raise ValueError(
                f"Site '{site.name}' coordinate_priority must be one of {_VALID_PRIORITIES}"
            )
        if site.rate_transect_spacing <= 0:
            raise ValueError(f"Site '{site.name}' rate_transect_spacing must be > 0")
        for sy in site.shorelines:
            if sy.rmse95_override is None and sy.uncertainty is None:
                raise ValueError(
                    f"Site '{site.name}' year {sy.year} needs either 'rmse95_override' "
                    "or 'uncertainty' components defined."
                )
            if sy.acquisition_date is not None:
                try:
                    datetime.strptime(sy.acquisition_date, "%Y-%m-%d")
                except ValueError:
                    raise ValueError(
                        f"Site '{site.name}' year {sy.year} has acquisition_date "
                        f"'{sy.acquisition_date}', which must be in 'YYYY-MM-DD' format."
                    ) from None
