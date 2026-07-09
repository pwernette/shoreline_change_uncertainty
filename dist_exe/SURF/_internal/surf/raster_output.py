"""Raster (gridded) uncertainty / similarity-index surfaces.

Replaces original_program/arcgis_pro/raster_buffers_analysis.py, which never
actually performed raster cell math: despite the filename, it only unioned
vector buffer polygons (Union_analysis ONLY_FID) and counted overlaps via a
'Similarity_Index' attribute on the resulting VECTOR polygons. Here we build
a genuine raster surface with rasterio.features.rasterize, in the spirit of
the spatially-variable uncertainty concept from Wernette et al. (2020),
"What is 'real'? Identifying erosion and deposition in context of
spatially-variable uncertainty."

For every output cell:
  - Similarity_Index = the number of per-year-pair uncertainty buffers
    (buffer_a + buffer_b, across all ODB pairs for the site) covering that
    cell -- i.e. how often the cell fell inside an ambiguous, positional
    uncertainty-confounded zone.
  - Significant_Change = 1 if at least one year-pair's union footprint
    covers the cell OUTSIDE that pair's overlap region (the area
    distinguishing real change for a significant pair), else 0.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry.base import BaseGeometry
from tqdm import tqdm


def build_grid_transform(bounds: Tuple[float, float, float, float], cell_size: float):
    """Build a rasterio Affine `transform` plus pixel `width`/`height` for a
    grid covering `bounds` (minx, miny, maxx, maxy) at `cell_size` per pixel.
    The grid origin is the bounds' upper-left corner (minx, maxy), matching
    rasterio's row-0-at-top convention; width/height are rounded up so the
    grid always fully covers `bounds` even when it isn't an exact multiple
    of `cell_size`.
    """
    minx, miny, maxx, maxy = bounds
    width = max(1, int(np.ceil((maxx - minx) / cell_size)))
    height = max(1, int(np.ceil((maxy - miny) / cell_size)))
    transform = from_origin(minx, maxy, cell_size, cell_size)
    return transform, width, height


def rasterize_geometry(geom: BaseGeometry, transform, width: int, height: int, fill: int = 0, value: int = 1) -> np.ndarray:
    """Burn a single vector `geom` into a (height, width) uint16 array using
    the given grid `transform`: cells covered by `geom` get `value`, all
    others get `fill`. Returns an all-`fill` array directly (skipping
    rasterio.features.rasterize) when `geom` is None/empty, since rasterize
    requires at least one non-empty shape.
    """
    if geom is None or geom.is_empty:
        return np.full((height, width), fill, dtype=np.uint16)
    return rasterize(
        [(geom, value)], out_shape=(height, width), transform=transform,
        fill=fill, dtype="uint16",
    )


def _union_bounds(geoms: List[BaseGeometry]):
    """Bounding box (minx, miny, maxx, maxy) covering every non-empty
    geometry in `geoms` -- used to size the output raster grid so it fully
    contains every uncertainty buffer being rasterized."""
    xs_min, ys_min, xs_max, ys_max = [], [], [], []
    for g in geoms:
        if g is None or g.is_empty:
            continue
        minx, miny, maxx, maxy = g.bounds
        xs_min.append(minx)
        ys_min.append(miny)
        xs_max.append(maxx)
        ys_max.append(maxy)
    if not xs_min:
        raise ValueError("No valid geometries to compute bounds from.")
    return min(xs_min), min(ys_min), max(xs_max), max(ys_max)


def build_similarity_surface(odb_results, cell_size: float, *, progress: bool = True):
    """Build a Similarity_Index raster (count of overlapping buffer-pair
    polygons per cell) plus a Significant_Change raster from a list of
    epsilon_bands.ODBResult objects covering one site.

    Returns (similarity_index_array, significant_change_array, transform).
    """
    all_geoms = []
    for r in odb_results:
        all_geoms.append(r.buffer_a)
        all_geoms.append(r.buffer_b)
    bounds = _union_bounds(all_geoms)
    transform, width, height = build_grid_transform(bounds, cell_size)

    similarity = np.zeros((height, width), dtype=np.uint16)
    significant = np.zeros((height, width), dtype=np.uint8)

    for r in tqdm(odb_results, desc="Rasterizing ODB buffer pairs", disable=not progress, leave=False):
        mask_a = rasterize_geometry(r.buffer_a, transform, width, height)
        mask_b = rasterize_geometry(r.buffer_b, transform, width, height)
        similarity += mask_a + mask_b

        if r.significant_change:
            union_mask = rasterize_geometry(r.buffer_a.union(r.buffer_b), transform, width, height)
            overlap_mask = rasterize_geometry(r.intersection, transform, width, height)
            real_change_mask = union_mask.astype(bool) & ~overlap_mask.astype(bool)
            significant |= real_change_mask.astype(np.uint8)

    return similarity, significant, transform


def write_raster(array: np.ndarray, transform, crs, path: str | Path, dtype: str = "uint16", nodata=None) -> None:
    """Write a single-band GeoTIFF to `path` (creating parent directories as
    needed) from a 2D `array`, georeferenced by `transform`/`crs`. `array`
    is cast to `dtype` before writing; pass `nodata` to flag a sentinel
    value (e.g. for the float32 probability-surface rasters)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1],
        count=1, dtype=dtype, crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(array.astype(dtype), 1)
