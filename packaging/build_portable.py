"""Build the portable Windows folder (copy it to a USB stick and run SlicerSegelin.exe).

    .venv/Scripts/python.exe packaging/build_portable.py [--zip]

Output: ``dist/SlicerSegelin/`` — the app, a "compatible mode" launcher for
computers where the studio 3D view can't start, and a short LEEME.txt.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "SlicerSegelin"

# Chromium UI locales and Qt translations we keep (the app's UI is English; Spanish for system dialogs)
KEEP_LOCALES = {"en-US.pak", "es.pak", "es-419.pak"}
KEEP_QM_PREFIX = ("qt_es", "qtbase_es", "qt_en", "qtbase_en", "qtwebengine_es", "qtwebengine_en")
# never needed at run time: Chromium devtools and Qt's large unused modules
DROP_FILES = ("qtwebengine_devtools_resources.pak", "qtwebengine_devtools_resources.debug.pak")
DROP_DLL_PREFIX = ("Qt6Quick3D", "Qt6Pdf", "Qt6Multimedia", "Qt6Bluetooth", "Qt6Nfc", "Qt6Sensors",
                   "Qt6SerialPort", "Qt6Designer", "Qt6Sql", "Qt6Test", "Qt6Help", "Qt6RemoteObjects",
                   "Qt6TextToSpeech", "Qt6SpatialAudio", "Qt6Charts", "Qt6DataVisualization", "Qt6Graphs",
                   "Qt6VirtualKeyboard", "Qt6ShaderTools", "Qt6QuickTest", "Qt6Quick3DPhysics")

LAUNCHER = r"""@echo off
rem Modo compatible: vista 3D simple (OpenGL por software). Usar si la vista 3D normal no arranca.
set SEGELIN_3D=opengl
set QT_OPENGL=software
start "" "%~dp0SlicerSegelin.exe" %*
"""

README = """SlicerSegelin — versión portable
================================

Abrir: doble clic en SlicerSegelin.exe. No hace falta instalar nada: la carpeta
entera se puede copiar a un pendrive y usar en cualquier PC con Windows 10/11 (64 bits).

Vista 3D
  * Normal: visor 3D tipo estudio (WebGL). Usa la placa de video.
  * Si en una PC la vista 3D no arranca, la app pasa sola a un visor más simple.
  * También se puede forzar: abrir "SlicerSegelin (modo compatible).bat", o en la app
    View > Compatible 3D (se aplica al reiniciar).

Configuración y perfiles: se guardan en la carpeta "datos" junto al programa, así que
viajan con el pendrive.

Si Windows muestra "Windows protegió su PC": Más información > Ejecutar de todas formas
(el programa no está firmado digitalmente).
"""


def _size(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 2**20


def trim(dist: Path) -> None:
    removed = 0.0
    for f in list(dist.rglob("*")):
        if not f.is_file():
            continue
        name = f.name
        drop = name in DROP_FILES or name.startswith(DROP_DLL_PREFIX)
        if f.parent.name == "qtwebengine_locales" and name not in KEEP_LOCALES:
            drop = True
        if f.suffix == ".qm" and not name.startswith(KEEP_QM_PREFIX):
            drop = True
        if drop:
            removed += f.stat().st_size / 2**20
            f.unlink()
    qml = next((p for p in dist.rglob("qml") if p.is_dir() and p.parent.name == "Qt6"), None)
    if qml is not None:
        removed += _size(qml)
        shutil.rmtree(qml)
    print(f"trimmed {removed:.0f} MB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", action="store_true", help="also make dist/SlicerSegelin-portable.zip")
    args = ap.parse_args()
    spec = ROOT / "packaging" / "SlicerSegelin_v2.spec"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "v2"), str(spec)],
                   check=True, cwd=ROOT)
    trim(DIST)
    (DIST / "SlicerSegelin (modo compatible).bat").write_text(LAUNCHER, encoding="ascii")
    (DIST / "LEEME.txt").write_text(README, encoding="utf-8")
    files = sum(1 for f in DIST.rglob("*") if f.is_file())
    print(f"portable folder: {DIST}  ({_size(DIST):.0f} MB, {files} files)")
    if args.zip:
        z = shutil.make_archive(str(ROOT / "dist" / "SlicerSegelin-portable"), "zip", DIST.parent, DIST.name)
        print(f"zip: {z}  ({Path(z).stat().st_size / 2**20:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
