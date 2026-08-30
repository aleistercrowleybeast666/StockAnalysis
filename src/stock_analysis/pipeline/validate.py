from __future__ import annotations

from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import AnalysisIssue, AnalysisRecord


def Record_Validate(record: AnalysisRecord) -> list[AnalysisIssue]:
    issues: list[AnalysisIssue] = []
    security = record.security
    expected_currency = "CNY" if security.market is Market.A_SHARE else "HKD"
    if record.current is None or record.current.revenue is None:
        issues.append(
            AnalysisIssue(
                security.market,
                security.code,
                security.name,
                "validate",
                "缺少所选年度营业收入",
                field_name="营业收入",
                field_status=DataStatus.MISSING,
                is_core=True,
            )
        )
    elif record.current.currency != expected_currency:
        issues.append(
            AnalysisIssue(
                security.market,
                security.code,
                security.name,
                "validate",
                f"标准币种应为 {expected_currency}，实际为 {record.current.currency}",
                field_name="报表币种",
                field_status=DataStatus.ERROR,
                is_core=True,
            )
        )
    for value, group in (
        (record.current, "本期财务"),
        (record.previous, "上期财务"),
        (record.three_year_base, "三年前财务"),
        (record.quote, "行情"),
        (record.ipo, "发行信息"),
        (record.flow, "资金流"),
        (record.block_trade, "大宗交易"),
    ):
        if value is not None and value.security_key != security.key:
            issues.append(
                AnalysisIssue(
                    security.market,
                    security.code,
                    security.name,
                    "validate",
                    f"{group}证券键与公司不一致",
                    field_name=group,
                    field_status=DataStatus.ERROR,
                    is_core=group == "本期财务",
                )
            )
    return issues
