# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata
from pathlib import Path

project = Path(SPECPATH).resolve()
backend = project.parents[1] / 'shared/python'

datas = []
binaries = [(str(project / 'qt_host/native_bin/xcp_core.dll'), 'qt_host/native_bin')]
hiddenimports = ['matplotlib.backends.backend_qtagg']
datas += collect_data_files('qt_host')
datas += copy_metadata('PySide6-Essentials')
datas += copy_metadata('shiboken6')
hiddenimports += collect_submodules('simrt_xcp')
tmp_ret = collect_all('pyxcp')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [str(project / 'main.py')],
    pathex=[str(project), str(backend)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'pyxcp_host.ui', 'PyQt5', 'PyQt6', 'PySide2', 'pyxcp.examples'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SimRT',
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
    version=str(project / 'version_info.txt'),
    icon=[str(project / 'qt_host/assets/simrt.ico')],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SimRT',
)
