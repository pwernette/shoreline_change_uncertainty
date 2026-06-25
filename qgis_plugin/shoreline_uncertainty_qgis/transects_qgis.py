"""QGIS-native port of shoreline_uncertainty/transects.py.

Replaces, in combination, the same original arcpy scripts the standalone
module replaces (Cast_Transects.py, extract_intersected_points.py,
transect_analysis.py, merge_results.py) -- just built on `qgis.core`
instead of geopandas/shapely:

  - `compute_baseline_direction` reads vertices via QgsVectorLayer +
    geometry_utils_qgis.extract_vertices instead of iterating a
    GeoDataFrame's geometry column directly.
  - Transect/baseline geometries are QgsGeometry instead of shapely
    LineString.
  - `QgsGeometry.interpolate(distance)` takes an absolute distance along
    the line (unlike shapely's `interpolate(0.5, normalized=True)`), so
    `_to_points` multiplies by `geom.length()` to get the same "midpoint of
    this intersection segment" behavior.
  - `QgsGeometry.asGeometryCollection()` decomposes any geometry (Point,
    MultiPoint, LineString, MultiLineString, or a mixed GeometryCollection)
    into single-part `QgsGeometry` pieces, replacing shapely's per-geom-type
    branching in the original `_to_points`.

Transects measure DIRECTION and MAGNITUDE of shoreline change only -- they
carry no information about statistical significance. Pair with
epsilon_bands_qgis.py for the significance test.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from qgis.core import QgsField, QgsGeometry, QgsPointXY, QgsVectorLayer, QgsWkbTypes
from tqdm import tqdm

from .geometry_utils_qgis import extract_vertices
from .io_utils_qgis import build_memory_layer, layer_geometries


def compute_baseline_direction(layer: QgsVectorLayer) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Dominant shoreline orientation via PCA/SVD on all shoreline vertices.
    Returns (centroid_xy, unit_direction_vector)."""
    pts: List[Tuple[float, float]] = []
    for geom in layer_geometries(layer):
        for v in extract_vertices(geom):
            pts.append((v.x(), v.y()))
    pts = np.array(pts)
    if len(pts) < 2:
        raise ValueError("Not enough points to determine shoreline orientation.")
    mean = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
    direction = vt[0, :2]
    direction = direction / np.linalg.norm(direction)
    return (mean[0], mean[1]), (float(direction[0]), float(direction[1]))


def build_baseline(center, direction, length: float) -> QgsGeometry:
    """Construct a straight baseline line of total `length`, centered on
    `center` and oriented along unit `direction` -- the auto-generated
    baseline used when a site has no explicit baseline shapefile, built
    from `compute_baseline_direction`'s PCA fit through the shoreline
    vertices."""
    cx, cy = center
    dx, dy = direction
    half = length / 2.0
    return QgsGeometry.fromPolylineXY([
        QgsPointXY(cx - dx * half, cy - dy * half),
        QgsPointXY(cx + dx * half, cy + dy * half),
    ])


def baseline_center_direction(baseline: QgsGeometry) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Center point and unit direction vector of a baseline line, regardless
    of whether it came from an explicit baseline shapefile or from
    compute_baseline_direction/build_baseline -- used by
    probability_surface_qgis.py to get a consistent baseline-relative sign
    convention for distances to a shoreline, mirroring the role
    coordinate_priority plays for along-transect distance."""
    coords = baseline.asPolyline()
    if len(coords) < 2:
        raise ValueError("Baseline has zero length.")
    p0 = np.array([coords[0].x(), coords[0].y()])
    p1 = np.array([coords[-1].x(), coords[-1].y()])
    center = tuple((p0 + p1) / 2.0)
    vec = p1 - p0
    length = np.linalg.norm(vec)
    if length == 0:
        raise ValueError("Baseline has zero length.")
    direction = tuple(vec / length)
    return center, direction


def _corner_key(coord: Tuple[float, float], priority: str):
    """Sort key for `coord` under a given `coordinate_priority` corner: the
    coordinate that sorts lowest under this key is the one closest to that
    corner of the bounding box, so `order_transect_start` can pick whichever
    endpoint should be the transect's start. Mirrors arcpy
    CreateRoutes_lr's four coordinate_priority options."""
    x, y = coord
    return {
        "UPPER_LEFT": (x, -y),
        "UPPER_RIGHT": (-x, -y),
        "LOWER_LEFT": (x, y),
        "LOWER_RIGHT": (-x, y),
    }[priority]


