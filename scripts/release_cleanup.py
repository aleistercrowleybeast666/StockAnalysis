#!/usr/bin/env python3
"""Plan and safely remove obsolete local release artifacts.

The default mode is read-only.  Destructive cleanup additionally requires the
current Windows and both macOS archives to exist, so an old usable release is
not removed before its replacement has been downloaded and verified.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

CURRENT_RELEASE_TAG = "current"
CURRENT_RELEASE_TITLE = "StockAnalysis Current Release"
CURRENT_RELEASE_ASSETS = (
    "StockAnalysis_Windows_onedir.zip",
    "StockAnalysis_macOS_arm64.zip",
    "StockAnalysis_macOS_x86_64.zip",
    "SHA256SUMS.txt",
)

_DIST_ALLOWED = {
    "win": {
        "StockAnalysis",
        "StockAnalysis_Windows_onedir.zip",
        "SHA256SUMS.txt",
        "BUILD_REPORT_Windows.md",
    },
    "mac": {
        "arm64",
        "x86_64",
        "StockAnalysis_macOS_arm64.zip",
        "StockAnalysis_macOS_x86_64.zip",
        "SHA256SUMS.txt",
        "BUILD_REPORT_macOS.md",
    },
}
_OBSOLETE_ROOT_FILES = ("src.zip", "分析表.xlsx")
_OBSOLETE_DIRECTORIES = ("build", "releases", "backup", "old", "archive")
_ARTIFACT_ALLOWED = {
    "A_SHARE_REGRESSION.md",
    "HK_COVERAGE_BASELINE.json",
    "HK_COVERAGE_BASELINE.md",
    "HK_COVERAGE_FINAL.json",
    "HK_COVERAGE_FINAL.md",
    "top100_0_5_0_release",
}


def CurrentReleaseAssets_Validate(asset_names: set[str]) -> bool:
    return asset_names == set(CURRENT_RELEASE_ASSETS)


def _PathInside_Check(project_root: Path, target: Path) -> Path:
    root = project_root.resolve()
    resolved = target.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError(f"拒绝清理工程目录外路径：{resolved}")
    return resolved


def LocalCleanupPlan_Create(project_root: Path) -> list[Path]:
    root = project_root.resolve()
    candidates: list[Path] = []
    for relative in _OBSOLETE_ROOT_FILES:
        target = root / relative
        if target.exists():
            candidates.append(target)
    for relative in _OBSOLETE_DIRECTORIES:
        target = root / relative
        if target.exists():
            candidates.append(target)

    release_root = root / "release"
    if release_root.is_dir():
        for child in release_root.iterdir():
            if child.name != "StockAnalysis_full_project.zip":
                candidates.append(child)

    artifact_root = root / "artifacts"
    if artifact_root.is_dir():
        for child in artifact_root.iterdir():
            if child.name not in _ARTIFACT_ALLOWED:
                candidates.append(child)

    for platform_name, allowed_names in _DIST_ALLOWED.items():
        platform_root = root / "dist" / platform_name
        if not platform_root.is_dir():
            continue
        for child in platform_root.iterdir():
            if child.name not in allowed_names:
                candidates.append(child)

    return sorted(
        {_PathInside_Check(root, item) for item in candidates},
        key=lambda item: str(item).casefold(),
    )


def CurrentLocalArtifacts_Validate(project_root: Path) -> None:
    root = project_root.resolve()
    required = (
        root / "dist" / "win" / "StockAnalysis_Windows_onedir.zip",
        root / "dist" / "mac" / "StockAnalysis_macOS_arm64.zip",
        root / "dist" / "mac" / "StockAnalysis_macOS_x86_64.zip",
    )
    missing = [path for path in required if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        joined = "、".join(str(path) for path in missing)
        raise FileNotFoundError(f"当前双平台产物尚未齐备，拒绝清理旧发布：{joined}")


def LocalCleanup_Apply(project_root: Path, candidates: list[Path]) -> int:
    root = project_root.resolve()
    count = 0
    for candidate in candidates:
        target = _PathInside_Check(root, candidate)
        if not target.exists():
            continue
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        count += 1
    return count


def _Arguments_Parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _Arguments_Parse()
    plan = LocalCleanupPlan_Create(arguments.project_root)
    for target in plan:
        print(target)
    if not arguments.apply:
        print(f"dry-run: {len(plan)} 个候选；未删除任何文件")
        return 0
    CurrentLocalArtifacts_Validate(arguments.project_root)
    removed = LocalCleanup_Apply(arguments.project_root, plan)
    print(f"已删除 {removed} 个旧发布目标")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
