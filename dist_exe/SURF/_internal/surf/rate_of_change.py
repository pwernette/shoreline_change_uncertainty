"""End Point Rate (EPR) and Linear Regression Rate (LRR) shoreline
change-rate statistics -- the standard DSAS (Digital Shoreline Analysis
System) -style companion metrics to the ODB significance test
(epsilon_bands.py) and the prob_change probability surfaces
(probability_surface.py) elsewhere in this package.

Computed along a separate, denser transect grid (see
`SiteConfig.rate_transect_spacing`, default 1m) from the general-purpose
`transects.shp` used for direction/magnitude reporting, so a fine-grained
per-meter rate profile can be produced without forcing every other
transect-based output to that resolution. The transect generation and
shoreline-intersection machinery is identical -- see
`transects.generate_transects` / `transects.intersect_transects_shorelines`
/ `transects.to_wide_table` -- only the spacing differs.

  - EPR (End Point Rate): uses only the oldest and youngest shoreline years
    at each transect. EPR_NET_DISTANCE is the raw along-transect distance
    between them (signed the same way as the TO_<year> columns themselves);
    EPR_RATE is that distance divided by the elapsed years between the two
    dates (m/yr) -- this *is* the "average annual change" based on the
    end-point method.
  - LRR (Linear Regression Rate): ordinary-least-squares regression of
    along-transect distance vs. shoreline year, using every year available
    at that transect (>= 2 required). LRR_RATE (the slope, m/yr) *is* the
    "average annual change" based on the regression method;
    LRR_NET_DISTANCE is LRR_RATE multiplied by the elapsed years between
    the oldest and youngest years, given as a magnitude analogous to
    EPR_NET_DISTANCE for direct comparison. LRR_R2 is the regression's
    coefficient of determination (1.0 whenever only 2 years are available,
    since a line through 2 points is an exact fit -- LRR and EPR are then
    numerically identical; LRR_R2 only diverges from 1.0, and LRR_RATE from
    EPR_RATE, once 3+ shoreline years exist for a site).

`build_rate_change_polygons` adds a polygon-area analogue of the same
EPR-style statistics: rather than one signed value per transect, it
produces one polygon per gap between two sequentially-adjacent rate
transects (per shoreline year pair), carrying the averaged magnitude/
direction of change and the probability that the change is "real" (Wernette
et al. 2020 Eqs. 2-3) for that stretch of coast.
"""
from __future__ import annotations

from typing import Dict, List

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import stats
from shapely.geometry import Polygon

from .probability_surface import gaussian_overlap_probability
from .transects import Transect


def _year_columns(wide_table: pd.DataFrame) -> List[int]:
    """Extract and sort the shoreline years present as TO_<year> columns in
    a transects.to_wide_table table (e.g. ["TO_1938", "TO_2010"] -> [1938,
    2010]), used by both end_point_rate and linear_regression_rate to find
    the oldest/youngest years and the full set of years to regress over."""
    return sorted(int(c.split("_", 1)[1]) for c in wide_table.columns if c.startswith("TO_"))


def end_point_rate(wide_table: pd.DataFrame) -> pd.DataFrame:
    """Add EPR_NET_DISTANCE and EPR_RATE columns to a transects.to_wide_table
    table, using only the oldest and youngest TO_<year> columns present."""
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
    transects.to_wide_table table: an OLS fit of along-transect distance vs.
    shoreline year across every TO_<year> column present for that row
    (rows with fewer than 2 non-NaN years get NaN results)."""
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
    to the input transects.to_wide_table table. EPR_RATE and LRR_RATE are
    the two "average annual change" values (end-point and regression-based,
    respectively)."""
    epr = end_point_rate(wide_table)
    lrr = linear_regression_rate(wide_table)
    out = wide_table.copy()
    out["EPR_NET_DISTANCE"] = epr["EPR_NET_DISTANCE"]
    out["EPR_RATE"] = epr["EPR_RATE"]
    out["LRR_NET_DISTANCE"] = lrr["LRR_NET_DISTANCE"]
    out["LRR_RATE"] = lrr["LRR_RATE"]
    out["LRR_R2"] = lrr["LRR_R2"]
    return out


_POLYGON_COLUMNS = [
    "TRANSECT_A", "TRANSECT_B", "YEAR_A", "YEAR_B", "MAGNITUDE", "RATE", "PROB_CHANGE", "geometry",
]


def build_rate_change_polygons(
    rate_transects: List[Transect],
    rate_wide_table: pd.DataFrame,
    sigma_by_year: Dict[int, float],
    crs=None,
) -> "gpd.GeoDataFrame":
    """Build one polygon per gap between two sequentially-adjacent rate
    transects, for every shoreline year pair -- a polygon-area analogue of
    the per-transect EPR_NET_DISTANCE/EPR_RATE statistics, useful for
    mapping which stretches of coast eroded/accreted the most (and how
    confidently "real" that change is) rather than reading individual
    transect values one at a time.

    Each polygon is the quadrilateral bounded by the two adjacent
    transects' shoreline-intersection points in both years
    (`Transect.geometry.interpolate(TO_<year>)`): walking transect_a from
    its year_a point to its year_b point, across to transect_b's year_b
    point, back along transect_b to its year_a point, and closing back to
    transect_a's year_a point. Transect pairs with a gap in their
    sequential transect_id (e.g. one transect that never intersected any
    shoreline and so is absent from `rate_wide_table`) are skipped, since
    that polygon would span a discontinuity in the transect grid rather
    than a true gap between adjacent transects; pairs missing a TO_<year>
    value for either transect/year are likewise skipped.

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
    are available) GeoDataFrame with the columns above plus geometry.
    """
    years = _year_columns(rate_wide_table)
    if len(years) < 2 or len(rate_transects) < 2:
        return gpd.GeoDataFrame({c: [] for c in _POLYGON_COLUMNS}, geometry="geometry", crs=crs)

    by_id = {t.transect_id: t for t in rate_transects}
    wide_indexed = rate_wide_table.set_index("TRANSECT_ID")
    ordered_ids = sorted(wide_indexed.index)

    rows = []
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

                polygon = Polygon([
                    transect_a.geometry.interpolate(to_a1),
                    transect_a.geometry.interpolate(to_b1),
                    transect_b.geometry.interpolate(to_b2),
                    transect_b.geometry.interpolate(to_a2),
                ])
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)

                elapsed = year_b - year_a
                magnitude = ((to_b1 - to_a1) + (to_b2 - to_a2)) / 2.0
                rate = magnitude / elapsed if elapsed else float("nan")
                mu_a = (to_a1 + to_a2) / 2.0
                mu_b = (to_b1 + to_b2) / 2.0
                prob_change = float(gaussian_overlap_probability(
                    mu_a, sigma_by_year[year_a], mu_b, sigma_by_year[year_b]
                ))
                rows.append({
                    "TRANSECT_A": tid_a, "TRANSECT_B": tid_b,
                    "YEAR_A": year_a, "YEAR_B": year_b,
                    "MAGNITUDE": magnitude, "RATE": rate,
                    "PROB_CHANGE": prob_change, "geometry": polygon,
                })

    if not rows:
        return gpd.GeoDataFrame({c: [] for c in _POLYGON_COLUMNS}, geometry="geometry", crs=crs)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
