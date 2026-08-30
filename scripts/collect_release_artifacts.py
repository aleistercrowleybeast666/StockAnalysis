from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import platform
import sys
from datetime import datetime
from pathlib import Path


def File_Hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def Dependency_Version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "未安装"


def Arguments_Parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect verified release hashes and report.")
    parser.add_argument("--platform", choices=("windows", "macos"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--hash-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--validation-status",
        choices=("passed", "blocked"),
        default="passed",
    )
    parser.add_argument("--validation-summary", default="")
    return parser.parse_args()


def main() -> int:
    arguments = Arguments_Parse()
    binary = arguments.binary.resolve()
    archive = arguments.archive.resolve()
    for path in (binary, archive):
        if not path.is_file():
            raise FileNotFoundError(f"Release artifact is missing: {path}")

    binary_hash = File_Hash(binary)
    archive_hash = File_Hash(archive)
    binary_label = (
        "StockAnalysis/StockAnalysis.exe"
        if arguments.platform == "windows"
        else "StockAnalysis.app/Contents/MacOS/StockAnalysis"
    )
    arguments.hash_file.parent.mkdir(parents=True, exist_ok=True)
    arguments.hash_file.write_text(
        f"{binary_hash.lower()} *{binary_label}\n"
        f"{archive_hash.lower()} *{archive.name}\n",
        encoding="ascii",
    )

    platform_name = "Windows" if arguments.platform == "windows" else "macOS"
    if arguments.validation_status == "passed":
        result_text = (
            "构建脚本已先完成代码检查、离线/真实网络测试以及打包后自检、"
            "fixture 和 GUI smoke；任一环节失败时不会生成本报告。"
        )
        release_state = "通过"
    else:
        result_text = (
            "代码检查、离线测试、PyInstaller 打包、打包后自检、fixture 和 GUI smoke "
            "已经完成；真实网络/字段覆盖率门禁仍未通过。本产物仅供测试，禁止作为最终发布版。"
        )
        release_state = "阻断（测试预览）"
    validation_summary = arguments.validation_summary.strip()
    validation_section = (
        f"\n\n门禁说明：{validation_summary}" if validation_summary else ""
    )

    report = f"""# StockAnalysis {arguments.version} {platform_name} 构建报告

生成时间：{datetime.now().astimezone().isoformat(timespec="seconds")}  
系统：{platform.platform()}  
架构：{platform.machine()}  
Python：{sys.version.split()[0]}  
PySide6：{Dependency_Version("PySide6")}  
PyInstaller：{Dependency_Version("pyinstaller")}

## 结果

发布状态：**{release_state}**

{result_text}{validation_section}

程序版本为 {arguments.version}，发布形式为原生 onedir/windowed。macOS 产物仅能由真实 Mac 生成，本报告不代表 Apple Developer ID 公证。

## 产物

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| `{binary_label}` | {binary.stat().st_size:,} bytes | `{binary_hash}` |
| `{archive.name}` | {archive.stat().st_size:,} bytes | `{archive_hash}` |

哈希同时写入 `{arguments.hash_file.name}`。ZIP 必须完整解压后运行，不得只复制主可执行文件。
"""
    arguments.report.write_text(report, encoding="utf-8")
    print(f"release report: {arguments.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
