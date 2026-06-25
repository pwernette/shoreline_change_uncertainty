"""I/O helpers: reading shorelines, reprojecting to a metric CRS, and writing
results to vector files / CSV / pipe-delimited logs.

Wraps geopandas/shapely/pyproj/Fiona/pyogrio -- which themselves wrap
GDAL/OGR -- so this package satisfies "use rasterio, GDAL, and other Python
tools" without ever importing arcpy.

Replaces original_program/arcgis_pro/create_fc.py, whose only job was to
pre-create empty ArcGIS polyline feature classes against a hardcoded
Michigan State Plane .prj file before they could be populated by hand in
ArcGIS. geopandas/Fiona create output files on demand when written, so no
equivalent pre-creation step is needed here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
from pyproj import CRS


def read_shoreline(path: str | Path) -> gpd.GeoDataFrame:
    """Read a shoreline (or any other vector) file with geopandas and
    require it to carry a defined CRS -- every downstream length/area/
    buffer/distance calculation in this package assumes a known, ideally
    projected, coordinate system, so a missing CRS is treated as an error
    here rather than silently assumed."""
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"{path} has no CRS defined; set one before processing.")
    return gdf


def utm_epsg_for(gdf: gpd.GeoDataFrame) -> int:
    """Pick a UTM EPSG code from a geographic GeoDataFrame's centroid."""
    centroid = gdf.unary_union.centroid
    lon, lat = centroid.x, centroid.y
    zone = int((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone


def ensure_projected(gdf: gpd.GeoDataFrame, target_crs: Optional[str] = None) -> gpd.GeoDataFrame:
    """Reproject to a metric CRS suitable for area/length/buffer math.

    If `target_crs` is given, use it. Otherwise auto-detect a UTM zone when
    the input is geographic; pass through unchanged if already projected.
    """
    if target_crs:
        return gdf.to_crs(CRS.from_user_input(target_crs))
    crs = CRS(gdf.crs)
    if crs.is_geographic:
        return gdf.to_crs(epsg=utm_epsg_for(gdf))
    return gdf.copy()


def write_vector(gdf: gpd.GeoDataFrame, path: str | Path, driver: Optional[str] = None) -> None:
    """Write a GeoDataFrame to `path` (e.g. a .shp), creating parent
    directories as needed. `driver` defaults to whatever geopandas/Fiona
    infers from the file extension (ESRI Shapefile for .shp). Silently does
    nothing for an empty/None `gdf`, since several pipeline stages are
    optional and may produce no rows -- callers don't need to guard every
    write_vector call with an emptiness check themselves."""
    if gdf is None or len(gdf) == 0:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver=driver)


def write_table_csv(df: pd.DataFrame, path: str | Path) -> None:
    """Write a DataFrame to `path` as CSV (no index column), creating
    parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_table_pipe_log(df: pd.DataFrame, path: str | Path, header_lines: Optional[list] = None) -> None:
    """Write a pipe-delimited .txt log, mirroring the original scripts' log
    format (e.g. copy_output_table.py, intersecting_epsilon_bands.py)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for line in header_lines or []:
            f.write(line.rstrip("\n") + "\n")
        f.write("|".join(str(c) for c in df.columns) + "\n")
        for _, row in df.iterrows():
            f.write("|".join(str(v) for v in row.values) + "\n")
