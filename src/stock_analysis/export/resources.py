from __future__ import annotations

from pathlib import Path

from stock_analysis.common.paths import Resources_GetPath


def Template_GetPath() -> Path:
    path = Resources_GetPath("templates/分析表.xlsx")
    if not path.is_file():
        raise FileNotFoundError(f"缺少工作簿模板：{path}")
    return path

