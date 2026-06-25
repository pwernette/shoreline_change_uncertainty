"""QGIS-native port of shoreline_uncertainty/rate_of_change.py.

End Point Rate (EPR) and Linear Regression Rate (LRR) shoreline
change-rate statistics -- the standard DSAS (Digital Shoreline Analysis
System)-style companion metrics to the ODB significance test
(epsilon_bands_qgis.py) and the prob_change probability surfaces
(probability_surface_qgis.py) elsewhere in this plugin.

`_year_columns`, `end_point_rate`, `linear_regression_rate`, and
`compute_rate_of_change` operate purely on pandas/numpy/scipy.stats inputs
(a transects_qgis.to_wide_table-shaped DataFrame in, the same DataFrame
plus new columns out) -- there is no geometry involved at all, so these four
functions are reused verbatim from the standalone package; only the
module-level docstring/import list differs.

`build_rate_change_polygons` is the one function that touches geometry, so
it's the only one actually re-implemented here, on `qgis.core.QgsGeometry` +
`io_utils_qgis.build_memory_layer` instead of shapely + geopandas:
  - `transect.geometry.interpolate(distance)` takes an absolute distance
    along the line under both APIs (shapely's only by explicitly passing
    `normalized=False`, which is shapely's *default* anyway -- see
    transects_qgis.py's module docstring), so the call site is unchanged;
    QGIS's version returns a QgsGeometry, so each call is followed by
    `.asPoint()` to get plain (x, y) coordinates for the QgsPointXY ring
    below.
  - `shapely.geometry.Polygon(...)` -> `QgsGeometry.fromPolygonXY([[...]])`.
  - `polygon.is_valid` / `polygon.buffer(0)` -> `polygon.isGeosValid()` /
    `polygon.makeValid()` (QGIS's own GEOS-backed equivalents, available
    since QGIS 3.0).
  - The output GeoDataFrame becomes a QgsVectorLayer, built via
    `io_utils_qgis.build_memory_layer` like every other vector-producing
    ported module.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
from qgis.core import QgsCoordinateReferenceSystem, QgsField, QgsGeometry, QgsPointXY
from scipy import stats

from .io_utils_qgis import _to_qgis_crs, build_memory_layer
from .probability_surface_qgis import gaussian_overlap_probability
from .transects_qgis import Transect


def _year_columns(wide_table: pd.DataFrame) -> List[int]:
    """Extract and sort the shoreline years present as TO_<year> columns in
    a transects_qgis.to_wide_table table (e.g. ["TO_1938", "TO_2010"] ->
    [1938, 2010]), used by both end_point_rate and linear_regression_rate to
    find the oldest/youngest years and the full set of years to regress
    over."""
    return sorted(int(c.split("_", 1)[1]) for c in wide_table.columns if c.startswith("TO_"))


def end_point_rate(wide_table: pd.DataFrame) -> pd.DataFrame:
    """Add EPR_NET_DISTANCE and EPR_RATE columns to a
    transects_qgis.to_wide_table table, using only the oldest and youngest
    TO_<year> columns present."""
    years = _year_columns(wide_table)
    if len(years) < 2:
        raise ValueError("end_point_rate needs at least 2 shoreline years.")
    oldest, youngest = years[0], years[-1]
    elapsed = youngest - oldest
    if elapsed <= 0:
        raise ValueError("Oldest and youngest shoreline years must differ.")
    out = wide_table.copy()
    out["EPR_NET_DISTANCE"] = out[f"TO_{youngest}"] - out[f"TO_{oldest}"]
    out["EPR_RATE"] = out["EPR_NET_DISTANCE"] / elapsed
    return out


def linear_regression_rate(wide_table: pd.DataFrame) -> pd.DataFrame:
    """Add LRR_RATE, LRR_NET_DISTANCE, and LRR_R2 columns to a
    transects_qgis.to_wide_table table: an OLS fit of along-transect
    distance vs. shoreline year across every TO_<year> column present for
    that row (rows with fewer than 2 non-NaN years get NaN results)."""
    years = _year_columns(wide_table)
    if len(years) < 2:
        raise ValueError("linear_regression_rate needs at least 2 shoreline years.")
    elapsed = years[-1] - years[0]
    cols = [f"TO_{y}" for y in years]
    x = np.array(years, dtype=float)

    def _fit(row: pd.Series) -> pd.Series:
        """OLS-fit one transect's row of TO_<year> distances against `x`
        (the shoreline years), skipping any NaN years for that row.
        Returns NaN results if fewer than 2 valid (year, distance) points
        are available for this transect."""
        y = row[cols].to_numpy(dtype=float)
        valid = ~np.isnan(y)
        if valid.sum() < 2:
            return pd.Series({"LRR_RATE": np.nan, "LRR_NET_DISTANCE": np.nan, "LRR_R2": np.nan})
        result = stats.linregress(x[valid], y[valid])
        return pd.Series({
            "LRR_RATE": result.slope,
            "LRR_NET_DISTANCE": result.slope * elapsed,
            "LRR_R2": result.rvalue ** 2,
        })

    fitted = wide_table.apply(_fit, axis=1)
    out = wide_table.copy()
    out[["LRR_RATE", "LRR_NET_DISTANCE", "LRR_R2"]] = fitted[["LRR_RATE", "LRR_NET_DISTANCE", "LRR_R2"]]
    return out


def compute_rate_of_change(wide_table: pd.DataFrame) -> pd.DataFrame:
    """Combine `end_point_rate` and `linear_regression_rate` into one table:
    EPR_NET_DISTANCE/EPR_RATE plus LRR_NET_DISTANCE/LRR_RATE/LRR_R2 appended
    to the input transects_qgis.to_wide_table table. EPR_RATE and LRR_RATE
    are the two "average annual change" values (end-point and
    regression-based, respectively)."""
    epr = end_point_rate(wide_table)
    lrr = linear_regression_rate(wide_table)
    out = wide_table.copy()
    out["EPR_NET_DISTANCE"] = epr["EPR_NET_DISTANCE"]
    out["EPR_RATE"] = epr["EPR_RATE"]
    out["LRR_NET_DISTANCE"] = lrr["LRR_NET_DISTANCE"]
    out["LRR_RATE"] = lrr["LRR_RATE"]
    out["LRR_R2"] = lrr["LRR_R2"]
    return out


_POLYGON_FIELDS = [
    QgsField("TRANSECT_A"), QgsField("TRANSECT_B"), QgsField("YEAR_A"), QgsField("YEAR_B"),
    QgsField("MAGNITUDE"), QgsField("RATE"), QgsField("PROB_CHANGE"),
]
_POLYGON_COLUMNS = [f.name() for f in _POLYGON_FIELDS]


def build_rate_change_polygons(
    rate_transects: List[Transect],
    rate_wide_table: pd.DataFrame,
    sigma_by_year: Dict[int, float],
    crs=None,
):
    """Build one polygon per gap between two sequentially-adjacent rate
    transects, for every shoreline year pair -- a polygon-area analogue of
    the per-transect EPR_NET_DISTANCE/EPR_RATE statistics, useful for
    mapping which stretches of coast eroded/accreted the most (and how
    confidently "real" that change is) rather than reading individual
    transect values one at a time.

    Each polygon is the quadrilateral bounded by the two adjacent
    transects' shoreline-intersection points in both years
    (`Transect.geometry.interpolate(TO_<year>).asPoint()`): walking
    transect_a from its year_a point to its year_b point, across to
    transect_b's year_b point, back along transect_b to its year_a point,
    and closing back to transect_a's year_a point. Transect pairs with a gap
    in their sequential transect_id (e.g. one transect that never
    intersected any shoreline and so is absent from `rate_wide_table`) are
    skipped, since that polygon would span a discontinuity in the transect
    grid rather than a true gap between adjacent transects; pairs missing a
    TO_<year> value for either transect/year are likewise skipped.

    `crs` may be an `EPSG:1234`-style string, a bare int/numeral string, or
    an already-built `QgsCoordinateReferenceSystem` (normalized via
    io_utils_qgis._to_qgis_crs).

    Attributes (one row per adjacent-transect-pair x year-pair):
      TRANSECT_A, TRANSECT_B -- the two bounding transects' transect_id.
      YEAR_A, YEAR_B          -- the year pair (YEAR_A < YEAR_B).
      MAGNITUDE               -- mean of the two transects'
                                  TO_<YEAR_B> - TO_<YEAR_A>; same sign
                                  convention as EPR_NET_DISTANCE (negative =
                                  erosion, positive = accretion).
      RATE                    -- MAGNITUDE / (YEAR_B - YEAR_A), m/yr, same
                                  convention as EPR_RATE.
      PROB_CHANGE             -- gaussian_overlap_probability (Wernette et
                                  al. 2020 Eqs. 2-3) of the two transects'
                                  averaged TO_<YEAR_A>/TO_<YEAR_B> positions
                                  being a "real" (not uncertainty-driven)
                                  change.

    Returns an (empty but correctly shaped, if fewer than 2 transects/years
    are available) QgsVectorLayer with the fields above plus geometry.
    """
    qgis_crs = (
        crs
        if isinstance(crs, QgsCoordinateReferenceSystem)
        else (_to_qgis_crs(crs) if crs else QgsCoordinateReferenceSystem())
    )

    years = _year_columns(rate_wide_table)
    if len(years) < 2 or len(rate_transects) < 2:
        return build_memory_layer(
            geometries=[], fields=_POLYGON_FIELDS, attributes=[],
            geometry_kind="Polygon", crs=qgis_crs, name="rate_change_polygons",
        )

    by_id = {t.transect_id: t for t in rate_transects}
    wide_indexed = rate_wide_table.set_index("TRANSECT_ID")
    ordered_ids = sorted(wide_indexed.index)

    geometries: List[QgsGeometry] = []
    attributes: List[tuple] = []
    for tid_a, tid_b in zip(ordered_ids[:-1], ordered_ids[1:]):
        if tid_b - tid_a != 1 or tid_a not in by_id or tid_b not in by_id:
            continue
        transect_a, transect_b = by_id[tid_a], by_id[tid_b]
        row_a, row_b = wide_indexed.loc[tid_a], wide_indexed.loc[tid_b]

        for i, year_a in enumerate(years):
            for year_b in years[i + 1:]:
                to_a1 = row_a.get(f"TO_{year_a}")
                to_b1 = row_a.get(f"TO_{year_b}")
                to_a2 = row_b.get(f"TO_{year_a}")
                to_b2 = row_b.get(f"TO_{year_b}")
                if any(v is None or pd.isna(v) for v in (to_a1, to_b1, to_a2, to_b2)):
                    continue

                ring = [
                    transect_a.geometry.interpolate(to_a1).asPoint(),
                    transect_a.geometry.interpolate(to_b1).asPoint(),
                    transect_b.geometry.interpolate(to_b2).asPoint(),
                    transect_b.geometry.interpolate(to_a2).asPoint(),
                ]
                polygon = QgsGeometry.fromPolygonXY([
                    [QgsPointXY(p.x(), p.y()) for p in ring]
                ])
                if not polygon.isGeosValid():
                    polygon = polygon.makeValid()

                elapsed = year_b - year_a
                magnitude = ((to_b1 - to_a1) + (to_b2 - to_a2)) / 2.0
                rate = magnitude / elapsed if elapsed else float("nan")
                mu_a = (to_a1 + to_a2) / 2.0
                mu_b = (to_b1 + to_b2) / 2.0
                prob_change = float(gaussian_overlap_probability(
                    mu_a, sigma_by_year[year_a], mu_b, sigma_by_year[year_b]
                ))
                geometries.append(polygon)
                attributes.append((
                    tid_a, tid_b, year_a, year_b, magnitude, rate, prob_change,
                ))

    return build_memory_layer(
        geometries=geometries, fields=_POLYGON_FIELDS, attributes=attributes,
        geometry_kind="Polygon", crs=qgis_crs, name="rate_change_polygons",
    )
