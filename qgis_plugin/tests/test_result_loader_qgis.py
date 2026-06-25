"""Tests for result_loader.py's discover_output_files/load_output_layers --
the "load results into map canvas" half of task #76. Builds real on-disk
shapefiles (via geopandas, same as conftest.py's synthetic_site fixture)
and GeoTIFFs (via rasterio) so qgis_stub.py's QgsVectorLayer/QgsRasterLayer
round-trip through real files, exactly like they will against this
plugin's actual pipeline outputs.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point

from shoreline_uncertainty_qgis.result_loader import discover_output_files, load_output_layers


def _write_shapefile(path, crs="EPSG:32616"):
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Point(0, 0)], crs=crs)
    gdf.to_file(path)


def _write_geotiff(path, crs="EPSG:32616"):
    transform = from_origin(0, 0, 1, 1)
    arr = np.zeros((5, 5), dtype="uint8")
    with rasterio.open(
        path, "w", driver="GTiff", height=5, width=5, count=1, dtype="uint8", crs=crs, transform=transform
    ) as dst:
        dst.write(arr, 1)


# ---------------------------------------------------------------------------
# discover_output_files
# ---------------------------------------------------------------------------


def test_discover_output_files_finds_vector_and_raster(tmp_path):
    site_dir = tmp_path / "synthetic_site"
    site_dir.mkdir()
    _write_shapefile(site_dir / "transects.shp")
    _write_geotiff(site_dir / "similarity_index.tif")
    (site_dir / "odb_overlapping_buffer_table.csv").write_text("a,b\n1,2\n")  # ignored: not vector/raster

    vector_paths, raster_paths = discover_output_files(tmp_path)

    assert [p.name for p in vector_paths] == ["transects.shp"]
    assert [p.name for p in raster_paths] == ["similarity_index.tif"]


def test_discover_output_files_missing_dir_returns_empty(tmp_path):
    vector_paths, raster_paths = discover_output_files(tmp_path / "does_not_exist")
    assert vector_paths == []
    assert raster_paths == []


def test_discover_output_files_sorted_across_multiple_sites(tmp_path):
    for site in ("site_b", "site_a"):
        site_dir = tmp_path / site
        site_dir.mkdir()
        _write_shapefile(site_dir / "transects.shp")

    vector_paths, _ = discover_output_files(tmp_path)
    assert [p.parent.name for p in vector_paths] == ["site_a", "site_b"]


# ---------------------------------------------------------------------------
# load_output_layers
# ---------------------------------------------------------------------------


def test_load_output_layers_builds_valid_layers(tmp_path):
    from qgis.core import QgsRasterLayer, QgsVectorLayer

    site_dir = tmp_path / "synthetic_site"
    site_dir.mkdir()
    _write_shapefile(site_dir / "transects.shp")
    _write_geotiff(site_dir / "similarity_index.tif")

    layers = load_output_layers(tmp_path)

    assert len(layers) == 2
    assert any(isinstance(l, QgsVectorLayer) for l in layers)
    assert any(isinstance(l, QgsRasterLayer) for l in layers)
    assert all(l.isValid() for l in layers)


def test_load_output_layers_skips_invalid_files(tmp_path):
    site_dir = tmp_path / "synthetic_site"
    site_dir.mkdir()
    (site_dir / "corrupt.shp").write_text("not a real shapefile")
    (site_dir / "corrupt.tif").write_text("not a real geotiff")
    _write_shapefile(site_dir / "transects.shp")  # one valid file alongside the corrupt ones

    layers = load_output_layers(tmp_path)

    assert len(layers) == 1
    assert layers[0].name() == "transects"


def test_load_output_layers_adds_to_given_project(tmp_path):
    from qgis.core import QgsProject

    site_dir = tmp_path / "synthetic_site"
    site_dir.mkdir()
    _write_shapefile(site_dir / "transects.shp")
    _write_geotiff(site_dir / "similarity_index.tif")

    project = QgsProject()  # fresh instance, not the process-wide singleton
    layers = load_output_layers(tmp_path, project=project)

    assert project.mapLayers() == layers
    assert len(layers) == 2


def test_load_output_layers_no_outputs_returns_empty_list(tmp_path):
    assert load_output_layers(tmp_path) == []
