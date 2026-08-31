from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.collect_macos_action_artifacts import (
    Archive_Reassemble,
    FileHash_Get,
    Metadata_Copy,
)
from scripts.package_full_project import ProjectArchive_Create
from scripts.release_cleanup import (
    CURRENT_RELEASE_ASSETS,
    CurrentLocalArtifacts_Validate,
    CurrentReleaseAssets_Validate,
    LocalCleanup_Apply,
    LocalCleanupPlan_Create,
)


def _Touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_cleanup_plan_only_targets_obsolete_release_files(tmp_path: Path) -> None:
    _Touch(tmp_path / "src" / "keep.py")
    _Touch(tmp_path / "src.zip")
    _Touch(tmp_path / "build" / "old.bin")
    _Touch(tmp_path / "release" / "StockAnalysis_0.4.0.zip")
    _Touch(tmp_path / "release" / "StockAnalysis_full_project.zip")
    _Touch(tmp_path / "artifacts" / "old-build" / "old.bin")
    _Touch(tmp_path / "artifacts" / "A_SHARE_REGRESSION.md")
    _Touch(tmp_path / "dist" / "win" / "StockAnalysis_Windows_onedir.zip")
    _Touch(tmp_path / "dist" / "win" / "StockAnalysis_0.4.0.zip")

    plan = LocalCleanupPlan_Create(tmp_path)
    relative = {path.relative_to(tmp_path).as_posix() for path in plan}

    assert relative == {
        "artifacts/old-build",
        "build",
        "dist/win/StockAnalysis_0.4.0.zip",
        "release/StockAnalysis_0.4.0.zip",
        "src.zip",
    }
    assert LocalCleanup_Apply(tmp_path, plan) == 5
    assert (tmp_path / "src" / "keep.py").is_file()
    assert (tmp_path / "release" / "StockAnalysis_full_project.zip").is_file()
    assert (tmp_path / "artifacts" / "A_SHARE_REGRESSION.md").is_file()
    assert (tmp_path / "dist" / "win" / "StockAnalysis_Windows_onedir.zip").is_file()


def test_cleanup_requires_current_dual_platform_archives(tmp_path: Path) -> None:
    _Touch(tmp_path / "dist" / "win" / "StockAnalysis_Windows_onedir.zip")
    with pytest.raises(FileNotFoundError):
        CurrentLocalArtifacts_Validate(tmp_path)
    _Touch(tmp_path / "dist" / "mac" / "StockAnalysis_macOS_arm64.zip")
    _Touch(tmp_path / "dist" / "mac" / "StockAnalysis_macOS_x86_64.zip")
    CurrentLocalArtifacts_Validate(tmp_path)


def test_current_release_asset_list_is_exact() -> None:
    expected = set(CURRENT_RELEASE_ASSETS)
    assert CurrentReleaseAssets_Validate(expected)
    assert not CurrentReleaseAssets_Validate(expected | {"old.zip"})
    assert not CurrentReleaseAssets_Validate(expected - {"SHA256SUMS.txt"})


def test_full_project_archive_includes_required_tree_and_excludes_runtime_data(
    tmp_path: Path,
) -> None:
    for directory in (
        "src",
        "tests",
        "resources",
        "packaging",
        "scripts",
        "docs",
        ".github/workflows",
    ):
        _Touch(tmp_path / directory / "keep.txt")
    for file_name in (
        "pyproject.toml",
        "README.md",
        "README_CN.md",
        "DATA_SOURCE_REPORT.md",
        "TEST_REPORT.md",
        "PROGRESS_VALIDATION_REPORT.md",
        "dist/win/StockAnalysis_Windows_onedir.zip",
        "dist/mac/StockAnalysis_macOS_arm64.zip",
        "dist/mac/StockAnalysis_macOS_x86_64.zip",
    ):
        _Touch(tmp_path / file_name)
    _Touch(tmp_path / ".venv" / "secret.txt")
    _Touch(tmp_path / "artifacts" / "run.log")
    _Touch(tmp_path / "src.zip")

    output = ProjectArchive_Create(
        tmp_path, tmp_path / "release" / "StockAnalysis_full_project.zip"
    )

    with ZipFile(output) as archive:
        names = set(archive.namelist())
    assert "src/keep.txt" in names
    assert "dist/mac/StockAnalysis_macOS_arm64.zip" in names
    assert not any(name.startswith(".venv/") for name in names)
    assert not any(name.startswith("artifacts/") for name in names)
    assert "src.zip" not in names


def test_macos_action_parts_are_reassembled_and_crc_checked(tmp_path: Path) -> None:
    download_root = tmp_path / "download"
    output_root = tmp_path / "dist" / "mac"
    source = tmp_path / "StockAnalysis_macOS_arm64.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("StockAnalysis.app/Contents/MacOS/StockAnalysis", b"binary")
    payload = source.read_bytes()
    midpoint = len(payload) // 2
    part_names = [
        "StockAnalysis_macOS_arm64.zip.part-00",
        "StockAnalysis_macOS_arm64.zip.part-01",
    ]
    parts = [payload[:midpoint], payload[midpoint:]]
    for name, value in zip(part_names, parts, strict=True):
        path = download_root / name / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    digest = FileHash_Get(source)
    manifest = {
        "archive": source.name,
        "architecture": "arm64",
        "chunk_count": 2,
        "size": len(payload),
        "sha256": digest,
        "parts": [
            {"name": name, "size": len(value)}
            for name, value in zip(part_names, parts, strict=True)
        ],
    }
    manifest_path = download_root / "metadata" / "TRANSFER_MANIFEST_arm64.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    for pattern in (
        "ARCHITECTURE_arm64.txt",
        "BUILD_REPORT_macOS_arm64.md",
        "requirements-lock-macos-arm64-resolved.txt",
        "SHA256SUMS_arm64.txt",
    ):
        _Touch(download_root / "metadata" / pattern)

    archive, parsed, entry_count = Archive_Reassemble(
        download_root, output_root, "arm64"
    )
    Metadata_Copy(download_root, output_root, "arm64")

    assert parsed["sha256"] == digest
    assert FileHash_Get(archive) == digest
    assert entry_count == 1
    assert (output_root / "BUILD_REPORT_macOS_arm64.md").is_file()
