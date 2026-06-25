"""Injects the shapely/GEOS-backed `qgis` stub (qgis_stub.py) into
sys.modules before any test imports `shoreline_uncertainty_qgis` modules --
this sandbox has no real QGIS install, so `import qgis.core` would
otherwise fail outright. See qgis_stub.py's module docstring for why this
exists and what it does/doesn't validate.
"""
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_PLUGIN_DIR = _TESTS_DIR.parent  # qgis_plugin/ -- parent of shoreline_uncertainty_qgis/

for p in (str(_PLUGIN_DIR), str(_TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import qgis_stub  # noqa: E402

qgis_stub.install()

# ---------------------------------------------------------------------------
# Synthetic shapefile fixtures, mirroring tests/conftest.py (the standalone
# package's equivalent) verbatim -- pure geopandas code, reusable as-is here
# because qgis_stub's QgsVectorLayer(..., "ogr") provider reads shapefiles
# via gpd.read_file internally, so these real on-disk shapefiles round-trip
# through the stub transparently. See tests/conftest.py for design notes.
# ---------------------------------------------------------------------------

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:32616"


def make_shoreline(y_offset: float, x0: float = 0.0, x1: float = 1000.0, n: int = 60) -> LineString:
    xs = np.linspace(x0, x1, n)
    ys = y_offset + 2.0 * np.sin(xs / 120.0)
    return LineString(zip(xs, ys))


@pytest.fixture
def synthetic_years():
    return {2000: (0.0, 2.0), 2010: (-5.0, 2.0), 2020: (-15.0, 12.0)}


@pytest.fixture
def synthetic_site(tmp_path, synthetic_years):
    paths = {}
    radii = {}
    for year, (offset, radius) in synthetic_years.items():
        line = make_shoreline(offset)
        gdf = gpd.GeoDataFrame({"year": [year]}, geometry=[line], crs=CRS)
        path = tmp_path / f"shoreline_{year}.shp"
        gdf.to_file(path)
        paths[year] = str(path)
        radii[year] = radius
    return {"paths": paths, "radii": radii, "tmp_path": tmp_path, "crs": CRS}


@pytest.fixture
def synthetic_professionals(tmp_path):
    base_year = 2000
    offsets = {"acmoody": 0.5, "goodwin": -0.5, "lusch": 1.5}
    paths = {}
    for name, off in offsets.items():
        line = make_shoreline(off)
        gdf = gpd.GeoDataFrame({"year": [base_year]}, geometry=[line], crs=CRS)
        path = tmp_path / f"shoreline_{base_year}_{name}.shp"
        gdf.to_file(path)
        paths[name] = str(path)
    return {"year": base_year, "paths": paths}
