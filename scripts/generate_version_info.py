from __future__ import annotations

from pathlib import Path

from stock_analysis.version import (
    APP_DISPLAY_NAME,
    APP_INTERNAL_NAME,
    ORGANIZATION_NAME,
    __version__,
)


def main() -> int:
    parts = [int(part) for part in __version__.split(".")]
    while len(parts) < 4:
        parts.append(0)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(parts)}, prodvers={tuple(parts)}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('080404B0', [
    StringStruct('CompanyName', '{ORGANIZATION_NAME}'),
    StringStruct('FileDescription', '{APP_DISPLAY_NAME}'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('InternalName', '{APP_INTERNAL_NAME}'),
    StringStruct('OriginalFilename', '{APP_INTERNAL_NAME}.exe'),
    StringStruct('ProductName', '{APP_DISPLAY_NAME}'),
    StringStruct('ProductVersion', '{__version__}')
  ])]), VarFileInfo([VarStruct('Translation', [2052, 1200])])]
)
"""
    target = Path(__file__).resolve().parents[1] / "packaging" / "version_info.txt"
    target.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

