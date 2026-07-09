"""Probability-surface and "probability of real change" analysis for
horizontal shoreline position uncertainty.

This is the horizontal-direction analogue of the vertical DEM-differencing
"change probability" (CP) approach in Wernette et al. (2020), "What is
'real'? Identifying erosion and deposition in context of spatially-variable
uncertainty," Geomorphology 355, 107083 (included in this repo as a PDF).
There, at every pixel, a DEM value z and its uncertainty (standard
deviation) sigma define a Gaussian distribution N(z, sigma^2); the
probability that an observed change between two epochs is "real" is
computed from the overlap area between the two epochs' Gaussian
distributions (their Eqs. 1-4).

Here the same equations are applied with z replaced by a measure of
horizontal shoreline position instead of vertical elevation:

  - Per-transect (`change_probability_table`): z = the along-transect
    distance to the shoreline (the existing transect_distances_wide.csv
    TO_<year> values), sigma = the shoreline's RMSE95-derived positional
    standard deviation.
  - Per-pixel, continuous raster (`change_probability_raster`), "around
    the shoreline": z(x,y) = the signed perpendicular distance from pixel
    (x,y) to the shoreline curve, signed by which side of the site's
    baseline the pixel falls on (the same baseline/coordinate_priority
    convention transects.py uses), so that distance differences between
    two shorelines correctly capture cases where a point lies between
    them, not just how far each line is from it. sigma is constant per
    shoreline year -- this package has no spatially-variable uncertainty
    *surface* for shoreline vectors, unlike the DSM uncertainty rasters in
    the 2020 paper, so sigma does not vary pixel-to-pixel within a year.

The "probability surface for shoreline position" (`position_probability_surfaces`,
one per shoreline year, independent of any other year) is a separate,
simpler quantity: it is just the Gaussian distribution N(0, sigma^2)
describing positional uncertainty around the digitized line (Fig. 1 of
Wernette et al. 2020), evaluated at every pixel's distance to the line --
i.e. a direct visualization of that per-epoch uncertainty model, before any
two-epoch comparison.

Equations 1-4 of Wernette et al. (2020), translated here:

  Eq. 1   dz(x,y) = z_b(x,y) - z_a(x,y)                    (observed change)
  Eq. 2   c = intersection point of N(z_a, sigma_a^2) and N(z_b, sigma_b^2)
  Eq. 3   P_real = 1 - [P(X_a > c) + P(X_b < c)]    (assuming z_a < z_b; the
                                                      lower/higher means are
                                                      sorted automatically)
  Eq. 4   erf(x) = (2/sqrt(pi)) * integral_0^x exp(-t^2) dt  (error function)

Eqs. 2-3 are implemented in `gaussian_overlap_probability` via the standard
closed-form intersection of two normal pdfs (Inman & Bradley, 1989, "The
overlapping coefficient as a measure of agreement between probability
distributions and point estimation of the overlap of two normal
densities", Comm. Statist. Theory Methods -- the construction Wernette et
al. (2020) cite their Eqs. 2-3 from) and `scipy.stats.norm.cdf` rather than
a literal erf transcription. The two are numerically identical
(Phi(z) = (1 + erf(z / sqrt(2))) / 2) but using `norm.cdf` avoids
re-deriving the sign bookkeeping behind the two-column PDF's stacked
equation typesetting.

RMSE95 (used elsewhere in this package, e.g. uncertainty.rmse95 /
rmse95_override, as the NSSDA 95% circular/radial positional-accuracy
radius -- Eq. 3 of Wernette et al. 2017) is converted to the 1D
(cross-shore) standard deviation sigma needed for the Gaussian math above
via the circular-normal relationship already implicit in that NSSDA
definition: RMSE95 = 1.7308 * RMSE_O, where RMSE_O is the radial RMSE of an
isotropic 2D Gaussian positional error with per-axis standard deviation
sigma (RMSE_O = sigma * sqrt(2)); the 95% radius of such an isotropic 2D
Gaussian is sigma * sqrt(-2 * ln(0.05)) = 2.4477 * sigma, and
1.7308 * sqrt(2) = 2.4477, confirming the two are the same circular-normal
model. `rmse95_to_sigma` performs this conversion.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import ndimage
from scipy.stats import norm
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring

from .raster_output import rasterize_geometry

ArrayOrFloat = Union[float, np.ndarray]

# NSSDA circular/radial 95% accuracy factor -- see module docstring.
NSSDA_95_FACTOR = 2.4477


def rmse95_to_sigma(rmse95: float) -> float:
    """Convert an NSSDA 95% circular/radial accuracy radius (RMSE95, as
    used elsewhere in this package) into a 1D (cross-shore) positional
    standard deviation: sigma = RMSE95 / 2.4477."""
    return rmse95 / NSSDA_95_FACTOR


def signed_distance_raster(
    line: BaseGeometry,
    baseline_center: Tuple[float, float],
    baseline_direction: Tuple[float, float],
    transform,
    width: int,
    height: int,
) -> np.ndarray:
    """Per-pixel Euclidean distance to `line`, signed by which side of the
    baseline (through `baseline_center`, with unit direction
    `baseline_direction`) each pixel falls on -- the same side/sign
    convention transects.py establishes via coordinate_priority, applied
    here pixel-wise so distances to two different shorelines can be
    meaningfully *subtracted* (Eq. 1) rather than only compared in
    magnitude.
    """
    mask = rasterize_geometry(line, transform, width, height).astype(bool)
    cell_size = abs(transform.a)
    unsigned = ndimage.distance_transform_edt(~mask) * cell_size

    rows, cols = np.indices((height, width))
    xs = transform.c + (cols + 0.5) * transform.a + (rows + 0.5) * transform.b
    ys = transform.f + (cols + 0.5) * transform.d + (rows + 0.5) * transform.e

    cx, cy = baseline_center
    dx, dy = baseline_direction
    side = np.sign((xs - cx) * dy - (ys - cy) * dx)
    side[side == 0] = 1.0
    return unsigned * side


def position_probability_surfaces(
    line: BaseGeometry,
    sigma: float,
    transform,
    width: int,
    height: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-shoreline "probability surface for shoreline position": the
    Gaussian distribution N(0, sigma^2) describing positional uncertainty
    around the digitized line, evaluated at every pixel's (unsigned)
    distance to the line.

    Returns (pdf, confidence):
      pdf        -- the true Gaussian probability *density*,
                     (1 / (sigma * sqrt(2*pi))) * exp(-d^2 / (2*sigma^2));
                     units of 1/distance, peak value depends on sigma.
      confidence -- the same Gaussian curve normalized to peak at 1.0
                     exactly on the line, exp(-d^2 / (2*sigma^2)) -- easier
                     to read/compare visually across shorelines with
                     different sigma.
    """
    mask = rasterize_geometry(line, transform, width, height).astype(bool)
    cell_size = abs(transform.a)
    d = ndimage.distance_transform_edt(~mask) * cell_size
    confidence = np.exp(-(d ** 2) / (2.0 * sigma ** 2))
    pdf = confidence / (sigma * np.sqrt(2.0 * np.pi))
    return pdf, confidence


