"""Identify and export shoreline segments experiencing significant change.

Replaces original_program/arcgis_pro/Identify_Critical_Areas.py, which reused
perkal_bands.py's iterative buffer-growth algorithm but additionally exported
the final intersected ("critical") shoreline segment for each from-year/
to-year/confidence-level combination -- i.e. the portion of the adjacent
shoreline that fell inside the grown buffer once growth stopped.

Unlike perkal_bands.py (which tests every ordered pair year != k),
Identify_Critical_Areas.py only tested year < k pairs; that asymmetry is
preserved here.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry
from tqdm import tqdm

from .epsilon_bands import grow_buffer_to_threshold
from .geometry_utils import vertex_nearest_stats


def identify_critical_areas(
    site_name: str,
    shorelines_by_year: Dict[int, BaseGeometry],
    confidence_levels: List[float],
    *,
    crs,
    step: float = 0.5,
    export_table: bool = True,
    progress: bool = True,
) -> Tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """For every (year < k) pair at every confidence level, grow a buffer
    around `year`'s shoreline until it captures `confidence_level` of `k`'s
    shoreline length, then record the final intersected segment as a
    'critical area' -- the portion of shoreline distinguishing real change
    at that confidence level.

    Returns (summary_table, critical_segments_gdf).
    """
    years = sorted(shorelines_by_year)
    combos = [
        (confidence_level, year, k)
        for confidence_level in confidence_levels
        for year in years
        for k in years
        if k > year
    ]
    rows = []
    segments = []
    for confidence_level, year, k in tqdm(
        combos, desc=f"{site_name}: critical areas", disable=not progress, leave=False
    ):
        pct = str(confidence_level).split(".")[-1]
        shoreline = shorelines_by_year[year]
        adjacent = shorelines_by_year[k]
        stats = vertex_nearest_stats(shoreline, adjacent)
        bufdist, threshold, obs_length, iterations = grow_buffer_to_threshold(
            shoreline, adjacent, confidence_level, step=step
        )
        final_buf = shoreline.buffer(bufdist)
        intersected = adjacent.intersection(final_buf)

        if export_table:
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
            })
        if not intersected.is_empty:
            segments.append({
                "SITE": site_name,
                "FROM_YEAR": year,
                "TO_YEAR": k,
                "PCT": pct,
                "geometry": intersected,
            })

    summary = pd.DataFrame(rows)
    segments_gdf = (
        gpd.GeoDataFrame(segments, geometry="geometry", crs=crs)
        if segments
        else gpd.GeoDataFrame(columns=["SITE", "FROM_YEAR", "TO_YEAR", "PCT", "geometry"], geometry="geometry", crs=crs)
    )
    return summary, segments_gdf
