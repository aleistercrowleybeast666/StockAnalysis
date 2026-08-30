from __future__ import annotations

from copy import copy

from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

_TITLE_FILL = PatternFill("solid", fgColor="4A9BD8")
_SUBTITLE_FILL = PatternFill("solid", fgColor="EAF4FC")
_NEUTRAL_GROUP_FILL = PatternFill("solid", fgColor="D9E2F3")
_NEUTRAL_FIELD_FILL = PatternFill("solid", fgColor="EDF1F7")
_FINANCIAL_GROUP_FILL = PatternFill("solid", fgColor="A9D18E")
_FINANCIAL_FIELD_FILL = PatternFill("solid", fgColor="E2F0D9")
_MARKET_GROUP_FILL = PatternFill("solid", fgColor="9DC3E6")
_MARKET_FIELD_FILL = PatternFill("solid", fgColor="DDEBF7")
_WHITE_FONT = Font(name="等线", size=11, bold=True, color="FFFFFF")
_GROUP_FONT = Font(name="等线", size=10, bold=True, color="1F2937")
_HEADER_FONT = Font(name="等线", size=10, bold=True, color="1F2937")
_BODY_FONT = Font(name="等线", size=10, color="000000")
_LINK_FONT = Font(name="等线", size=10, color="008000")
_THIN_GRAY = Side(style="thin", color="CAD5E2")

MAIN_GROUPS = (
    ("A3:D3", "公司信息", _NEUTRAL_GROUP_FILL),
    ("E3:G3", "营业收入", _FINANCIAL_GROUP_FILL),
    ("H3:J3", "毛利率", _FINANCIAL_GROUP_FILL),
    ("K3:N3", "归母净利润", _FINANCIAL_GROUP_FILL),
    ("O3:Q3", "经营活动现金流", _FINANCIAL_GROUP_FILL),
    ("R3:AB3", "上市发行与市场交易", _MARKET_GROUP_FILL),
)


def _FieldFill_Get(column: int) -> PatternFill:
    if column <= 4:
        return _NEUTRAL_FIELD_FILL
    if column <= 17:
        return _FINANCIAL_FIELD_FILL
    return _MARKET_FIELD_FILL


def Formatting_MainSheet(sheet: Worksheet, last_row: int) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "E5"
    sheet.auto_filter.ref = f"A4:AB{max(4, last_row)}"
    sheet.row_dimensions[1].height = 24
    sheet.row_dimensions[2].height = 25
    sheet.row_dimensions[3].height = 24
    sheet.row_dimensions[4].height = 52
    sheet.merge_cells("A1:AB1")
    sheet.merge_cells("A2:AB2")
    sheet["A1"].fill = _TITLE_FILL
    sheet["A1"].font = Font(name="等线", size=13, bold=True, color="FFFFFF")
    sheet["A1"].alignment = Alignment(horizontal="left", vertical="center")
    sheet["A2"].fill = _SUBTITLE_FILL
    sheet["A2"].font = Font(name="等线", size=10, color="1F2937")
    sheet["A2"].alignment = Alignment(
        horizontal="left", vertical="center", wrap_text=True
    )

    for merged_range, title, fill in MAIN_GROUPS:
        sheet.merge_cells(merged_range)
        start = merged_range.split(":", 1)[0]
        cell = sheet[start]
        cell.value = title
        cell.fill = copy(fill)
        cell.font = copy(_GROUP_FONT)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = Border(bottom=_THIN_GRAY)

    for column in range(1, 29):
        cell = sheet.cell(4, column)
        cell.fill = copy(_FieldFill_Get(column))
        cell.font = copy(_HEADER_FONT)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=_THIN_GRAY)

    linked_columns = {
        3,
        5,
        11,
        15,
        18,
        19,
        20,
        21,
        22,
        23,
        25,
        26,
        27,
        28,
    }
    percentage_columns = {6, 7, 8, 12, 13, 14, 16, 17, 24}
    point_columns = {9, 10}
    amount_columns = {5, 11, 15, 18, 22, 26, 27, 28}
    price_columns = {20, 23}
    for row in range(5, last_row + 1):
        sheet.row_dimensions[row].height = 21
        for column in range(1, 29):
            cell = sheet.cell(row, column)
            cell.font = copy(_LINK_FONT if column in linked_columns else _BODY_FONT)
            cell.alignment = Alignment(
                horizontal="left" if column in {1, 2, 4} else "right",
                vertical="center",
            )
            if column in percentage_columns:
                cell.number_format = "0.00%;-0.00%;0.00%"
            elif column in point_columns:
                cell.number_format = "0.00;-0.00;0.00"
            elif column in amount_columns:
                cell.number_format = "#,##0.00;-#,##0.00;0.00"
            elif column in price_columns or column == 21:
                cell.number_format = "#,##0.000;-#,##0.000;0.000"
            elif column == 25:
                cell.number_format = "#,##0"
            elif column in {3, 19}:
                cell.number_format = "yyyy-mm-dd"
            elif column == 1:
                cell.number_format = "@"

    widths = {
        "A": 12,
        "B": 18,
        "C": 13,
        "D": 11,
        "E": 16,
        "F": 14,
        "G": 18,
        "H": 11,
        "I": 20,
        "J": 20,
        "K": 16,
        "L": 13,
        "M": 16,
        "N": 19,
        "O": 19,
        "P": 19,
        "Q": 22,
        "R": 15,
        "S": 13,
        "T": 11,
        "U": 13,
        "V": 16,
        "W": 11,
        "X": 13,
        "Y": 19,
        "Z": 19,
        "AA": 18,
        "AB": 22,
    }
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.print_title_rows = "1:4"


def Formatting_AuxiliarySheet(sheet: Worksheet, last_column: int) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A2"
    for column in range(1, last_column + 1):
        cell = sheet.cell(1, column)
        cell.fill = copy(_TITLE_FILL)
        cell.font = copy(_WHITE_FONT)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(column)].width = 18
    sheet.row_dimensions[1].height = 34


def Formatting_AddHeaderComments(sheet: Worksheet) -> None:
    comments = {
        "F4": "上期营业收入大于 0 时：本期/上期-1。",
        "G4": "本期与三年前营业收入均大于 0 时：(本期/三年前)^(1/3)-1。",
        "I4": "本期毛利率减上期毛利率，结果以百分点显示。",
        "J4": "本期毛利率减三年前毛利率，不计算 CAGR。",
        "M4": "上期归母净利润不为 0 时：(本期-上期)/ABS(上期)。",
        "V4": "仅按发行价×发行后总股本计算；缺任一项时留空，不使用募资额或发行股数替代。",
        "X4": "发行时总市值大于 0 时：最新总市值/发行时总市值-1。",
        "AB4": (
            "近一月按最近 20 个有效交易日口径聚合。"
            if sheet.title == "港股"
            else "近一月按最近 22 个有效交易日口径聚合。"
        ),
    }
    for address, text in comments.items():
        sheet[address].comment = Comment(text, "StockAnalysis")
