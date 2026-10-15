# -*- mode: python ; coding: utf-8 -*-
# Portable (one-folder) build of the v2 app. Run through packaging/build_portable.py,
# which also trims the folder and adds the launchers.
from pathlib import Path

ROOT = Path(SPECPATH).parent
V2 = ROOT / 'appSlicerSegelin' / 'v2'

# every non-Python file of the v2 package (themes, 3D web viewer, machine model), keeping its package path
datas = [(str(p), str(p.parent.relative_to(ROOT))) for p in V2.rglob('*')
         if p.is_file() and p.suffix not in {'.py', '.pyc'} and '__pycache__' not in p.parts]

a = Analysis(
    [str(V2 / '__main__.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=['pyqtgraph.opengl', 'OpenGL.platform.win32', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebEngineCore'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pandas', 'scipy', 'IPython', 'pytest', 'PyQt5', 'PySide2', 'PySide6',
              'PyQt6.QtQuick3D', 'PyQt6.QtMultimedia', 'PyQt6.QtBluetooth', 'PyQt6.QtNfc', 'PyQt6.QtSensors',
              'PyQt6.QtSerialPort', 'PyQt6.QtDesigner', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets', 'PyQt6.QtSql',
              'PyQt6.QtTest', 'PyQt6.QtHelp', 'PyQt6.QtRemoteObjects', 'PyQt6.QtTextToSpeech',
              'pyqtgraph.examples', 'pyqtgraph.jupyter'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SlicerSegelin',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='SlicerSegelin',
)
