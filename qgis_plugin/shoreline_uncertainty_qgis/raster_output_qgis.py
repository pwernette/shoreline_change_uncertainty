"""QGIS-native port of shoreline_uncertainty/raster_output.py.

Raster (gridded) uncertainty / similarity-index surfaces.

Replaces original_program/arcgis_pro/raster_buffers_analysis.py, which never
actually performed raster cell math: despite the filename, it only unioned
vector buffer polygons (Union_analysis ONLY_FID) and counted overlaps via a
'Similarity_Index' attribute on the resulting VECTOR polygons. Here we build
a genuine raster surface, in the spirit of the spatially-variable
uncertainty concept from Wernette et al. (2020), "What is 'real'?
Identifying erosion and deposition in context of spatially-variable
uncertainty."

For every output cell:
  - Similarity_Index = the number of per-year-pair uncertainty buffers
    (buffer_a + buffer_b, across all ODB pairs for the site) covering that
    cell -- i.e. how often the cell fell inside an ambiguous, positional
    uncertainty-confounded zone.
  - Significant_Change = 1 if at least one year-pair's union footprint
    covers the cell OUTSIDE that pair's overlap region (the area
    distinguishing real change for a significant pair), else 0.

Ported onto QGIS-bundled GDAL (`osgeo.gdal` / `osgeo.ogr` / `osgeo.osr`)
instead of rasterio + rasterio.features.rasterize: QGIS ships its own GDAL
Python bindings, so this plugin needs no extra Python packages for raster
I/O beyond what QGIS itself bundles.

Geotransform note: rather than depend on the `affine` package (a rasterio
dependency, not guaranteed to ship inside QGIS), grid georeferencing here is
represented by the small `GridTransform` namedtuple below, using the same
(a, b, c, d, e, f) affine-coefficient convention and pixel-center formula
rasterio/affine use (x = a*col + b*row + c, y = d*col + e*row + f) -- so the
pixel-center math in probability_surface_qgis.py is unchanged from the
standalone package. `to_gdal()`/`from_gdal()` convert to/from GDAL's own
six-element geotransform tuple (origin_x, pixel_width, x_rotation, origin_y,
y_rotation, pixel_height).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, NamedTuple, Tuple

import numpy as np
from osgeo import gdal, ogr, osr
from qgis.core import QgsGeometry
from tqdm import tqdm

gdal.UseExceptions()

_GDAL_DTYPES = {
    "uint8": gdal.GDT_Byte,
    "uint16": gdal.GDT_UInt16,
    "int16": gdal.GDT_Int16,
    "int32": gdal.GDT_Int32,
    "float32": gdal.GDT_Float32,
    "float64": gdal.GDT_Float64,
}

_NUMPY_DTYPES = {
    "uint8": np.uint8,
    "uint16": np.uint16,
    "int16": np.int16,
    "int32": np.int32,
    "float32": np.float32,
    "float64": np.float64,
}


class GridTransform(NamedTuple):
    """Affine-style grid georeferencing: x = a*col + b*row + c,
    y = d*col + e*row + f -- same field names/convention as the `affine`
    package's `Affine` (which rasterio uses internally), so
    probability_surface_qgis.py's pixel-center math is unchanged from the
    standalone package."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def to_gdal(self) -> Tuple[float, float, float, float, float, float]:
        """Convert to GDAL's own 6-tuple geotransform convention
        (origin_x, pixel_width, x_rotation, origin_y, y_rotation,
        pixel_height)."""
        return (self.c, self.a, self.b, self.f, self.d, self.e)

    @staticmethod
    def from_gdal(gt: Tuple[float, float, float, float, float, float]) -> "GridTransform":
        origin_x, pixel_width, rot_x, origin_y, rot_y, pixel_height = gt
        return GridTransform(pixel_width, rot_x, origin_x, rot_y, pixel_height, origin_y)


def from_origin(west: float, north: float, xsize: float, ysize: float) -> GridTransform:
    """Build a north-up GridTransform with no rotation, matching
    rasterio.transform.from_origin's signature/semantics."""
    return GridTransform(xsize, 0.0, west, 0.0, -ysize, north)


def build_grid_transform(bounds: Tuple[float, float, float, float], cell_size: float) -> Tuple[GridTransform, int, int]:
    """Build a `GridTransform` plus pixel `width`/`height` for a grid
    covering `bounds` (minx, miny, maxx, maxy) at `cell_size` per pixel. The
    grid origin is the bounds' upper-left corner (minx, maxy); width/height
    are rounded up so the grid always fully covers `bounds` even when it
    isn't an exact multiple of `cell_size`.
    """
    minx, miny, maxx, maxy = bounds
    width = max(1, int(np.ceil((maxx - minx) / cell_size)))
    height = max(1, int(np.ceil((maxy - miny) / cell_size)))
    transform = from_origin(minx, maxy, cell_size, cell_size)
    return transform, width, height


