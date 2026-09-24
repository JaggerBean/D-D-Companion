# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
datas = [
    (str(ROOT / "app" / "ui" / "web"), "app/ui/web"),
    (str(ROOT / "app" / "assets"), "app/assets"),
    (str(ROOT / "character"), "character"),
    (str(ROOT / "vendor"), "vendor"),
]
binaries = []
hiddenimports = ["webview.platforms.edgechromium"]
for package in ("faster_whisper", "ctranslate2", "av"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DNDCompanion",
    console=False,
    icon=str(ROOT / "app" / "assets" / "dnd-companion.ico"),
)
COLLECT(exe, a.binaries, a.datas, name="DNDCompanion")
