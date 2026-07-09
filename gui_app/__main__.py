"""Entry point: python -m gui_app"""
import os
import sys


def _fix_frozen_env():
    """Set GDAL_DATA / PROJ_DATA when running inside a PyInstaller bundle.

    PyInstaller extracts everything to sys._MEIPASS at runtime. rasterio and
    pyproj ship their own copies of the GDAL and PROJ data files, but the env
    vars that point to them are not set automatically in a frozen binary.
    Without GDAL_DATA, GDAL emits 'Warning 3: Cannot find gdalvrt.xsd' and
    some projections may silently fail.
    """
    if not getattr(sys, "frozen", False):
        return  # not a frozen bundle — nothing to do

    base = sys._MEIPASS  # root of the extracted bundle

    # rasterio ships gdal-data inside its package directory
    for candidate in (
        os.path.join(base, "rasterio", "gdal-data"),
        os.path.join(base, "gdal-data"),
    ):
        if os.path.isdir(candidate):
            os.environ.setdefault("GDAL_DATA", candidate)
            break

    # pyproj ships its PROJ database inside its package directory
    for candidate in (
        os.path.join(base, "pyproj", "proj_dir", "share", "proj"),
        os.path.join(base, "proj"),
    ):
        if os.path.isdir(candidate):
            os.environ.setdefault("PROJ_DATA", candidate)
            os.environ.setdefault("PROJ_LIB", candidate)
            break


_fix_frozen_env()

from gui_app.app import ShorelineUncertaintyApp  # noqa: E402


def main():
    app = ShorelineUncertaintyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
