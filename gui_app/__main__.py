"""Entry point: python -m gui_app"""
import os
import sys


def _fix_frozen_env():
    """Set GDAL_DATA / PROJ_DATA when running inside a PyInstaller bundle.

    PyInstaller extracts everything to a temporary _MEIPASS folder; rasterio
    and pyproj need to be told where their data directories landed.
    """
    if not getattr(sys, "frozen", False):
        return
    base = sys._MEIPASS
    for env_var, rel_path in [
        ("GDAL_DATA", os.path.join("rasterio", "gdal_data")),
        ("PROJ_DATA", os.path.join("pyproj", "proj_dir", "share", "proj")),
        ("PROJ_LIB",  os.path.join("pyproj", "proj_dir", "share", "proj")),
    ]:
        candidate = os.path.join(base, rel_path)
        if os.path.isdir(candidate):
            os.environ.setdefault(env_var, candidate)


_fix_frozen_env()

from gui_app.app import main  # noqa: E402

if __name__ == "__main__":
    main()