def order_transect_start(line: QgsGeometry, coordinate_priority: str = "UPPER_LEFT") -> QgsGeometry:
    """Orient a transect so its start point matches the given corner
    priority, mirroring arcpy CreateRoutes_lr's `coordinate_priority`
    parameter -- this keeps the sign/direction of along-transect distance
    consistent across a whole site, regardless of vertex order in the input
    shapefile."""
    coords = line.asPolyline()
    p0, p1 = (coords[0].x(), coords[0].y()), (coords[-1].x(), coords[-1].y())
    if _corner_key(p0, coordinate_priority) <= _corner_key(p1, coordinate_priority):
        return line
    return QgsGeometry.fromPolylineXY([QgsPointXY(*p1), QgsPointXY(*p0)])


@dataclass
class Transect:
    """One shore-normal transect: its sequential ID along the baseline, its
    line geometry (oriented per coordinate_priority), and the point on the
    baseline it was generated from."""

    transect_id: int
    geometry: QgsGeometry
    baseline_point: tuple


def generate_transects(
    baseline: QgsGeometry,
    spacing: float,
    transect_length: float,
    coordinate_priority: str = "UPPER_LEFT",
    *,
    progress: bool = True,
) -> List[Transect]:
    """Generate shore-normal transects at regular `spacing` along `baseline`,
    each of total length `transect_length`, oriented per `coordinate_priority`."""
    coords = baseline.asPolyline()
    p_start = np.array([coords[0].x(), coords[0].y()])
    p_end = np.array([coords[-1].x(), coords[-1].y()])
    vec = p_end - p_start
    total_len = math.hypot(*vec)
    if total_len == 0:
        raise ValueError("Baseline has zero length.")
    unit = vec / total_len
    perp = np.array([-unit[1], unit[0]])

    n_steps = max(1, int(math.floor(total_len / spacing)))
    half = transect_length / 2.0
    transects = []
    for i in tqdm(range(n_steps + 1), desc="Generating transects", disable=not progress, leave=False):
        t = i / n_steps
        base_pt = p_start + (p_end - p_start) * t
        p1 = base_pt - perp * half
        p2 = base_pt + perp * half
        line = order_transect_start(
            QgsGeometry.fromPolylineXY([QgsPointXY(*p1), QgsPointXY(*p2)]), coordinate_priority
        )
        transects.append(Transect(transect_id=i, geometry=line, baseline_point=tuple(base_pt)))
    return transects


def _to_points(geom: QgsGeometry) -> List[QgsGeometry]:
    """Normalize the result of a transect/shoreline `.intersection()` call
    into a flat list of single-point QgsGeometry objects, regardless of
    which geometry type the intersection returned. A transect crossing a
    shoreline cleanly gives Point(s) directly; a transect running briefly
    collinear with the shoreline gives LineString/MultiLineString segments
    instead, which are reduced here to their midpoints so
    `intersect_transects_shorelines` always has point candidates to pick
    the closest one from. `asGeometryCollection()` decomposes any of
    Point/MultiPoint/LineString/MultiLineString/mixed-GeometryCollection
    into single-part pieces uniformly."""
    if geom is None or geom.isEmpty():
        return []
    parts = geom.asGeometryCollection()
    points: List[QgsGeometry] = []
    for part in parts:
        geom_type = QgsWkbTypes.geometryType(part.wkbType())
        if geom_type == QgsWkbTypes.PointGeometry:
            points.append(part)
        elif geom_type == QgsWkbTypes.LineGeometry:
            points.append(part.interpolate(0.5 * part.length()))
    return points


