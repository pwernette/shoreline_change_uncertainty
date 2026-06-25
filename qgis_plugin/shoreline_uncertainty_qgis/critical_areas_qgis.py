"""QGIS-native port of shoreline_uncertainty/critical_areas.py.

Identify and export shoreline segments experiencing significant change.

Replaces original_program/arcgis_pro/Identify_Critical_Areas.py, which reused
perkal_bands.py's iterative buffer-growth algorithm but additionally exported
the final intersected ("critical") shoreline segment for each from-year/
to-year/confidence-level combination -- i.e. the portion of the adjacent
shoreline that fell inside the grown buffer once growth stopped.

Unlike epsilon_bands_qgis.run_perkal_for_site (which tests every ordered pair
year != k), Identify_Critical_Areas.py only tested year < k pairs; that
asymmetry is preserved here.

Ported onto `qgis.core.QgsGeometry`/`QgsVectorLayer` instead of shapely/
geopandas: the critical-segments output is assembled via
io_utils_qgis.build_memory_layer (a QgsVectorLayer) instead of a
GeoDataFrame.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd
from qgis.core import QgsField, QgsGeometry, QgsVectorLayer
from tqdm import tqdm

from .epsilon_bands_qgis import grow_buffer_to_threshold
from .geometry_utils_qgis import vertex_nearest_stats
from .io_utils_qgis import _to_qgis_crs, build_memory_layer


def identify_critical_areas(
    site_name: str,
    shorelines_by_year: Dict[int, QgsGeometry],
    confidence_levels: List[float],
    *,
    crs,
    step: float = 0.5,
    export_table: bool = True,
    progress: bool = True,
) -> Tuple[pd.DataFrame, QgsVectorLayer]:
    """For every (year < k) pair at every confidence level, grow a buffer
    around `year`'s shoreline until it captures `confidence_level` of `k`'s
    shoreline length, then record the final intersected segment as a
    'critical area' -- the portion of shoreline distinguishing real change
    at that confidence level.

    `crs` may be an `EPSG:1234`-style string, a bare int/numeral string, or
    an already-built `QgsCoordinateReferenceSystem` (normalized via
    io_utils_qgis._to_qgis_crs).

    Returns (summary_table, critical_segments_layer).
    """
    qgis_crs = crs if hasattr(crs, "authid") else _to_qgis_crs(crs)
    years = sorted(shorelines_by_year)
    combos = [
        (confidence_level, year, k)
        for confidence_level in confidence_levels
        for year in years
        for k in years
        if k > year
    ]
    rows = []
    segment_geoms: List[QgsGeometry] = []
    segment_attrs: List[Tuple] = []
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
        final_buf = shoreline.buffer(bufdist, 8)
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
        if not intersected.isEmpty():
            segment_geoms.append(intersected)
            segment_attrs.append((site_name, year, k, pct))

    summary = pd.DataFrame(rows)
    segments_layer = build_memory_layer(
        geometries=segment_geoms,
        fields=[QgsField("SITE"), QgsField("FROM_YEAR"), QgsField("TO_YEAR"), QgsField("PCT")],
        attributes=segment_attrs,
        geometry_kind="LineString",
        crs=qgis_crs,
        name="critical_areas",
    )
    return summary, segments_layer
