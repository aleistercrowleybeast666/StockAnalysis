from __future__ import annotations

import json
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from stock_analysis.common.paths import Paths_GetRuntimePaths
from stock_analysis.config.models import AppConfig


def Config_Load(path: Path | None = None) -> AppConfig:
    config_path = path or Paths_GetRuntimePaths().config_file
    if not config_path.exists():
        return AppConfig()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("配置根节点必须是对象")
        return AppConfig.from_dict(data)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = config_path.with_name(f"{config_path.stem}.corrupt.{suffix}.json")
        with suppress(OSError):
            config_path.replace(backup)
        return AppConfig()


def Config_Save(config: AppConfig, path: Path | None = None) -> None:
    config.validate()
    config_path = path or Paths_GetRuntimePaths().config_file
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(config_path)
