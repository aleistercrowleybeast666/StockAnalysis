# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

project_root = Path(SPECPATH).parent
source_root = project_root / "src"
resources_root = project_root / "resources"
entry = source_root / "stock_analysis" / "__main__.py"
version_namespace = {}
exec(
    (source_root / "stock_analysis" / "version.py").read_text(encoding="utf-8"),
    version_namespace,
)
app_version = version_namespace["__version__"]

hiddenimports = [
    "openpyxl.cell._writer",
    "openpyxl.worksheet._writer",
    "dateutil.parser",
]

a = Analysis(
    [str(entry)],
    pathex=[str(source_root)],
    binaries=[],
    datas=[(str(resources_root), "resources")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytestqt", "ruff", "tests"],
    noarchive=False,
    optimize=1,
)

# The Codex Windows runtime places Poppler's ICU 78 directory on PATH. Its
# version-suffixed exports are incompatible with Qt's Windows-system ICU import,
# so never let those unrelated DLLs shadow the OS ICU forwarder in the bundle.
if sys.platform == "win32":
    a.binaries = [
        item
        for item in a.binaries
        if not (
            Path(item[1]).name.lower() in {"icuuc.dll", "icudt78.dll"}
            and "poppler" in str(item[1]).lower()
        )
    ]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StockAnalysis",
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
    version=str(project_root / "packaging" / "version_info.txt") if sys.platform == "win32" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StockAnalysis",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="StockAnalysis.app",
        icon=None,
        bundle_identifier="local.stockanalysis.app",
        info_plist={
            "CFBundleDisplayName": "股票分析表生成器",
            "CFBundleShortVersionString": app_version,
            "CFBundleVersion": app_version,
            "NSHighResolutionCapable": True,
        },
    )
