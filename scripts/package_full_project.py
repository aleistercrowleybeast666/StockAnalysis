#!/usr/bin/env python3
"""Create the current complete source/test/docs/dist delivery ZIP."""

from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path

_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "artifacts",
    "build",
    "release",
    "releases",
    "backup",
    "old",
    "archive",
    "logs",
    "outputs",
}
_EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".sqlite3", ".tmp"}
_REQUIRED_PATHS = (
    "src",
    "tests",
    "resources",
    "packaging",
    "scripts",
    "docs",
    ".github/workflows",
    "pyproject.toml",
    "README.md",
    "README_CN.md",
    "DATA_SOURCE_REPORT.md",
    "TEST_REPORT.md",
    "PROGRESS_VALIDATION_REPORT.md",
    "dist/win/StockAnalysis_Windows_onedir.zip",
    "dist/mac/StockAnalysis_macOS_arm64.zip",
    "dist/mac/StockAnalysis_macOS_x86_64.zip",
)


def _PathInclude_Check(relative: Path) -> bool:
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative.suffix.lower() in _EXCLUDED_SUFFIXES:
        return False
    return relative.name not in {"src.zip", "分析表.xlsx"}


def ProjectFiles_List(project_root: Path) -> list[Path]:
    root = project_root.resolve()
    missing = [relative for relative in _REQUIRED_PATHS if not (root / relative).exists()]
    if missing:
        raise FileNotFoundError(f"完整工程缺少必需路径：{'、'.join(missing)}")
    files: list[Path] = []
    for directory, directory_names, file_names in os.walk(root):
        current = Path(directory)
        directory_names[:] = [
            name
            for name in directory_names
            if name not in _EXCLUDED_PARTS
            and not name.startswith(".tmp_pytest")
            and not (current / name).is_symlink()
        ]
        for file_name in file_names:
            path = current / file_name
            relative = path.relative_to(root)
            if path.is_file() and not path.is_symlink() and _PathInclude_Check(relative):
                files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def ProjectArchive_Create(project_root: Path, output_path: Path) -> Path:
    root = project_root.resolve()
    output = output_path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in ProjectFiles_List(root):
            archive.write(path, path.relative_to(root).as_posix())
    temporary.replace(output)
    return output


def _Arguments_Parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parents[1] / "release" / "StockAnalysis_full_project.zip",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _Arguments_Parse()
    archive = ProjectArchive_Create(arguments.project_root, arguments.output)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
