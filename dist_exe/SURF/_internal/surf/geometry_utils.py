"""Shared geometry helpers used by epsilon_bands, critical_areas, and
comparison -- mainly the vertex-to-nearest-line distance statistic that the
original scripts computed via
FeatureVerticesToPoints_management(..., 'ALL') + Near_analysis + Statistics_analysis.
"""
from __future__ import annotations

from typing import Iterable, List, NamedTuple

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union


def extract_vertices(geom) -> List[Point]:
    """Extract every vertex of a (Multi)LineString as Point objects, mirroring
    arcpy's FeatureVerticesToPoints_management(..., 'ALL')."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [Point(c) for c in geom.coords]
    if isinstance(geom, MultiLineString):
        pts = []
        for part in geom.geoms:
            pts.extend(Point(c) for c in part.coords)
        return pts
    if hasattr(geom, "exterior") and geom.exterior is not None:
        return [Point(c) for c in geom.exterior.coords]
    return []


class NearStats(NamedTuple):
    """Min/mean/max distance from every vertex of one line to another
    geometry, as returned by `vertex_nearest_stats` -- mirrors the summary
    columns produced by arcpy's Near_analysis + Statistics_analysis combo."""

    min_dist: float
    mean_dist: float
    max_dist: float


def vertex_nearest_stats(line, other) -> NearStats:
    """For every vertex of `line`, compute the nearest distance to `other`.
    Returns min/mean/max, mirroring
    FeatureVerticesToPoints + Near_analysis + Statistics_analysis."""
    verts = extract_vertices(line)
    if not verts:
        raise ValueError("Input line has no vertices.")
    dists = np.array([p.distance(other) for p in verts])
    return NearStats(float(dists.min()), float(dists.mean()), float(dists.max()))


def dissolve(geoms: Iterable):
    """Union/dissolve a collection of geometries into one, mirroring
    Buffer_analysis(..., dissolve_option='ALL')."""
    return unary_union(list(geoms))
