# Testing this plugin without a real QGIS install

This development sandbox has no QGIS, no PyQt5/PyQt6, no conda, and no root
access -- so the real `qgis.core`/`qgis.gui`/`qgis.PyQt`/`processing`
modules can't be imported or installed here (there is no real PyPI `qgis`
wheel; PyQGIS only ships bundled inside a full QGIS desktop install).

To still unit-test the ported algorithm *logic* in this environment, the
tests in this directory run against `qgis_stub.py`: a small stand-in for
the handful of `qgis.core` classes the ported modules actually call,
backed by shapely/GEOS (the same geometry engine real `QgsGeometry` uses
internally) and geopandas/pyproj for the vector-layer/CRS pieces.
`conftest.py` installs it into `sys.modules` before any test imports
`shoreline_uncertainty_qgis`.

**What passing these tests confirms:** the math/algorithm logic (buffer
overlap ratios, vertex-distance stats, CRS auto-detection, reprojection,
read/write roundtrips, etc.) is correct.

**What it does NOT confirm:** that every real `qgis.core` call is spelled
and used correctly, that the plugin loads in QGIS's plugin manager, that
the Processing algorithm registers correctly, or that the dialog renders
and behaves correctly under real PyQt5 (QGIS 3.x) or PyQt6 (QGIS 4.0+).
Those need a real load-and-run check inside actual QGIS -- see the
top-level plugin README (added once the plugin is far enough along to be
worth loading) for exact steps.
