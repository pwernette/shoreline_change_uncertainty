"""
Build a standalone single-file executable using PyInstaller.

Requirements
------------
    pip install pyinstaller

Usage
-----
From the repo root::

    python gui_app/build_exe.py

The output binary lands in  dist/ShorelineUncertainty(.exe on Windows).

PyInstaller hidden-imports
--------------------------
geopandas, rasterio, shapely, pyogrio, fiona, and friends all use dynamic
imports that PyInstaller can't auto-detect. The spec below lists the most
common ones; add more to HIDDEN if you hit ImportError at runtime.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

HIDDEN = [
    "shoreline_uncertainty",
    "shoreline_uncertainty.config",
    "shoreline_uncertainty.pipeline",
    "shoreline_uncertainty.uncertainty",
    "shoreline_uncertainty.epsilon_bands",
    "shoreline_uncertainty.transects",
    "shoreline_uncertainty.critical_areas",
    "shoreline_uncertainty.raster_output",
    "shoreline_uncertainty.probability_surface",
    "shoreline_uncertainty.rate_of_change",
    "shoreline_uncertainty.water_level",
    "shoreline_uncertainty.io_utils",
    "shoreline_uncertainty.geometry_utils",
    "shoreline_uncertainty.cli",
    "geopandas",
    "geopandas._compat",
    "rasterio",
    "rasterio._shim",
    "rasterio.crs",
    "shapely",
    "shapely.geometry",
    "pyogrio",
    "fiona",
    "pyproj",
    "numpy",
    "pandas",
    "yaml",
    "tqdm",
    "requests",
    "tkinter",
    "tkinter.ttk",
    "tkinter.scrolledtext",
    "tkinter.filedialog",
    "tkinter.messagebox",
]

hidden_args = []
for h in HIDDEN:
    hidden_args += ["--hidden-import", h]

cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--windowed",                    # suppress the console window on Windows/macOS
    "--name", "ShorelineUncertainty",
    "--add-data", f"{ROOT / 'shoreline_uncertainty'}{':' if sys.platform != 'win32' else ';'}shoreline_uncertainty",
    *hidden_args,
    str(ROOT / "gui_app" / "__main__.py"),
]

print("Running:", " ".join(cmd))
subprocess.run(cmd, check=True)
print("\nBuild complete. Binary is in dist/ShorelineUncertainty")
