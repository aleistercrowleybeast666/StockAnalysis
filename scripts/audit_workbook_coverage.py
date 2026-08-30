#!/usr/bin/env python3
"""Audit numeric coverage of the workbook's key market-data fields.

The report intentionally distinguishes a true numeric zero from a dash and a
blank cell.  This prevents a failed fetch from being mistaken for a legitimate
zero-value observation.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

MARKET_SHEETS = ("A股", "港股")
TARGET_FIELDS = (
    "发行时总市值",
    "市值增长率",
    "当年累计大宗交易笔数",
    "当年累计大宗交易金额",
    "近五个交易日资金净额",
    "近一月资金净额（最近22个交易日）",
)
CODE_HEADER = "证券代码"
DASH_VALUES = {"-", "—", "–"}


@dataclass(frozen=True)
class FieldCoverage:
    field: str
    company_count: int
    applicable_count: int
    numeric_count: int
    nonzero_numeric_count: int
    zero_count: int
    dash_count: int
    blank_count: int
    other_text_count: int
    coverage_rate: float
    all_blank: bool
    all_numeric_missing: bool


def _HeaderRow_Find(sheet: Any, search_limit: int = 20) -> int:
    for row_index in range(1, min(sheet.max_row, search_limit) + 1):
        values = {
            str(sheet.cell(row_index, column_index).value).strip()
            for column_index in range(1, sheet.max_column + 1)
            if sheet.cell(row_index, column_index).value is not None
        }
        if CODE_HEADER in values:
            return row_index
    raise ValueError(f"工作表 {sheet.title!r} 未找到表头 {CODE_HEADER!r}")


def _Headers_Index(sheet: Any, header_row: int) -> dict[str, int]:
    result: dict[str, int] = {}
    for column_index in range(1, sheet.max_column + 1):
        value = sheet.cell(header_row, column_index).value
        if value is not None and str(value).strip():
            result[str(value).strip()] = column_index
    return result


def _DataRows_List(sheet: Any, header_row: int, code_column: int) -> list[int]:
    rows: list[int] = []
    for row_index in range(header_row + 1, sheet.max_row + 1):
        code = sheet.cell(row_index, code_column).value
        if code is None or not str(code).strip():
            continue
        rows.append(row_index)
    return rows


def _Numeric_TryParse(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or text in DASH_VALUES:
            return None
        if text.endswith("%"):
            text = text[:-1]
        try:
            number = float(text)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _Field_Audit(sheet: Any, rows: Iterable[int], column: int, field: str) -> FieldCoverage:
    row_list = list(rows)
    numeric_count = 0
    nonzero_numeric_count = 0
    zero_count = 0
    dash_count = 0
    blank_count = 0
    other_text_count = 0

    for row_index in row_list:
        value = sheet.cell(row_index, column).value
        if value is None or (isinstance(value, str) and not value.strip()):
            blank_count += 1
            continue
        if isinstance(value, str) and value.strip() in DASH_VALUES:
            dash_count += 1
            continue
        number = _Numeric_TryParse(value)
        if number is None:
            other_text_count += 1
            continue
        numeric_count += 1
        if math.isclose(number, 0.0, abs_tol=1e-12):
            zero_count += 1
        else:
            nonzero_numeric_count += 1

    company_count = len(row_list)
    applicable_count = max(0, company_count - dash_count)
    coverage_rate = numeric_count / applicable_count if applicable_count else 0.0
    return FieldCoverage(
        field=field,
        company_count=company_count,
        applicable_count=applicable_count,
        numeric_count=numeric_count,
        nonzero_numeric_count=nonzero_numeric_count,
        zero_count=zero_count,
        dash_count=dash_count,
        blank_count=blank_count,
        other_text_count=other_text_count,
        coverage_rate=round(coverage_rate, 6),
        all_blank=company_count > 0 and blank_count == company_count,
        all_numeric_missing=applicable_count > 0 and numeric_count == 0,
    )


def Workbook_Audit(path: Path) -> dict[str, Any]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheets: dict[str, Any] = {}
        for sheet_name in MARKET_SHEETS:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(f"缺少工作表 {sheet_name!r}")
            sheet = workbook[sheet_name]
            header_row = _HeaderRow_Find(sheet)
            headers = _Headers_Index(sheet, header_row)
            missing_fields = [field for field in TARGET_FIELDS if field not in headers]
            if missing_fields:
                raise ValueError(
                    f"工作表 {sheet_name!r} 缺少目标字段：{', '.join(missing_fields)}"
                )
            rows = _DataRows_List(sheet, header_row, headers[CODE_HEADER])
            coverages = [
                _Field_Audit(sheet, rows, headers[field], field)
                for field in TARGET_FIELDS
            ]
            sheets[sheet_name] = {
                "header_row": header_row,
                "company_count": len(rows),
                "fields": {item.field: asdict(item) for item in coverages},
            }
        empty_numeric_columns = [
            {"market": sheet_name, "field": field_name}
            for sheet_name, sheet_report in sheets.items()
            for field_name, field_report in sheet_report["fields"].items()
            if field_report["all_numeric_missing"]
        ]
        return {
            "schema_version": 2,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "workbook": str(path.resolve()),
            "coverage_definition": (
                "numeric_count / applicable_count；applicable_count = company_count - dash_count"
            ),
            "sheets": sheets,
            "release_gate": {
                "passed": not empty_numeric_columns,
                "empty_numeric_columns": empty_numeric_columns,
                "rule": "有适用公司的目标字段不得整列无数值",
            },
        }
    finally:
        workbook.close()


def _Markdown_Render(report: dict[str, Any]) -> str:
    lines = [
        "# 工作簿关键字段覆盖率审计",
        "",
        f"- 文件：`{report['workbook']}`",
        f"- 生成时间：{report['generated_at']}",
        f"- 覆盖率定义：{report['coverage_definition']}",
        f"- 整列数值门禁：{'通过' if report['release_gate']['passed'] else '未通过'}",
        "",
        "数值 0 单独计数；`-` 表示明确不适用；空白表示未取得或未写入，三者不会混算。",
        "",
    ]
    for sheet_name, sheet_report in report["sheets"].items():
        lines.extend(
            [
                f"## {sheet_name}",
                "",
                f"公司数：{sheet_report['company_count']}",
                "",
                "| 字段 | 理论适用 | 数值 | 非零数值 | 零 | `-` | 空白 | 其他文本 | 覆盖率 | 整列空白 | 整列无数值 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|",
            ]
        )
        for field, item in sheet_report["fields"].items():
            row_values = dict(item)
            row_values["field"] = field
            row_values["rate"] = item["coverage_rate"]
            row_values["all_blank_label"] = "是" if item["all_blank"] else "否"
            row_values["all_numeric_missing_label"] = (
                "是" if item["all_numeric_missing"] else "否"
            )
            lines.append(
                "| {field} | {applicable_count} | {numeric_count} | "
                "{nonzero_numeric_count} | {zero_count} | {dash_count} | "
                "{blank_count} | {other_text_count} | {rate:.2%} | "
                "{all_blank_label} | {all_numeric_missing_label} |".format(**row_values)
            )
        lines.append("")
    if not report["release_gate"]["passed"]:
        lines.extend(["## 未通过门禁的整列", ""])
        for item in report["release_gate"]["empty_numeric_columns"]:
            lines.append(f"- {item['market']}：{item['field']}")
        lines.append("")
    return "\n".join(lines)


def CoverageReports_Write(
    report: dict[str, Any], json_path: Path, markdown_path: Path
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(_Markdown_Render(report), encoding="utf-8")


def _Arguments_Parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path, help="待审计的 .xlsx 文件")
    parser.add_argument("--json", dest="json_path", type=Path, required=True)
    parser.add_argument("--markdown", dest="markdown_path", type=Path, required=True)
    parser.add_argument(
        "--allow-empty-columns",
        action="store_true",
        help="仅用于基线审计；仍写入门禁失败，但命令返回成功",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _Arguments_Parse(sys.argv[1:] if argv is None else argv)
    if not arguments.workbook.is_file():
        print(f"文件不存在：{arguments.workbook}", file=sys.stderr)
        return 2
    try:
        report = Workbook_Audit(arguments.workbook)
    except (OSError, ValueError) as exc:
        print(f"审计失败：{exc}", file=sys.stderr)
        return 1

    CoverageReports_Write(report, arguments.json_path, arguments.markdown_path)
    print(
        f"审计完成：{arguments.json_path}；{arguments.markdown_path}",
        file=sys.stdout,
    )
    if not report["release_gate"]["passed"] and not arguments.allow_empty_columns:
        print(
            "发布门禁未通过：至少一个目标字段在有适用公司的市场中整列无数值",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
