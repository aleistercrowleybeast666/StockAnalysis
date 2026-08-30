from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_runtime_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runtime_home = tmp_path / "runtime"
    monkeypatch.setenv("STOCK_ANALYSIS_HOME", str(runtime_home))
    return runtime_home