def rasterize_geometry(
    geom: QgsGeometry, transform: GridTransform, width: int, height: int, fill: int = 0, value: int = 1
) -> np.ndarray:
    """Burn a single vector `geom` into a (height, width) uint16 array using
    the given grid `transform`: cells covered by `geom` get `value`, all
    others get `fill`. Returns an all-`fill` array directly when `geom` is
    None/empty, since GDAL's rasterizer requires at least one non-empty
    shape.

    Implemented via an in-memory GDAL ("MEM" driver) raster dataset plus an
    in-memory OGR ("Memory" driver) vector layer holding `geom` (converted
    from QgsGeometry via WKB), burned in with `gdal.RasterizeLayer` -- the
    QGIS-bundled-GDAL equivalent of rasterio.features.rasterize.
    """
    if geom is None or geom.isEmpty():
        return np.full((height, width), fill, dtype=np.uint16)

    mem_ds = gdal.GetDriverByName("MEM").Create("", width, height, 1, gdal.GDT_UInt16)
    mem_ds.SetGeoTransform(transform.to_gdal())
    band = mem_ds.GetRasterBand(1)
    band.Fill(fill)

    mem_ogr_ds = ogr.GetDriverByName("Memory").CreateDataSource("burn")
    layer = mem_ogr_ds.CreateLayer("burn", geom_type=ogr.wkbUnknown)
    feat = ogr.Feature(layer.GetLayerDefn())
    feat.SetGeometry(ogr.CreateGeometryFromWkb(bytes(geom.asWkb())))
    layer.CreateFeature(feat)

    gdal.RasterizeLayer(mem_ds, [1], layer, burn_values=[value])
    return band.ReadAsArray().astype(np.uint16)


def _union_bounds(geoms: List[QgsGeometry]) -> Tuple[float, float, float, float]:
    """Bounding box (minx, miny, maxx, maxy) covering every non-empty
    geometry in `geoms` -- used to size the output raster grid so it fully
    contains every uncertainty buffer being rasterized."""
    xs_min, ys_min, xs_max, ys_max = [], [], [], []
    for g in geoms:
        if g is None or g.isEmpty():
            continue
        bbox = g.boundingBox()
        xs_min.append(bbox.xMinimum())
        ys_min.append(bbox.yMinimum())
        xs_max.append(bbox.xMaximum())
        ys_max.append(bbox.yMaximum())
    if not xs_min:
        raise ValueError("No valid geometries to compute bounds from.")
    return min(xs_min), min(ys_min), max(xs_max), max(ys_max)


def build_similarity_surface(odb_results, cell_size: float, *, progress: bool = True):
    """Build a Similarity_Index raster (count of overlapping buffer-pair
    polygons per cell) plus a Significant_Change raster from a list of
    epsilon_bands_qgis.ODBResult objects covering one site.

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
            union_mask = rasterize_geometry(r.buffer_a.combine(r.buffer_b), transform, width, height)
            overlap_mask = rasterize_geometry(r.intersection, transform, width, height)
            real_change_mask = union_mask.astype(bool) & ~overlap_mask.astype(bool)
            significant |= real_change_mask.astype(np.uint8)

    return similarity, significant, transform


def write_raster(
    array: np.ndarray, transform: GridTransform, crs, path: str | Path, dtype: str = "uint16", nodata=None
) -> None:
    """Write a single-band GeoTIFF to `path` (creating parent directories as
    needed) from a 2D `array`, georeferenced by `transform`/`crs`. `array`
    is cast to `dtype` before writing; pass `nodata` to flag a sentinel
    value (e.g. for the float32 probability-surface rasters).

    `crs` may be a `QgsCoordinateReferenceSystem` (its `.authid()` is used)
    or any string GDAL's `osr.SpatialReference.SetFromUserInput` accepts
    (e.g. `"EPSG:32616"`).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    height, width = array.shape
    gdal_dtype = _GDAL_DTYPES[dtype]
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(path), width, height, 1, gdal_dtype)
    ds.SetGeoTransform(transform.to_gdal())

    crs_str = crs.authid() if hasattr(crs, "authid") else str(crs)
    srs = osr.SpatialReference()
    srs.SetFromUserInput(crs_str)
    ds.SetProjection(srs.ExportToWkt())

    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    band.WriteArray(array.astype(_NUMPY_DTYPES[dtype]))
    band.FlushCache()
    ds = None
