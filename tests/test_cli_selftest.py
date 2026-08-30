from __future__ import annotations

import json
from pathlib import Path

from stock_analysis.__main__ import main
from stock_analysis.common.paths import Paths_GetRuntimePaths
from stock_analysis.version import __version__


def test_version_command(capsys) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_self_test_and_headless_fixture(tmp_path: Path, capsys) -> None:
    report = tmp_path / "self-test.json"
    assert main(["--self-test", "--report", str(report)]) == 0
    self_test = json.loads(report.read_text(encoding="utf-8"))
    assert self_test["ok"] is True

    output = tmp_path / "headless.xlsx"
    assert (
        main(
            [
                "--headless",
                "--fixture-mode",
                "--max-a-share-companies",
                "1",
                "--max-hk-companies",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["output_path"] == str(output.resolve())
    assert output.is_file()
    log_file = Paths_GetRuntimePaths().log_file
    assert log_file.is_file()
    log_text = log_file.read_text(encoding="utf-8")
    assert "任务开始" in log_text
    assert "任务结束" in log_text
