"""QGIS-native port of shoreline_uncertainty/io_utils.py.

Reading/reprojecting/writing vector data via `qgis.core` (which wraps
GDAL/OGR internally, the same library geopandas/Fiona/pyogrio wrap) instead
of geopandas, so this plugin needs no extra Python packages beyond what
ships inside QGIS itself.

Replaces original_program/arcgis_pro/create_fc.py the same way the
standalone package's io_utils.py does -- QGIS creates output vector files on
demand when written, so no pre-creation step is needed.

Design note: read_shoreline returns a QgsVectorLayer (QGIS's native
in-memory/on-disk vector container) rather than a GeoDataFrame. Downstream
ported modules (epsilon_bands_qgis, transects_qgis, etc.) work feature-by-
feature on plain QgsGeometry objects -- closer to how the original arcpy
scripts iterated cursors than to geopandas' whole-table operations -- and
get assembled back into a QgsVectorLayer only when writing output, via
`write_vector`.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from .geometry_utils_qgis import dissolve


def read_shoreline(path: str | Path) -> QgsVectorLayer:
    """Load a shoreline (or any other vector) file via QGIS's OGR provider
    and require it to carry a defined CRS -- every downstream length/area/
    buffer/distance calculation in this package assumes a known, ideally
    projected, coordinate system, so a missing CRS is treated as an error
    here rather than silently assumed."""
    path = Path(path)
    layer = QgsVectorLayer(str(path), path.stem, "ogr")
    if not layer.isValid():
        raise ValueError(f"{path} could not be loaded as a vector layer (invalid OGR source).")
    if not layer.crs().isValid():
        raise ValueError(f"{path} has no CRS defined; set one before processing.")
    return layer


def layer_geometries(layer: QgsVectorLayer) -> List[QgsGeometry]:
    """All feature geometries in a layer, as a plain list -- the common
    starting point for the feature-by-feature ported modules."""
    return [f.geometry() for f in layer.getFeatures()]


def utm_epsg_for(layer: QgsVectorLayer) -> int:
    """Pick a UTM EPSG code from a geographic layer's centroid."""
    merged = dissolve(layer_geometries(layer))
    centroid = merged.centroid().asPoint()
    lon, lat = centroid.x(), centroid.y()
    zone = int((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone


def _to_qgis_crs(value: str | int) -> QgsCoordinateReferenceSystem:
    """QgsCoordinateReferenceSystem's string constructor needs an
    `EPSG:1234`-style authid -- it doesn't accept a bare int or a bare
    numeral string the way pyproj.CRS.from_user_input does. Config files
    (YAML) commonly hand us either form (`target_crs: EPSG:32616` parses as
    a str, `target_crs: 32616` parses as a bare int), so normalize both to
    a proper authid here rather than pushing that distinction onto every
    caller."""
    s = str(value)
    if s.lstrip("-").isdigit():
        s = f"EPSG:{s}"
    return QgsCoordinateReferenceSystem(s)


def ensure_projected(
    layer: QgsVectorLayer, target_crs: Optional[str | int] = None
) -> QgsVectorLayer:
    """Reproject to a metric CRS suitable for area/length/buffer math.

    If `target_crs` is given, use it. Otherwise auto-detect a UTM zone when
    the input is geographic; pass through unchanged if already projected.

    Implemented as a direct QgsCoordinateTransform feature-by-feature copy
    (rather than `processing.run('native:reprojectlayer', ...)`) so this
    helper works standalone without requiring the Processing framework to
    be initialized -- the Processing algorithm wrapper (a later step) can
    still call this same function from inside a registered algorithm.
    """
    src_crs = layer.crs()
    if target_crs:
        dst_crs = _to_qgis_crs(target_crs)
    elif src_crs.isGeographic():
        dst_crs = QgsCoordinateReferenceSystem(f"EPSG:{utm_epsg_for(layer)}")
    else:
        dst_crs = src_crs

    if dst_crs == src_crs:
        return layer.clone() if hasattr(layer, "clone") else layer

    transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())

    out = QgsVectorLayer(
        f"{layer.wkbType()}?crs={dst_crs.authid()}",
        f"{layer.name()}_projected",
        "memory",
    )
    out.dataProvider().addAttributes(layer.fields())
    out.updateFields()

    out_feats = []
    for feat in layer.getFeatures():
        new_feat = QgsFeature(feat)
        geom = QgsGeometry(feat.geometry())
        geom.transform(transform)
        new_feat.setGeometry(geom)
        out_feats.append(new_feat)
    out.dataProvider().addFeatures(out_feats)
    out.updateExtents()
    return out


def write_vector(
    layer: Optional[QgsVectorLayer], path: str | Path, driver: Optional[str] = None
) -> None:
    """Write a vector layer to `path` (e.g. a .shp), creating parent
    directories as needed. `driver` defaults to whatever
    QgsVectorFileWriter infers from the file extension (ESRI Shapefile for
    .shp). Silently does nothing for a None/empty layer, since several
    pipeline stages are optional and may produce no features -- callers
    don't need to guard every write_vector call with an emptiness check
    themselves."""
    if layer is None or layer.featureCount() == 0:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    options = QgsVectorFileWriter.SaveVectorOptions()
    if driver:
        options.driverName = driver
    else:
        options.driverName = QgsVectorFileWriter.driverForExtension(path.suffix)

    error, message = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(path), layer.transformContext(), options
    )
    if error != QgsVectorFileWriter.NoError:
        raise IOError(f"Failed writing {path}: {message}")


def build_memory_layer(
    geometries: List[QgsGeometry],
    fields,
    attributes: List[Tuple],
    geometry_kind: str,
    crs: QgsCoordinateReferenceSystem,
    name: str = "layer",
) -> QgsVectorLayer:
    """Assemble a list of (geometry, attribute-tuple) pairs into an
    in-memory QgsVectorLayer -- the QGIS-native equivalent of building a
    GeoDataFrame from a list of records, used by every ported module that
    produces vector output (epsilon bands, transects, critical areas,
    rate-change polygons, etc.) before handing it to `write_vector`."""
    uri = f"{geometry_kind}?crs={crs.authid()}"
    layer = QgsVectorLayer(uri, name, "memory")
    provider = layer.dataProvider()
    provider.addAttributes(fields)
    layer.updateFields()

    feats = []
    for geom, attrs in zip(geometries, attributes):
        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        feat.setAttributes(list(attrs))
        feats.append(feat)
    provider.addFeatures(feats)
    layer.updateExtents()
    return layer


def write_table_csv(df: pd.DataFrame, path: str | Path) -> None:
    """Write a DataFrame to `path` as CSV (no index column), creating
    parent directories as needed. Pure pandas, copied verbatim from the
    standalone package's io_utils.write_table_csv -- no qgis dependency."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_table_pipe_log(df: pd.DataFrame, path: str | Path, header_lines: Optional[list] = None) -> None:
    """Write a pipe-delimited .txt log, mirroring the original scripts' log
    format (e.g. copy_output_table.py, intersecting_epsilon_bands.py). Pure
    pandas, copied verbatim from the standalone package's
    io_utils.write_table_pipe_log -- no qgis dependency."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for line in header_lines or []:
            f.write(line.rstrip("\n") + "\n")
        f.write("|".join(str(c) for c in df.columns) + "\n")
        for _, row in df.iterrows():
            f.write("|".join(str(v) for v in row.values) + "\n")