def gaussian_overlap_probability(
    mu_a: ArrayOrFloat, sigma_a: ArrayOrFloat,
    mu_b: ArrayOrFloat, sigma_b: ArrayOrFloat,
) -> np.ndarray:
    """Probability that an observed difference between two Gaussian-
    distributed quantities, N(mu_a, sigma_a^2) and N(mu_b, sigma_b^2), is
    "real" (Wernette et al. 2020 Eqs. 2-3): 1 minus the overlap area
    between the two normal distributions (the Inman & Bradley 1989
    "overlapping coefficient").

    Two normal pdfs with *equal* variance cross at exactly one point (the
    midpoint of the two means), so the overlap is just the sum of two
    tails split at that point. With *unequal* variance the pdfs cross at
    two points, symmetric about neither mean in general: between the two
    crossing points the narrower (smaller-sigma) distribution is on top;
    outside that interval the wider (larger-sigma) distribution is on top
    (its heavier tails eventually exceed the narrower curve in both
    directions). The overlap area is then the wider distribution's mass
    between the two crossings plus the narrower distribution's mass
    outside them. Using only one crossing point (as if the equal-variance
    formula still applied) silently drops the second crossing's
    contribution and is wrong whenever sigma_a != sigma_b.

    All four inputs may be scalars or same-shaped numpy arrays (e.g. whole
    rasters); returns an array (0-d for scalar inputs) of P_real values in
    [0, 1].
    """
    mu_a = np.asarray(mu_a, dtype=float)
    sigma_a = np.asarray(sigma_a, dtype=float)
    mu_b = np.asarray(mu_b, dtype=float)
    sigma_b = np.asarray(sigma_b, dtype=float)

    safe_sigma_a = np.where(sigma_a == 0, 1e-12, sigma_a)
    safe_sigma_b = np.where(sigma_b == 0, 1e-12, sigma_b)

    equal_sigma = np.isclose(safe_sigma_a, safe_sigma_b)
    equal_mu = np.isclose(mu_a, mu_b)

    # --- Equal-variance case: single crossing at the midpoint. ---
    sigma_avg = (safe_sigma_a + safe_sigma_b) / 2.0
    overlap_equal_sigma = 2.0 * norm.cdf(-np.abs(mu_a - mu_b) / (2.0 * sigma_avg))

    # --- General (unequal-variance) case: two crossing points, found by
    # solving A*x^2 + B*x + C = 0 for where the two log-pdfs are equal
    # (Inman & Bradley 1989 / Wernette et al. 2020 Eq. 2). Label by sigma,
    # not by mean: S = narrower (smaller-sigma) distribution, L = wider.
    narrower_is_a = safe_sigma_a <= safe_sigma_b
    mu_s = np.where(narrower_is_a, mu_a, mu_b)
    sigma_s = np.where(narrower_is_a, safe_sigma_a, safe_sigma_b)
    mu_l = np.where(narrower_is_a, mu_b, mu_a)
    sigma_l = np.where(narrower_is_a, safe_sigma_b, safe_sigma_a)

    with np.errstate(divide="ignore", invalid="ignore"):
        A = 1.0 / sigma_s ** 2 - 1.0 / sigma_l ** 2
        safe_A = np.where(A == 0, 1e-12, A)
        B = -2.0 * (mu_s / sigma_s ** 2 - mu_l / sigma_l ** 2)
        C = (
            mu_s ** 2 / sigma_s ** 2
            - mu_l ** 2 / sigma_l ** 2
            - 2.0 * np.log(sigma_l / sigma_s)
        )
        disc = np.maximum(B ** 2 - 4.0 * safe_A * C, 0.0)
        sqrt_disc = np.sqrt(disc)
        root1 = (-B + sqrt_disc) / (2.0 * safe_A)
        root2 = (-B - sqrt_disc) / (2.0 * safe_A)
        r_lo = np.minimum(root1, root2)
        r_hi = np.maximum(root1, root2)

        # Narrower distribution's mass outside [r_lo, r_hi] (its tails are
        # below the wider curve out there), plus wider distribution's mass
        # inside [r_lo, r_hi] (it's below the narrower curve in the middle).
        overlap_general = (
            norm.cdf(r_lo, loc=mu_s, scale=sigma_s)
            + (norm.cdf(r_hi, loc=mu_l, scale=sigma_l) - norm.cdf(r_lo, loc=mu_l, scale=sigma_l))
            + (1.0 - norm.cdf(r_hi, loc=mu_s, scale=sigma_s))
        )

    overlap = np.where(equal_sigma, overlap_equal_sigma, overlap_general)
    overlap = np.clip(overlap, 0.0, 1.0)
    p_real = 1.0 - overlap

    # Domain-specific override (not a generic overlap-coefficient property):
    # mu here is an *observed* shoreline position, and Eq. 1's delta is the
    # difference between two such observed positions. If the two observed
    # positions are exactly equal, the observed change is exactly zero, so
    # it cannot be "real" regardless of how the two years' uncertainties
    # compare -- even though two same-mean, different-sigma distributions
    # are technically distinguishable in the generic statistical sense
    # (overlap_general < 1 there), that distinguishability isn't evidence
    # of a *change* in position for this application.
    p_real = np.where(equal_mu, 0.0, p_real)
    return p_real


