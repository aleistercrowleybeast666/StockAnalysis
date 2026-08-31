#!/usr/bin/env python3
"""Reassemble and verify split macOS archives downloaded from GitHub Actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

ARCHITECTURES = ("arm64", "x86_64")
METADATA_NAMES = (
    "ARCHITECTURE_{arch}.txt",
    "BUILD_REPORT_macOS_{arch}.md",
    "requirements-lock-macos-{arch}-resolved.txt",
    "SHA256SUMS_{arch}.txt",
)


def FileHash_Get(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def UniqueFile_Find(root: Path, name: str) -> Path:
    matches = [item for item in root.rglob(name) if item.is_file()]
    if len(matches) != 1:
        raise FileNotFoundError(
            f"期望唯一文件 {name!r}，实际找到 {len(matches)} 个"
        )
    return matches[0]


def Archive_Reassemble(
    download_root: Path, output_root: Path, architecture: str
) -> tuple[Path, dict[str, Any], int]:
    manifest_path = UniqueFile_Find(
        download_root, f"TRANSFER_MANIFEST_{architecture}.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("architecture") != architecture:
        raise ValueError(f"{manifest_path} 架构字段不匹配")
    parts = manifest.get("parts")
    if not isinstance(parts, list) or len(parts) != int(manifest.get("chunk_count", 0)):
        raise ValueError(f"{manifest_path} 分片清单不完整")
    archive_name = str(manifest.get("archive") or "")
    if archive_name != f"StockAnalysis_macOS_{architecture}.zip":
        raise ValueError(f"{manifest_path} 归档文件名不正确")

    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / archive_name
    temporary = output_root / f"{archive_name}.tmp"
    if temporary.exists():
        temporary.unlink()
    digest = hashlib.sha256()
    written = 0
    with temporary.open("wb") as output_stream:
        for item in parts:
            name = str(item.get("name") or "")
            part = UniqueFile_Find(download_root, name)
            expected_size = int(item.get("size", -1))
            if part.stat().st_size != expected_size:
                raise ValueError(f"分片大小不符：{part}")
            with part.open("rb") as input_stream:
                for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                    output_stream.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
    if written != int(manifest.get("size", -1)):
        temporary.unlink(missing_ok=True)
        raise ValueError(f"{architecture} 归档总大小不符")
    if digest.hexdigest().lower() != str(manifest.get("sha256") or "").lower():
        temporary.unlink(missing_ok=True)
        raise ValueError(f"{architecture} 归档 SHA-256 不符")
    temporary.replace(target)
    with zipfile.ZipFile(target) as archive:
        bad_file = archive.testzip()
        entry_count = len(archive.infolist())
    if bad_file is not None:
        raise ValueError(f"{architecture} ZIP CRC 失败：{bad_file}")
    return target, manifest, entry_count


def Metadata_Copy(download_root: Path, output_root: Path, architecture: str) -> None:
    for pattern in METADATA_NAMES:
        name = pattern.format(arch=architecture)
        source = UniqueFile_Find(download_root, name)
        shutil.copy2(source, output_root / name)


def Arguments_Parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("download_root", type=Path)
    parser.add_argument("output_root", type=Path)
    return parser.parse_args()


def Main_Run() -> int:
    arguments = Arguments_Parse()
    download_root = arguments.download_root.resolve()
    output_root = arguments.output_root.resolve()
    if not download_root.is_dir():
        raise FileNotFoundError(download_root)
    hash_lines: list[str] = []
    for architecture in ARCHITECTURES:
        archive, manifest, entry_count = Archive_Reassemble(
            download_root, output_root, architecture
        )
        Metadata_Copy(download_root, output_root, architecture)
        digest = FileHash_Get(archive)
        if digest.lower() != str(manifest["sha256"]).lower():
            raise ValueError(f"{architecture} 复制后 SHA-256 不符")
        hash_lines.append(f"{digest} *{archive.name}")
        print(
            f"{architecture}: {archive.stat().st_size} bytes, "
            f"{entry_count} entries, sha256={digest}"
        )
    (output_root / "SHA256SUMS.txt").write_text(
        "\n".join(hash_lines) + "\n", encoding="ascii"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(Main_Run())
