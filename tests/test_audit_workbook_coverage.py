from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from scripts.audit_workbook_coverage import (
    TARGET_FIELDS,
    CoverageReports_Write,
    Workbook_Audit,
)


def _Workbook_Write(path: Path) -> None:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_name in ("A股", "港股"):
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(["测试标题"])
        sheet.append([])
        sheet.append([])
        sheet.append(["证券代码", *TARGET_FIELDS])
        sheet.append(["000001", 10, 0, "-", None, "", "2.5"])
        sheet.append(["000002", None, 1, 0, "—", 5, "文本"])
    workbook.save(path)


def test_workbook_audit_distinguishes_numeric_zero_dash_and_blank(tmp_path: Path) -> None:
    path = tmp_path / "audit.xlsx"
    _Workbook_Write(path)

    report = Workbook_Audit(path)
    first = report["sheets"]["A股"]["fields"]

    assert report["sheets"]["A股"]["company_count"] == 2
    assert first["市值增长率"]["zero_count"] == 1
    assert first["市值增长率"]["numeric_count"] == 2
    assert first["当年累计大宗交易笔数"]["dash_count"] == 1
    assert first["当年累计大宗交易笔数"]["zero_count"] == 1
    assert first["当年累计大宗交易金额"]["blank_count"] == 1
    assert first["当年累计大宗交易金额"]["dash_count"] == 1
    assert first["近五个交易日资金净额"]["blank_count"] == 1
    assert first["近一月资金净额（最近22个交易日）"]["other_text_count"] == 1
    assert report["release_gate"]["passed"] is False
    assert {
        (item["market"], item["field"])
        for item in report["release_gate"]["empty_numeric_columns"]
    } == {
        (market, "当年累计大宗交易金额")
        for market in ("A股", "港股")
    }


def test_coverage_reports_write_json_and_markdown(tmp_path: Path) -> None:
    workbook_path = tmp_path / "audit.xlsx"
    json_path = tmp_path / "reports" / "coverage.json"
    markdown_path = tmp_path / "reports" / "coverage.md"
    _Workbook_Write(workbook_path)

    CoverageReports_Write(Workbook_Audit(workbook_path), json_path, markdown_path)

    assert '"passed": false' in json_path.read_text(encoding="utf-8")
    assert "整列数值门禁：未通过" in markdown_path.read_text(encoding="utf-8")
