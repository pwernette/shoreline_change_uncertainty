"""Compare independently-delineated ('professional') shorelines against each
other and against a primary analyst's shoreline.

Replaces original_program/arcgis_pro/professional_comparison.py. The
original used FeatureVerticesToPoints_management + Near_analysis +
Statistics_analysis to get min/mean/max nearest-vertex distance between two
shorelines; the same statistic is computed directly here via
geometry_utils.vertex_nearest_stats (shapely under the hood).
"""
from __future__ import annotations

from typing import Dict

import pandas as pd
from shapely.geometry.base import BaseGeometry
from tqdm import tqdm

from .geometry_utils import vertex_nearest_stats


def compare_to_professionals(
    site_name: str,
    year: int,
    primary_shoreline: BaseGeometry,
    professional_shorelines: Dict[str, BaseGeometry],
    *,
    progress: bool = True,
) -> pd.DataFrame:
    """Compare `primary_shoreline` to each professional's delineation for one
    site/year, mirroring the '_meTOprof' table."""
    rows = []
    items = list(professional_shorelines.items())
    for name, geom in tqdm(items, desc=f"{site_name} {year}: vs. professionals", disable=not progress, leave=False):
        stats = vertex_nearest_stats(primary_shoreline, geom)
        rows.append({
            "SITE": site_name, "YEAR": year, "FROM": "PRIMARY", "TO_PROF": name,
            "MIN_DIST": stats.min_dist, "MEAN_DIST": stats.mean_dist, "MAX_DIST": stats.max_dist,
        })
    return pd.DataFrame(rows)


def compare_professionals_pairwise(
    site_name: str, year: int, professional_shorelines: Dict[str, BaseGeometry], *, progress: bool = True
) -> pd.DataFrame:
    """All ordered pairs (from_prof != to_prof) of professional delineations
    for one site/year, mirroring the '_profTOprof' table."""
    names = list(professional_shorelines)
    pairs = [(a, b) for a in names for b in names if a != b]
    rows = []
    for from_name, to_name in tqdm(
        pairs, desc=f"{site_name} {year}: professional pairs", disable=not progress, leave=False
    ):
        stats = vertex_nearest_stats(professional_shorelines[from_name], professional_shorelines[to_name])
        rows.append({
            "SITE": site_name, "YEAR": year, "FROM_PROF": from_name, "TO_PROF": to_name,
            "MIN_DIST": stats.min_dist, "MEAN_DIST": stats.mean_dist, "MAX_DIST": stats.max_dist,
        })
    return pd.DataFrame(rows)


def professional_summary(pairwise_df: pd.DataFrame) -> pd.DataFrame:
    """Mean MEAN_DIST per (FROM_PROF, TO_PROF, YEAR), mirroring the running
    '_professional_summary' table in professional_comparison.py."""
    if pairwise_df is None or pairwise_df.empty:
        return pd.DataFrame(columns=["FROM_PROF", "TO_PROF", "YEAR", "MEAN_DIST"])
    return (
        pairwise_df.groupby(["FROM_PROF", "TO_PROF", "YEAR"], as_index=False)["MEAN_DIST"]
        .mean()
    )