def intersect_transects_shorelines(
    transects: List[Transect], shorelines_by_year: Dict[int, QgsGeometry], *, progress: bool = True
) -> pd.DataFrame:
    """Intersect every transect with every year's shoreline.

    Returns a long table: TRANSECT_ID | YEAR | DISTANCE | X | Y -- DISTANCE
    is measured from the transect's start point (set by
    `coordinate_priority`), mirroring arcpy's LocateFeaturesAlongRoutes_lr
    'MEAS' output. Where a transect crosses a shoreline more than once, the
    closest intersection to the transect start is kept (mirroring
    LocateFeaturesAlongRoutes_lr's default "FIRST" match behavior).
    """
    rows = []
    for transect in tqdm(transects, desc="Intersecting transects x shorelines", disable=not progress, leave=False):
        start_xy = transect.geometry.asPolyline()[0]
        start = QgsGeometry.fromPointXY(start_xy)
        for year, shoreline in shorelines_by_year.items():
            inter = transect.geometry.intersection(shoreline)
            if inter.isEmpty():
                continue
            points = _to_points(inter)
            if not points:
                continue
            closest = min(points, key=lambda p: start.distance(p))
            closest_xy = closest.asPoint()
            rows.append({
                "TRANSECT_ID": transect.transect_id,
                "YEAR": year,
                "DISTANCE": start.distance(closest),
                "X": closest_xy.x(),
                "Y": closest_xy.y(),
            })
    return pd.DataFrame(rows)


def to_wide_table(long_table: pd.DataFrame) -> pd.DataFrame:
    """Pivot the long TRANSECT_ID|YEAR|DISTANCE table into one row per
    transect with a TO_<year> column per year -- the wide format
    Cast_Transects.py / merge_results.py were building toward (the original
    merge_results.py never finished this; it's a direct pivot here)."""
    if long_table.empty:
        return long_table
    wide = long_table.pivot(index="TRANSECT_ID", columns="YEAR", values="DISTANCE")
    wide.columns = [f"TO_{int(c)}" for c in wide.columns]
    return wide.reset_index()


def nearest_transect_net_distance(
    point: QgsGeometry,
    transects: List[Transect],
    wide_table: pd.DataFrame,
    year_a: int,
    year_b: int,
) -> float:
    """EPR-style signed net along-transect distance change
    (TO_<year_b> - TO_<year_a>, the same value/sign convention as
    rate_of_change_qgis.end_point_rate's EPR_NET_DISTANCE) at whichever
    transect in `transects` is geometrically closest to `point`.

    Lets callers attach a transect-anchored, erosion/accretion-consistent
    magnitude to an arbitrary point that doesn't necessarily fall exactly on
    any transect -- e.g. the midpoint of a probability_surface_qgis.py
    shoreline segment. This is deliberately *not* derived from
    probability_surface_qgis.signed_distance_raster: that raster's sign is a
    location-dependent baseline-side indicator (it flips depending on
    whether the sampled point sits near the older or the younger shoreline)
    and is not a reliable stand-in for "did this stretch of coast erode or
    accrete" -- whereas TO_<year> (and therefore its difference) carries a
    single, transect-global sign fixed by coordinate_priority, matching the
    convention already used for EPR_NET_DISTANCE/EPR_RATE/LRR_RATE.

    Returns NaN if `wide_table` is missing the nearest transect's row, or
    either TO_<year> column/value for that row.
    """
    nearest = min(transects, key=lambda t: point.distance(t.geometry))
    col_a, col_b = f"TO_{year_a}", f"TO_{year_b}"
    if col_a not in wide_table.columns or col_b not in wide_table.columns:
        return float("nan")
    row = wide_table.loc[wide_table["TRANSECT_ID"] == nearest.transect_id]
    if row.empty:
        return float("nan")
    val_a, val_b = row[col_a].iloc[0], row[col_b].iloc[0]
    if pd.isna(val_a) or pd.isna(val_b):
        return float("nan")
    return float(val_b - val_a)


def transects_to_layer(transects: List[Transect], crs) -> QgsVectorLayer:
    """Convert a list of Transect objects into a QgsVectorLayer (TRANSECT_ID
    + geometry, in `crs`) suitable for writing out as transects.shp via
    io_utils_qgis.write_vector."""
    return build_memory_layer(
        geometries=[t.geometry for t in transects],
        fields=[QgsField("TRANSECT_ID")],
        attributes=[(t.transect_id,) for t in transects],
        geometry_kind="LineString",
        crs=crs,
        name="transects",
    )
