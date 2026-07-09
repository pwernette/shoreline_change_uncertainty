"""
Build a standalone directory-based executable using PyInstaller.

Requirements
------------
    pip install pyinstaller

Usage
-----
From the repo root::

    python gui_app/build_exe.py

Output lands in dist_exe/ShorelineUncertainty/ as a folder containing the
binary plus all dependencies.  To launch:

    Linux / macOS : dist_exe/ShorelineUncertainty/ShorelineUncertainty
    Windows       : dist_exe\\ShorelineUncertainty\\ShorelineUncertainty.exe

Distribute the entire dist_exe/ShorelineUncertainty/ folder (zip it up, or use
an installer tool such as NSIS on Windows or AppImage on Linux).

Note: dist_exe/ is intentionally separate from dist_pypi/ (PyPI wheel/sdist
output).  Keep them in different directories so ``python -m build`` and
PyInstaller do not interfere with each other.

OneDrive / cloud-sync note
--------------------------
All PyInstaller build files (work AND dist) are written to a temporary
directory outside the repo so that OneDrive or any other sync daemon cannot
lock them mid-build.  The finished folder is then copied back into the repo
using a robust delete that falls back to ``cmd /c rd /s /q`` on Windows if
shutil.rmtree is blocked by an OneDrive file lock.

Why --onedir and not --onefile?
--------------------------------
The geospatial stack (geopandas + rasterio + GDAL + shapely + pyproj) bundled
from a conda environment easily exceeds 4 GB.  PyInstaller's --onefile format
uses a 32-bit unsigned integer for byte offsets inside its CArchive, so it
raises ``struct.error: 'I' format requires 0 <= number <= 4294967295`` once
the total exceeds that limit.  --onedir writes plain files and has no such
limit.

PyInstaller hidden-imports
--------------------------
geopandas, rasterio, shapely, pyogrio, fiona, and friends all use dynamic
imports that PyInstaller cannot auto-detect.  The lists below cover the most
common ones; add more to HIDDEN if you hit ImportError at runtime.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent

# --collect-all recursively collects all submodules AND data files for a
# package.  Use this (not --hidden-import) for local packages and for
# packages like rasterio/pyproj that ship binary data alongside their Python.
COLLECT_ALL = [
    "shoreline_uncertainty",   # the analysis package -- local, must be collected
    "rasterio",                # ships gdal-data/ inside the package directory
    "pyproj",                  # ships its PROJ database inside the package directory
    "geopandas",
    "pyogrio",
    "fiona",
    "shapely",
]

# --hidden-import for pure-Python packages that PyInstaller sometimes misses
# due to dynamic/lazy imports but do not need data-file collection.
HIDDEN = [
    "geopandas._compat",
    "rasterio._shim",
    "rasterio.crs",
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

# Packages to explicitly exclude.  PyInstaller scans the entire conda/venv
# site-packages, so anything installed for other projects gets dragged in
# unless excluded here.  This package uses none of the following.
EXCLUDE = [
    "tensorflow",
    "tensorflow_core",
    "tensorflow_estimator",
    "keras",
    "keras_preprocessing",
    "torch",
    "torchvision",
    "torchaudio",
    "sklearn",
    "sklearn.ensemble",
    "sklearn.linear_model",
    "skimage",
    "cv2",
    "matplotlib",
    "IPython",
    "ipykernel",
    "ipywidgets",
    "notebook",
    "jupyterlab",
    "pytest",
    "sphinx",
    "docutils",
]

collect_args = []
for c in COLLECT_ALL:
    collect_args += ["--collect-all", c]

hidden_args = []
for h in HIDDEN:
    hidden_args += ["--hidden-import", h]

exclude_args = []
for e in EXCLUDE:
    exclude_args += ["--exclude-module", e]

FINAL_DIST = ROOT / "dist_exe" / "ShorelineUncertainty"


def _force_remove(path: Path) -> None:
    """Remove a directory tree robustly.

    OneDrive (and other sync daemons) can hold file handles open inside a
    previously-synced dist folder, causing shutil.rmtree to raise
    PermissionError.  On Windows we fall back to ``cmd /c rd /s /q`` which
    bypasses those userspace locks.
    """
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except PermissionError:
        if sys.platform == "win32":
            print("shutil.rmtree blocked (OneDrive lock?); retrying with rd /s /q ...")
            subprocess.run(
                ["cmd", "/c", "rd", "/s", "/q", str(path)],
                check=True,
            )
        else:
            raise


# Build everything in system temp so OneDrive never touches any build files.
# The finished folder is copied back into the repo afterwards.
with tempfile.TemporaryDirectory(prefix="pyi_build_") as tmp_root:
    tmp_work = Path(tmp_root) / "work"
    tmp_dist = Path(tmp_root) / "dist"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",                     # folder bundle -- no 4 GB archive limit
        "--windowed",                   # suppress console window on Windows/macOS
        "--noconfirm",                  # no interactive prompt
        "--name", "ShorelineUncertainty",
        "--distpath", str(tmp_dist),    # output stays in temp
        "--workpath", str(tmp_work),    # intermediate files stay in temp
        *collect_args,
        *hidden_args,
        *exclude_args,
        str(ROOT / "gui_app" / "__main__.py"),
    ]

    print("Running:", " ".join(cmd))
    print(f"(all build files -> {tmp_root})")
    subprocess.run(cmd, check=True)

    src = tmp_dist / "ShorelineUncertainty"
    print(f"\nCopying {src} -> {FINAL_DIST} ...")
    _force_remove(FINAL_DIST)
    shutil.copytree(src, FINAL_DIST)

print("\nBuild complete.")
print(f"Folder : dist_exe/ShorelineUncertainty/")
ext = ".exe" if sys.platform == "win32" else ""
print(f"Launch : dist_exe/ShorelineUncertainty/ShorelineUncertainty{ext}")
