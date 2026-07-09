"""shoreline_uncertainty: arcpy-free reimplementation of the analysis behind
Wernette et al. (2017), "Accounting for positional uncertainty in historical
shoreline change analysis without ground reference information."

Built entirely on geopandas/shapely/pyproj (vector core, wrapping GDAL/OGR)
plus rasterio (gridded uncertainty/similarity-index surfaces) -- no ESRI
ArcGIS / arcpy dependency anywhere in this package.

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
