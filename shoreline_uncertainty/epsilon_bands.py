"""Positional-uncertainty significance testing for shoreline change.

Two methods are ported from original_program/arcgis_pro:

1. Overlapping Double Buffer (ODB) -- the PUBLISHED method from Wernette et
   al. (2017), ported from intersecting_epsilon_bands.py /
   intersecting_epsilon_bands_2017_UPDATE.py. Buffer each shoreline by its
   RMSE95 positional uncertainty, then compute the proportion of similarity:

       Ps = Area(buffer_a INTERSECT buffer_b) / Area(buffer_a UNION buffer_b)

   A LOW Ps means the two uncertainty buffers barely overlap -- the
   shorelines are distinguishable beyond their combined positional
   uncertainty, i.e. the observed change is statistically "real." A HIGH Ps
   means the buffers mostly overlap -- the apparent change cannot be
   distinguished from positional uncertainty/noise. `significant_change` is
   therefore `True` when `prop_ab_overlap < threshold` (the user-defined
   significance threshold T from the paper).

2. Iterative buffer-growth ("Perkal-style" legacy method) -- an UNPUBLISHED
   alternative ported from perkal_bands.py. Grows a buffer around one
   shoreline until it captures a confidence-level-defined proportion of an
   adjacent shoreline's length, and reports the resulting radius plus
   vertex-to-shoreline distance statistics. Kept here for completeness and
   side-by-side comparison -- it is NOT the method described in the
   published paper.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import pandas as pd
from shapely.geometry.base import BaseGeometry
from tqdm import tqdm

from .geometry_utils import vertex_nearest_stats

# ---------------------------------------------------------------------------
# Method 1: Overlapping Double Buffer (ODB) -- published method (Eq. 4)
# ---------------------------------------------------------------------------


@dataclass
class ODBResult:
    """Result of one Overlapping Double Buffer comparison between two
    shoreline years: the two RMSE95 buffer polygons, their intersection,
    the resulting areas/overlap proportion (Ps, Eq. 4), and the
    significance verdict (`significant_change = Ps < threshold`). Geometry
    fields (`buffer_a`/`buffer_b`/`intersection`) are kept on the object so
    `raster_output.build_similarity_surface` can rasterize them directly
    without recomputing buffers."""

    site: str
    year_a: int
    year_b: int
    area_a: float
    area_b: float
    area_ab_overlap: float
    prop_ab_overlap: float
    area_ab_total: float
    significant_change: bool
    buffer_a: BaseGeometry
    buffer_b: BaseGeometry
    intersection: BaseGeometry


def overlapping_double_buffer(
    geom_a: BaseGeometry,
    radius_a: float,
    geom_b: BaseGeometry,
    radius_b: float,
    *,
    site: str = "",
    year_a: int = 0,
    year_b: int = 0,
    threshold: float = 0.05,
) -> ODBResult:
    """Core ODB computation for a single shoreline pair (Eq. 4, Wernette et al. 2017)."""
    buffer_a = geom_a.buffer(radius_a)
    buffer_b = geom_b.buffer(radius_b)
    area_a = buffer_a.area
    area_b = buffer_b.area
    intersection = buffer_a.intersection(buffer_b)
    union = buffer_a.union(buffer_b)
    area_ab = intersection.area
    area_union = union.area
    prop_ab = (area_ab / area_union) if area_union else 0.0
    return ODBResult(
        site=site,
        year_a=year_a,
        year_b=year_b,
        area_a=area_a,
        area_b=area_b,
        area_ab_overlap=area_ab,
        prop_ab_overlap=prop_ab,
        area_ab_total=area_union,
        significant_change=prop_ab < threshold,
        buffer_a=buffer_a,
        buffer_b=buffer_b,
        intersection=intersection,
    )


def run_odb_for_site(
    site_name: str,
    shorelines_by_year: Dict[int, BaseGeometry],
    radii_by_year: Dict[int, float],
    *,
    threshold: float = 0.05,
    progress: bool = True,
) -> pd.DataFrame:
    """Run the ODB method across every (year_a < year_b) pair for one site.

    Returns a DataFrame matching the original OverlappingBufferTable schema
    (SITE | YEAR_A | YEAR_B | AREA_A | AREA_B | AREA_AB_OVERLAP |
    PROP_AB_OVERLAP | AREA_AB_TOTAL), plus a SIGNIFICANT_CHANGE column.
    """
    years = sorted(shorelines_by_year)
    pairs = [(year_a, year_b) for i, year_a in enumerate(years) for year_b in years[i + 1:]]
    rows = []
    for year_a, year_b in tqdm(pairs, desc=f"{site_name}: ODB year pairs", disable=not progress, leave=False):
        r = overlapping_double_buffer(
            shorelines_by_year[year_a], radii_by_year[year_a],
            shorelines_by_year[year_b], radii_by_year[year_b],
            site=site_name, year_a=year_a, year_b=year_b, threshold=threshold,
        )
        rows.append({
            "SITE": r.site,
            "YEAR_A": r.year_a,
            "YEAR_B": r.year_b,
            "AREA_A": r.area_a,
            "AREA_B": r.area_b,
            "AREA_AB_OVERLAP": r.area_ab_overlap,
            "PROP_AB_OVERLAP": r.prop_ab_overlap,
            "AREA_AB_TOTAL": r.area_ab_total,
            "SIGNIFICANT_CHANGE": r.significant_change,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Method 2: Iterative buffer-growth ("Perkal-style") -- legacy/alternative
# ---------------------------------------------------------------------------


@dataclass
class PerkalResult:
    """Result of one legacy iterative buffer-growth comparison: the buffer
    radius needed around `from_year`'s shoreline to capture `confidence_level`
    of `to_year`'s shoreline length, plus vertex-to-shoreline distance
    statistics and how many growth iterations it took to converge. Not
    currently constructed directly (run_perkal_for_site builds its output
    rows as plain dicts) -- kept as the typed/documented counterpart to
    ODBResult and as a stable structure for callers who want one."""

    site: str
    from_year: int
    to_year: int
    confidence_level: float
    min_dist: float
    mean_dist: float
    max_dist: float
    threshold: float
    buffer_radius: float
    obs_length: float
    iterations: int


def grow_buffer_to_threshold(
    shoreline: BaseGeometry,
    adjacent_shoreline: BaseGeometry,
    confidence_level: float,
    *,
    step: float = 0.5,
    max_iterations: int = 10_000,
) -> Tuple[float, float, float, int]:
    """Iteratively grow a buffer around `shoreline` until it captures at
    least `confidence_level` proportion of `adjacent_shoreline`'s length,
    mirroring the while-loop in perkal_bands.py.

    Returns (buffer_radius, threshold, observed_length, iterations).
    """
    threshold = confidence_level * adjacent_shoreline.length
    min_dist = vertex_nearest_stats(shoreline, adjacent_shoreline).min_dist
    bufdist = min_dist if min_dist != 0 else step
    obs_length = 0.0
    iterations = 0
    while obs_length < threshold:
        buf = shoreline.buffer(bufdist)
        intersected = adjacent_shoreline.intersection(buf)
        obs_length = intersected.length
        if obs_length < threshold:
            bufdist += step
        iterations += 1
        if iterations >= max_iterations:
            raise RuntimeError(
                f"grow_buffer_to_threshold did not converge after {max_iterations} "
                f"iterations (bufdist={bufdist}, obs_length={obs_length}, threshold={threshold})."
            )
    return bufdist, threshold, obs_length, iterations


def run_perkal_for_site(
    site_name: str,
    shorelines_by_year: Dict[int, BaseGeometry],
    confidence_levels: List[float],
    *,
    step: float = 0.5,
    progress: bool = True,
) -> pd.DataFrame:
    """Run the legacy iterative buffer-growth method for every ordered pair
    of years (year != k) at every confidence level, mirroring
    perkal_bands.py's full loop structure (every from/to direction, not just
    year < k)."""
    years = sorted(shorelines_by_year)
    combos = [
        (confidence_level, year, k)
        for confidence_level in confidence_levels
        for year in years
        for k in years
        if k != year
    ]
    rows = []
    for confidence_level, year, k in tqdm(
        combos, desc=f"{site_name}: Perkal buffer growth", disable=not progress, leave=False
    ):
        shoreline = shorelines_by_year[year]
        adjacent = shorelines_by_year[k]
        stats = vertex_nearest_stats(shoreline, adjacent)
        bufdist, threshold, obs_length, iterations = grow_buffer_to_threshold(
            shoreline, adjacent, confidence_level, step=step
        )
        rows.append({
            "SITE": site_name,
            "CONFIDENCE_LEVEL": confidence_level,
            "FROM_YEAR": year,
            "TO_YEAR": k,
            "MIN_DIST": stats.min_dist,
            "MEAN_DIST": stats.mean_dist,
            "MAX_DIST": stats.max_dist,
            "THRESHOLD": threshold,
            "BUFFER_RADIUS": bufdist,
            "OBS_LENGTH": obs_length,
            "ITERATIONS": iterations,
        })
    return pd.DataFrame(rows)
