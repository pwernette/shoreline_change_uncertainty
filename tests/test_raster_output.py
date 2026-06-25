import numpy as np
import rasterio
from shapely.geometry import LineString

from shoreline_uncertainty.epsilon_bands import overlapping_double_buffer
from shoreline_uncertainty.raster_output import (
    build_grid_transform,
    build_similarity_surface,
    rasterize_geometry,
    write_raster,
)


def test_build_grid_transform_dimensions():
    transform, width, height = build_grid_transform((0, 0, 100, 50), cell_size=10)
    assert width == 10
    assert height == 5


def test_rasterize_geometry_marks_cells():
    transform, width, height = build_grid_transform((0, 0, 10, 10), cell_size=1)
    geom = LineString([(0, 5), (10, 5)]).buffer(1)
    mask = rasterize_geometry(geom, transform, width, height)
    assert mask.shape == (height, width)
    assert mask.sum() > 0


def test_rasterize_geometry_empty_geom_returns_all_fill():
    from shapely.geometry import Polygon
    transform, width, height = build_grid_transform((0, 0, 10, 10), cell_size=1)
    empty_geom = Polygon()
    mask = rasterize_geometry(empty_geom, transform, width, height, fill=0)
    assert mask.sum() == 0


def test_build_similarity_surface_significant_pair_has_nonzero_significant():
    line_a = LineString([(0, 0), (100, 0)])
    line_b = LineString([(0, 20), (100, 20)])  # far apart -> definitely significant
    odb = overlapping_double_buffer(line_a, 1.0, line_b, 1.0, threshold=0.05)
    similarity, significant, transform = build_similarity_surface([odb], cell_size=1.0)
    assert similarity.sum() > 0
    assert significant.sum() > 0
    assert odb.significant_change is True


def test_build_similarity_surface_non_significant_pair_has_no_significant_cells():
    line = LineString([(0, 0), (100, 0)])
    odb = overlapping_double_buffer(line, 5.0, line, 5.0, threshold=0.05)  # identical -> Ps=1
    assert odb.significant_change is False
    similarity, significant, transform = build_similarity_surface([odb], cell_size=1.0)
    assert significant.sum() == 0
    assert similarity.sum() > 0


def test_write_raster_roundtrip(tmp_path):
    line_a = LineString([(0, 0), (100, 0)])
    line_b = LineString([(0, 20), (100, 20)])
    odb = overlapping_double_buffer(line_a, 1.0, line_b, 1.0, threshold=0.05)
    similarity, significant, transform = build_similarity_surface([odb], cell_size=2.0)
    out_path = tmp_path / "similarity_index.tif"
    write_raster(similarity, transform, "EPSG:32616", out_path)
    assert out_path.exists()
    with rasterio.open(out_path) as src:
        data = src.read(1)
        assert data.shape == similarity.shape
        assert np.array_equal(data, similarity)
        assert src.crs is not None
