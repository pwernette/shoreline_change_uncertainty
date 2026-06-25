"""Shore-normal transect generation and shoreline intersection.

Replaces, in combination:
  - Cast_Transects.py             (created the transects feature class + per-year TO_<year> fields)
  - extract_intersected_points.py (intersected shoreline x transects, logged XY)
  - transect_analysis.py          (linear-referenced distance along each transect, per year)
  - merge_results.py              (an incomplete original script; folding per-year
                                    distances into one wide table per transect is done
                                    directly here as a pivot)

Transects measure DIRECTION and MAGNITUDE of shoreline change only -- they
carry no information about statistical significance. Pair with
epsilon_bands.py for the significance test.

Baseline/transect generation builds on the geometry logic already prototyped
(arcpy-free) in original_program/arcgis_pro/shoreline_transects.ipynb.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from tqdm import tqdm


def compute_baseline_direction(gdf: gpd.GeoDataFrame):
    """Dominant shoreline orientation via PCA/SVD on all shoreline vertices.
    Returns (centroid_xy, unit_direction_vector)."""
    pts = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "LineString":
            pts.extend(geom.coords)
        elif geom.geom_type in ("MultiLineString", "GeometryCollection"):
            for part in geom.geoms:
                if hasattr(part, "coords"):
                    pts.extend(part.coords)
    pts = np.array(pts)[:, :2]
    if len(pts) < 2:
        raise ValueError("Not enough points to determine shoreline orientation.")
    mean = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
    direction = vt[0, :2]
    direction = direction / np.linalg.norm(direction)
    return (mean[0], mean[1]), (float(direction[0]), float(direction[1]))


def build_baseline(center, direction, length: float) -> LineString:
    """Construct a straight baseline LineString of total `length`, centered
    on `center` and oriented along unit `direction` -- the auto-generated
    baseline used when a site has no explicit baseline shapefile, built
    from `compute_baseline_direction`'s PCA fit through the shoreline
    vertices."""
    cx, cy = center
    dx, dy = direction
    half = length / 2.0
    return LineString([(cx - dx * half, cy - dy * half), (cx + dx * half, cy + dy * half)])


def baseline_center_direction(baseline: LineString):
    """Center point and unit direction vector of a baseline LineString,
    regardless of whether it came from an explicit baseline shapefile or
    from compute_baseline_direction/build_baseline -- used by
    probability_surface.py to get a consistent baseline-relative sign
    convention for distances to a shoreline, mirroring the role
    coordinate_priority plays for along-transect distance."""
    p0 = np.array(baseline.coords[0])
    p1 = np.array(baseline.coords[-1])
    center = tuple((p0 + p1) / 2.0)
    vec = p1 - p0
    length = np.linalg.norm(vec)
    if length == 0:
        raise ValueError("Baseline has zero length.")
    direction = tuple(vec / length)
    return center, direction


def _corner_key(coord, priority: str):
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


def order_transect_start(line: LineString, coordinate_priority: str = "UPPER_LEFT") -> LineString:
    """Orient a transect so its start point matches the given corner
    priority, mirroring arcpy CreateRoutes_lr's `coordinate_priority`
    parameter -- this keeps the sign/direction of along-transect distance
    consistent across a whole site, regardless of vertex order in the input
    shapefile."""
    p0, p1 = line.coords[0], line.coords[-1]
    if _corner_key(p0, coordinate_priority) <= _corner_key(p1, coordinate_priority):
        return line
    return LineString([p1, p0])


@dataclass
class Transect:
    """One shore-normal transect: its sequential ID along the baseline, its
    line geometry (oriented per coordinate_priority), and the point on the
    baseline it was generated from."""

    transect_id: int
    geometry: LineString
    baseline_point: tuple


def generate_transects(
    baseline: LineString,
    spacing: float,
    transect_length: float,
    coordinate_priority: str = "UPPER_LEFT",
    *,
    progress: bool = True,
) -> List[Transect]:
    """Generate shore-normal transects at regular `spacing` along `baseline`,
    each of total length `transect_length`, oriented per `coordinate_priority`."""
    p_start = np.array(baseline.coords[0])
    p_end = np.array(baseline.coords[-1])
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
        line = order_transect_start(LineString([p1, p2]), coordinate_priority)
        transects.append(Transect(transect_id=i, geometry=line, baseline_point=tuple(base_pt)))
    return transects


def _to_points(geom) -> List[Point]:
    """Normalize the result of a transect/shoreline `.intersection()` call
    into a flat list of Points, regardless of which geometry type shapely
    returned. A transect crossing a shoreline cleanly gives Point(s)
    directly; a transect running briefly collinear with the shoreline
    gives LineString/MultiLineString segments instead, which are reduced
    here to their midpoints so `intersect_transects_shorelines` always has
    point candidates to pick the closest one from."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Point":
        return [geom]
    if geom.geom_type == "MultiPoint":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(_to_points(g))
        return out
    if geom.geom_type == "LineString":
        return [geom.interpolate(0.5, normalized=True)]
    if geom.geom_type == "MultiLineString":
        return [seg.interpolate(0.5, normalized=True) for seg in geom.geoms]
    return []


def intersect_transects_shorelines(
    transects: List[Transect], shorelines_by_year: Dict[int, BaseGeometry], *, progress: bool = True
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
        start = Point(transect.geometry.coords[0])
        for year, shoreline in shorelines_by_year.items():
            inter = transect.geometry.intersection(shoreline)
            if inter.is_empty:
                continue
            points = _to_points(inter)
            if not points:
                continue
            closest = min(points, key=lambda p: start.distance(p))
            rows.append({
                "TRANSECT_ID": transect.transect_id,
                "YEAR": year,
                "DISTANCE": start.distance(closest),
                "X": closest.x,
                "Y": closest.y,
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
    point: Point,
    transects: List[Transect],
    wide_table: pd.DataFrame,
    year_a: int,
    year_b: int,
) -> float:
    """EPR-style signed net along-transect distance change
    (TO_<year_b> - TO_<year_a>, the same value/sign convention as
    rate_of_change.end_point_rate's EPR_NET_DISTANCE) at whichever transect
    in `transects` is geometrically closest to `point`.

    Lets callers attach a transect-anchored, erosion/accretion-consistent
    magnitude to an arbitrary point that doesn't necessarily fall exactly on
    any transect -- e.g. the midpoint of a probability_surface.py shoreline
    segment. This is deliberately *not* derived from
    probability_surface.signed_distance_raster: that raster's sign is a
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


def transects_to_gdf(transects: List[Transect], crs) -> gpd.GeoDataFrame:
    """Convert a list of Transect objects into a GeoDataFrame (TRANSECT_ID +
    geometry, in `crs`) suitable for writing out as transects.shp."""
    return gpd.GeoDataFrame(
        [{"TRANSECT_ID": t.transect_id, "geometry": t.geometry} for t in transects],
        geometry="geometry", crs=crs,
    )