def change_probability_raster(
    line_a: BaseGeometry, sigma_a: float,
    line_b: BaseGeometry, sigma_b: float,
    baseline_center: Tuple[float, float],
    baseline_direction: Tuple[float, float],
    transform, width: int, height: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-pixel "probability that the observed change is real" (Wernette
    et al. 2020 Eqs. 1-4), translated to the horizontal: z(x,y) is the
    signed perpendicular distance from pixel (x,y) to each shoreline
    (`signed_distance_raster`), sigma is each shoreline's positional
    standard deviation (`rmse95_to_sigma`).

    Returns (delta, p_real):
      delta  -- Eq. 1, z_b(x,y) - z_a(x,y): the local cross-shore offset
                between the two shoreline curves at this pixel.
      p_real -- Eqs. 2-3: probability the offset is "real" and not an
                artifact of either shoreline's positional uncertainty.
    """
    z_a = signed_distance_raster(line_a, baseline_center, baseline_direction, transform, width, height)
    z_b = signed_distance_raster(line_b, baseline_center, baseline_direction, transform, width, height)
    delta = z_b - z_a
    p_real = gaussian_overlap_probability(z_a, sigma_a, z_b, sigma_b)
    return delta, p_real


def _iter_simple_lines(geom: BaseGeometry) -> List[LineString]:
    """Flatten a LineString/MultiLineString/GeometryCollection (e.g. the
    unary_union of a shoreline shapefile's features) into a flat list of
    simple LineStrings, merging contiguous MultiLineString parts back into
    single LineStrings where possible (shapely.ops.linemerge) so segmenting
    doesn't introduce spurious breaks at original feature boundaries."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        merged = linemerge(geom)
        if merged.is_empty:
            return []
        if merged.geom_type == "LineString":
            return [merged]
        return list(merged.geoms)
    if geom.geom_type == "GeometryCollection":
        out: List[LineString] = []
        for part in geom.geoms:
            out.extend(_iter_simple_lines(part))
        return out
    raise ValueError(f"Unsupported geometry type for segmentation: {geom.geom_type}")


def segment_line(line: BaseGeometry, segment_length: float) -> List[LineString]:
    """Break `line` into consecutive segments of length `segment_length`
    (the last segment of each component may be shorter -- segments don't
    span gaps between disconnected parts of a MultiLineString). Returns a
    flat list of LineString segments, in order, covering the whole input
    geometry."""
    if segment_length <= 0:
        raise ValueError("segment_length must be > 0")
    segments: List[LineString] = []
    for part in _iter_simple_lines(line):
        total = part.length
        if total <= 0:
            continue
        n_segments = max(1, int(math.ceil(total / segment_length)))
        for i in range(n_segments):
            d0 = i * segment_length
            d1 = min((i + 1) * segment_length, total)
            if d1 <= d0:
                continue
            sub = substring(part, d0, d1)
            if not sub.is_empty and sub.length > 0:
                segments.append(sub)
    return segments


def _shrink_for_rasterize_mask(seg: LineString, frac: float = 1e-6) -> LineString:
    """Trim a tiny epsilon off both ends of `seg` before rasterizing it for a
    cell-membership mask, to dodge rasterio.features.rasterize's
    floating-point tie-breaking when an endpoint lands exactly on a pixel
    boundary: with the default Bresenham-style line rasterization (used for
    LineString/MultiLineString geometries regardless of `all_touched`), a
    segment whose endpoint sits precisely on a column/row edge can get
    burned into the neighboring cell as well as the intended one (confirmed
    via a direct rasterize() repro -- e.g. a 10m grid with two 10-wide
    columns: LineString([(0,5),(10,5)]) burns into both columns, while the
    adjacent LineString([(10,5),(20,5)]) burns into only the second). Since
    `segment_line` deliberately produces segments whose endpoints fall
    exactly on multiples of `segment_length` -- which line up with cell
    edges whenever segment_length is a multiple of the grid's cell size --
    this is not a rare edge case for this caller. Shrinking each endpoint
    inward by `frac` of the segment's own length (floor of 1e-9 map units)
    moves it just off the boundary without changing which cell(s) a segment
    that genuinely straddles a cell boundary mid-segment is counted in."""
    length = seg.length
    if length <= 0:
        return seg
    eps = min(length * frac, length / 2.0 * 0.99)
    eps = max(eps, min(1e-9, length / 2.0 * 0.99))
    return substring(seg, eps, length - eps)


def segment_mean_probability(
    segments: List[LineString],
    p_real: np.ndarray,
    transform,
    width: int,
    height: int,
) -> List[float]:
    """Mean `p_real` (change_probability_raster output) value of every
    raster cell each segment passes through, one value per segment in
    `segments`. NaN for a segment whose rasterized footprint doesn't land on
    any cell (e.g. shorter than the cell size)."""
    means = []
    for seg in segments:
        sample_geom = _shrink_for_rasterize_mask(seg)
        mask = rasterize_geometry(sample_geom, transform, width, height).astype(bool)
        means.append(float(np.nanmean(p_real[mask])) if mask.any() else float("nan"))
    return means


def shoreline_change_probability_segments(
    line: BaseGeometry,
    segment_length: float,
    p_real: np.ndarray,
    transform,
    width: int,
    height: int,
    crs=None,
    magnitudes: List[float] = None,
) -> gpd.GeoDataFrame:
    """Break `line` (one shoreline from a year pair) into `segment_length`-
    long pieces and attach each segment's mean `change_probability_raster`
    value as PROB_CHANGE -- per-segment summary of where along *this*
    shoreline the observed change relative to its paired year is most/least
    likely to be real, addressing the same question as
    `change_probability_<a>_<b>.tif` but reduced to one attribute per
    segment on the line itself rather than a continuous pixel surface.

    `magnitudes`, if given, must have one entry per segment returned by
    `segment_line(line, segment_length)` (same order) and is attached as a
    MAGNITUDE column -- the signed (negative = erosion, positive =
    accretion) extent of along-coast change at that segment. Callers
    typically compute this via `transects.nearest_transect_net_distance`
    rather than from `p_real`/this function's own raster inputs, since
    those carry no shoreline-position sign information on their own. If
    omitted, no MAGNITUDE column is added.

    Returns a GeoDataFrame with columns SEG_ID, LENGTH, PROB_CHANGE
    (, MAGNITUDE), geometry -- empty (but correctly shaped) if `line` has no
    length.
    """
    segments = segment_line(line, segment_length)
    means = segment_mean_probability(segments, p_real, transform, width, height)
    if not segments:
        cols = {"SEG_ID": [], "LENGTH": [], "PROB_CHANGE": []}
        if magnitudes is not None:
            cols["MAGNITUDE"] = []
        cols["geometry"] = []
        return gpd.GeoDataFrame(cols, geometry="geometry", crs=crs)
    rows = [
        {"SEG_ID": i, "LENGTH": seg.length, "PROB_CHANGE": mean, "geometry": seg}
        for i, (seg, mean) in enumerate(zip(segments, means))
    ]
    if magnitudes is not None:
        if len(magnitudes) != len(rows):
            raise ValueError(
                f"magnitudes has {len(magnitudes)} entries but {len(rows)} segments were generated."
            )
        for row, mag in zip(rows, magnitudes):
            row["MAGNITUDE"] = mag
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)


def change_probability_table(wide_table: pd.DataFrame, sigma_by_year: Dict[int, float]) -> pd.DataFrame:
    """Add per-year-pair DELTA_<a>_<b> and P_REAL_<a>_<b> columns to the
    existing transect_distances_wide table (transects.to_wide_table),
    using the same Eqs. 1-4 as `change_probability_raster` but with each
    transect's TO_<year> distance standing in for z(x,y).
    """
    years = sorted(int(c.split("_", 1)[1]) for c in wide_table.columns if c.startswith("TO_"))
    out = wide_table.copy()
    for i, year_a in enumerate(years):
        for year_b in years[i + 1:]:
            z_a = out[f"TO_{year_a}"].to_numpy(dtype=float)
            z_b = out[f"TO_{year_b}"].to_numpy(dtype=float)
            out[f"DELTA_{year_a}_{year_b}"] = z_b - z_a
            out[f"P_REAL_{year_a}_{year_b}"] = gaussian_overlap_probability(
                z_a, sigma_by_year[year_a], z_b, sigma_by_year[year_b]
            )
    return out
