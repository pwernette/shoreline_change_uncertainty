"""SURF: Shoreline Uncertainty and Rate Framework.

Arcpy-free implementation of the shoreline change uncertainty methods
described in Wernette et al. (2017) and Wernette et al. (2020). Built
entirely on geopandas/shapely/pyproj (vector core) and rasterio (raster
surfaces) -- no ESRI ArcGIS/arcpy dependency anywhere in this package.

See MIGRATION.md for a map of each original original_program/arcgis_pro/*.py
script to its replacement here.
"""

from .config import RunConfig, SiteConfig, ShorelineYear, UncertaintyComponents, load_config
from .pipeline import run_pipeline, run_site

__all__ = [
    "RunConfig",
    "SiteConfig",
    "ShorelineYear",
    "UncertaintyComponents",
    "load_config",
    "run_pipeline",
    "run_site",
]

__version__ = "0.1.0"
