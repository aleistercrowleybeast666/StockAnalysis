from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from stock_analysis.version import APP_INTERNAL_NAME, ORGANIZATION_NAME


@dataclass(slots=True, frozen=True)
class RuntimePaths:
    data_root: Path
    config_file: Path
    logs_root: Path
    log_file: Path


def _FrozenPortableRoot_Get() -> Path:
    executable = Path(sys.executable).resolve()
    if platform.system() == "Darwin":
        parents = executable.parents
        if len(parents) >= 4 and parents[2].suffix.lower() == ".app":
            return parents[3]
    return executable.parent


def Paths_GetRuntimePaths(create: bool = True) -> RuntimePaths:
    override = os.environ.get("STOCK_ANALYSIS_HOME")
    if override:
        data_root = Path(override).expanduser().resolve()
        logs_root = data_root / "logs"
    else:
        data_root = Path(
            user_data_dir(APP_INTERNAL_NAME, ORGANIZATION_NAME, roaming=False)
        )
        logs_root = data_root / "logs"
    if getattr(sys, "frozen", False):
        logs_root = _FrozenPortableRoot_Get() / "logs"
    paths = RuntimePaths(
        data_root=data_root,
        config_file=data_root / "config.json",
        logs_root=logs_root,
        log_file=logs_root / "stock_analysis.log",
    )
    if create:
        for directory in (paths.data_root, paths.logs_root):
            directory.mkdir(parents=True, exist_ok=True)
    return paths


def Resources_GetRoot() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle_root / "resources"
    return Path(__file__).resolve().parents[3] / "resources"


def Resources_GetPath(relative_path: str) -> Path:
    return Resources_GetRoot() / Path(relative_path)
