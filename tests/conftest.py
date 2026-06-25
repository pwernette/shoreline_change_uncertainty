"""Shared pytest fixtures: synthetic shoreline data.

No real shapefiles are bundled with this repo (none were available at
development time), so tests build small, geometrically-known synthetic
shorelines on the fly. They use the same column/CRS conventions real data
would, so swapping in real shapefiles later only requires pointing the
config's `shorelines[].path` entries at the new files.
"""
from __future__ import annotations

import numpy as np
import geopandas as gpd
import pytest
from shapely.geometry import LineString

CRS = "EPSG:32616"  # arbitrary UTM zone; only used as a metric (meters) CRS here


def make_shoreline(y_offset: float, x0: float = 0.0, x1: float = 1000.0, n: int = 60) -> LineString:
    """A gently wavy, roughly east-west line offset in Y by `y_offset` -- a
    stand-in for one year's digitized shoreline."""
    xs = np.linspace(x0, x1, n)
    ys = y_offset + 2.0 * np.sin(xs / 120.0)
    return LineString(zip(xs, ys))


@pytest.fixture
def synthetic_years():
    """Year -> (y_offset_meters, rmse95_radius_meters).

    2000 -> 2010: shoreline retreats 5m, well beyond the combined ~4m
            uncertainty buffer -> should register as significant change.
    2010 -> 2020: shoreline retreats another 10m (15m total) with a much
            larger 12m uncertainty radius -> buffers mostly overlap ->
            should NOT register as significant at a strict threshold.
    """
    return {
        2000: (0.0, 2.0),
        2010: (-5.0, 2.0),
        2020: (-15.0, 12.0),
    }


@pytest.fixture
def synthetic_site(tmp_path, synthetic_years):
    """Write each synthetic year's shoreline to its own shapefile and return
    everything a test needs to build a SiteConfig/RunConfig against them."""
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
    """Three independently-delineated ('professional') shorelines for a
    single year, each a small, known perturbation of the same base line."""
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
