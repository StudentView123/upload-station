# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Upload Station (onedir, windowed).

Builds dist/UploadStation/UploadStation.exe with Python embedded. The Orthanc
binaries and config.json are NOT bundled here — the Inno Setup installer places
them next to the executable in the install directory, and the app resolves them
via station.config.app_dir().
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = os.path.abspath(os.path.join(SPECPATH, os.pardir))

datas = []
binaries = []
hiddenimports = []

# Pull in packages that PyInstaller's static analysis tends to miss because they
# import submodules lazily (uvicorn workers, pydicom encoders, etc.).
for pkg in ("uvicorn", "fastapi", "starlette", "pydicom", "anyio"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    [os.path.join(REPO, "run.py")],
    pathex=[REPO],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "tkinter", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UploadStation",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name="UploadStation",
)
