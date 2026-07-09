# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['geopandas._compat', 'rasterio._shim', 'rasterio.crs', 'numpy', 'pandas', 'yaml', 'tqdm', 'requests', 'tkinter', 'tkinter.ttk', 'tkinter.scrolledtext', 'tkinter.filedialog', 'tkinter.messagebox']
tmp_ret = collect_all('shoreline_uncertainty')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rasterio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyproj')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('geopandas')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyogrio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('fiona')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('shapely')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\Users\\werne\\OneDrive\\Documents\\github\\shoreline_change_uncertainty\\gui_app\\__main__.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorflow', 'tensorflow_core', 'tensorflow_estimator', 'keras', 'keras_preprocessing', 'torch', 'torchvision', 'torchaudio', 'sklearn', 'sklearn.ensemble', 'sklearn.linear_model', 'skimage', 'cv2', 'matplotlib', 'IPython', 'ipykernel', 'ipywidgets', 'notebook', 'jupyterlab', 'pytest', 'sphinx', 'docutils'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ShorelineUncertainty',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ShorelineUncertainty',
)
