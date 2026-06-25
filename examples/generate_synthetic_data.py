"""Generate synthetic shoreline shapefiles matching
examples/config_with_professionals.yaml.

Run this script once to produce a small, geometrically-known synthetic
dataset under examples/data/example_site/ -- it backs the
professionals/inter-analyst comparison demo, which needs 2+ independent
delineations of the same year that don't exist in real historical data.

examples/config_without_professionals.yaml does NOT need this script: it
ships with real historical shoreline shapefiles for the Allegan, MI site
under examples/data/allegan/ and works out of the box.

To use your own data, edit the `path:` entries in either example config to
point at your real shapefiles -- everything else (uncertainty components,
transect settings, etc.) stays the same.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

CRS = "EPSG:32616"
OUT_DIR = Path(__file__).parent / "data" / "example_site"


def make_shoreline(y_offset: float, x0: float = 0.0, x1: float = 2000.0, n: int = 120) -> LineString:
    xs = np.linspace(x0, x1, n)
    ys = y_offset + 4.0 * np.sin(xs / 250.0)
    return LineString(zip(xs, ys))


def write_line(line: LineString, year: int, path: Path) -> None:
    gdf = gpd.GeoDataFrame({"year": [year]}, geometry=[line], crs=CRS)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path)
    print(f"wrote {path}")


def main() -> None:
    # Primary analyst's shorelines: gradual retreat over time.
    write_line(make_shoreline(0.0), 2000, OUT_DIR / "shoreline_2000.shp")
    write_line(make_shoreline(-6.0), 2010, OUT_DIR / "shoreline_2010.shp")
    write_line(make_shoreline(-20.0), 2020, OUT_DIR / "shoreline_2020.shp")

    # Two independent ("professional") delineations of the 2000 shoreline,
    # each a small perturbation of the primary analyst's line.
    write_line(make_shoreline(0.7), 2000, OUT_DIR / "shoreline_2000_analyst_a.shp")
    write_line(make_shoreline(-0.9), 2000, OUT_DIR / "shoreline_2000_analyst_b.shp")


if __name__ == "__main__":
    main()
