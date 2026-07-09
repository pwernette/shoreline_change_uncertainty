# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/mnt/c/users/werne/onedrive/documents/github/shoreline_change_uncertainty/gui_app/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[('/mnt/c/users/werne/onedrive/documents/github/shoreline_change_uncertainty/shoreline_uncertainty', 'shoreline_uncertainty')],
    hiddenimports=['shoreline_uncertainty', 'shoreline_uncertainty.config', 'shoreline_uncertainty.pipeline', 'shoreline_uncertainty.uncertainty', 'shoreline_uncertainty.epsilon_bands', 'shoreline_uncertainty.transects', 'shoreline_uncertainty.critical_areas', 'shoreline_uncertainty.raster_output', 'shoreline_uncertainty.probability_surface', 'shoreline_uncertainty.rate_of_change', 'shoreline_uncertainty.water_level', 'shoreline_uncertainty.io_utils', 'shoreline_uncertainty.geometry_utils', 'shoreline_uncertainty.cli', 'geopandas', 'geopandas._compat', 'rasterio', 'rasterio._shim', 'rasterio.crs', 'shapely', 'shapely.geometry', 'pyogrio', 'fiona', 'pyproj', 'numpy', 'pandas', 'yaml', 'tqdm', 'requests', 'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext', 'tkinter.filedialog', 'tkinter.messagebox'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ShorelineUncertainty',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
