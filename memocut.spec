# -*- mode: python ; coding: utf-8 -*-
# Збірка: pyinstaller memocut.spec  ->  dist/MemoCut/
#   MemoCut.exe      — вікно програми (без консолі)
#   memocut-cli.exe  — те саме, але для командного рядка
# ffmpeg.exe/ffprobe.exe кладе workflow у dist/MemoCut/ffmpeg/, стилі — у dist/MemoCut/styles/.
from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets"), ("styles", "styles")]
binaries, hidden = [], []
for pkg in ("faster_whisper", "ctranslate2"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h

# Великі модулі Qt, які нам не потрібні (менший zip).
EXCLUDES = [
    "tkinter", "matplotlib", "IPython", "pytest", "pandas", "scipy", "PIL", "lxml", "python_calamine",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner",
]

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden + ["memocut.gui", "memocut.cli"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MemoCut",
          console=False, upx=False, icon=None)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="memocut-cli",
          console=True, upx=False, icon=None)

coll = COLLECT(gui, cli, a.binaries, a.datas, upx=False, name="MemoCut")
