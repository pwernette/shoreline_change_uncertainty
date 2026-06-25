"""QGIS-native port of shoreline_uncertainty/geometry_utils.py.

Same shared geometry helpers (vertex-to-nearest-line distance stats, and
dissolve/union) used by epsilon_bands_qgis, critical_areas_qgis, and
comparison_qgis -- but built on `qgis.core.QgsGeometry` instead of shapely.
QgsGeometry's actual buffer/union/intersection/distance math is backed by
GEOS internally (the same engine shapely wraps), so the numeric behavior is
the same; only the API surface changes.

Mirrors arcpy's FeatureVerticesToPoints_management(..., 'ALL') +
Near_analysis + Statistics_analysis, same as the original module.
"""
from __future__ import annotations

import math
from typing import Iterable, List, NamedTuple

from qgis.core import QgsGeometry, QgsPointXY, QgsWkbTypes


def extract_vertices(geom: QgsGeometry) -> List[QgsPointXY]:
    """Extract every vertex of a (multi)line or polygon geometry as
    QgsPointXY objects, mirroring
    arcpy's FeatureVerticesToPoints_management(..., 'ALL')."""
    if geom is None or geom.isNull() or geom.isEmpty():
        return []

    geom_type = QgsWkbTypes.geometryType(geom.wkbType())

    if geom_type == QgsWkbTypes.PolygonGeometry:
        rings = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
        pts: List[QgsPointXY] = []
        for polygon in rings:
            for ring in polygon:
                pts.extend(ring)
        return pts

    # LineGeometry (and PointGeometry, trivially)
    if geom.isMultipart():
        parts = geom.asMultiPolyline()
        pts = []
        for part in parts:
            pts.extend(part)
        return pts
    if geom_type == QgsWkbTypes.PointGeometry:
        return [geom.asPoint()]
    return list(geom.asPolyline())


class NearStats(NamedTuple):
    """Min/mean/max distance from every vertex of one line to another
    geometry, as returned by `vertex_nearest_stats` -- mirrors the summary
    columns produced by arcpy's Near_analysis + Statistics_analysis combo."""

    min_dist: float
    mean_dist: float
    max_dist: float


def vertex_nearest_stats(line: QgsGeometry, other: QgsGeometry) -> NearStats:
    """For every vertex of `line`, compute the nearest distance to `other`.
    Returns min/mean/max, mirroring
    FeatureVerticesToPoints + Near_analysis + Statistics_analysis."""
    verts = extract_vertices(line)
    if not verts:
        raise ValueError("Input line has no vertices.")
    dists = [QgsGeometry.fromPointXY(p).distance(other) for p in verts]
    return NearStats(min(dists), sum(dists) / len(dists), max(dists))


def dissolve(geoms: Iterable[QgsGeometry]) -> QgsGeometry:
    """Union/dissolve a collection of geometries into one, mirroring
    Buffer_analysis(..., dissolve_option='ALL'). Uses QgsGeometry's own
    unaryUnion (GEOS-backed, same as shapely.ops.unary_union)."""
    geom_list = [g for g in geoms if g is not None and not g.isNull()]
    if not geom_list:
        return QgsGeometry()
    return QgsGeometry.unaryUnion(geom_list)


def substring(line: QgsGeometry, start_distance: float, end_distance: float) -> QgsGeometry:
    """Extract the portion of `line` between `start_distance` and
    `end_distance` (measured along the line from its first vertex),
    mirroring shapely.ops.substring -- used by
    probability_surface_qgis.segment_line to cut a shoreline into fixed-
    length pieces.

    Implemented via vertex-walking + `interpolate()`/`asPolyline()` rather
    than a single QgsGeometry/QgsCurve API call, since a guaranteed
    curve-substring method (`QgsCurve.curveSubstring`) isn't available
    across the whole supported QGIS version range (3.16+); this version
    only relies on `interpolate`, `asPolyline`, and `fromPolylineXY`, all
    already used elsewhere in this plugin.

    Returns an empty QgsGeometry if `end_distance <= start_distance` (after
    clamping both to [0, line.length()])."""
    coords = line.asPolyline()
    if len(coords) < 2:
        return QgsGeometry()
    pts = [(p.x(), p.y()) for p in coords]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    total = cum[-1]
    d0 = max(0.0, min(start_distance, total))
    d1 = max(0.0, min(end_distance, total))
    if d1 <= d0:
        return QgsGeometry()

    out_pts: List[QgsPointXY] = [line.interpolate(d0).asPoint()]
    for i, d in enumerate(cum):
        if d0 < d < d1:
            out_pts.append(QgsPointXY(*pts[i]))
    out_pts.append(line.interpolate(d1).asPoint())
    return QgsGeometry.fromPolylineXY(out_pts)
