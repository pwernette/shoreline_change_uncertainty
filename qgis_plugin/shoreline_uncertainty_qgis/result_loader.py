"""Discovers a completed run's output vector/raster files and loads them as
QGIS map layers. Split out from plugin.py/runner.py so it's unit-testable
without a real Qt event loop or map canvas (the same carve-out pattern as
dialog.py's build_run_config): given just an output directory,
`discover_output_files`/`load_output_layers` are pure qgis.core-only
functions with no QDialog/iface dependency.

Which output files exist for a given site depends on which RunConfig flags
were set (epsilon-band method, prob_change, rate-of-change, etc.), so this
module doesn't hard-code an expected file list -- it just walks the output
directory for every vector (.shp/.gpkg/.geojson) and raster (.tif/.tiff)
file actually present and tries to load each one, silently skipping any
that fail to load (isValid() is False) rather than raising. A run that
produced no outputs (e.g. every optional stage disabled) simply yields an
empty layer list.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple, Union

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

_VECTOR_EXTENSIONS = {".shp", ".gpkg", ".geojson"}
_RASTER_EXTENSIONS = {".tif", ".tiff"}


def discover_output_files(output_dir: Union[str, Path]) -> Tuple[List[Path], List[Path]]:
    """Recursively find every vector/raster output file under `output_dir`
    (e.g. <output_dir>/<site_name>/*.shp, */*.tif), sorted for deterministic
    ordering. Returns (vector_paths, raster_paths). A missing directory
    (e.g. a run that failed before writing anything) returns ([], [])
    rather than raising.
    """
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return [], []
    vector_paths = sorted(
        p for p in output_dir.rglob("*") if p.is_file() and p.suffix.lower() in _VECTOR_EXTENSIONS
    )
    raster_paths = sorted(
        p for p in output_dir.rglob("*") if p.is_file() and p.suffix.lower() in _RASTER_EXTENSIONS
    )
    return vector_paths, raster_paths


def load_output_layers(
    output_dir: Union[str, Path], project: Optional["QgsProject"] = None
) -> List[object]:
    """Build a QgsVectorLayer/QgsRasterLayer for every discovered output
    file under `output_dir`, skipping any that fail to load, and add the
    valid ones to `project` (if given) so they show up in the QGIS map
    canvas.

    Layer names are derived from each file's stem (e.g. "transects" for
    transects.shp) -- good enough for a first pass; nothing stops the
    caller from renaming layers afterward (e.g. prefixing with the site
    name when a run covers multiple sites).

    Returns the list of valid layers actually built (and added to
    `project`, if one was given).
    """
    vector_paths, raster_paths = discover_output_files(output_dir)
    layers: List[object] = []

    for path in vector_paths:
        layer = QgsVectorLayer(str(path), path.stem, "ogr")
        if layer.isValid():
            layers.append(layer)

    for path in raster_paths:
        layer = QgsRasterLayer(str(path), path.stem)
        if layer.isValid():
            layers.append(layer)

    if project is not None:
        for layer in layers:
            project.addMapLayer(layer)

    return layers
