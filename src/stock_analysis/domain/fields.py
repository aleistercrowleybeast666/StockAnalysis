from __future__ import annotations

from stock_analysis.domain.enums import Market

FLOW_FIVE_DAY_FIELD = "近五个交易日资金净额"
FLOW_ONE_MONTH_A_FIELD = "近一月资金净额（最近22个交易日）"
FLOW_ONE_MONTH_HK_FIELD = "近一月资金净额（最近20个交易日）"


def FlowOneMonthField_Get(market: Market) -> str:
    return (
        FLOW_ONE_MONTH_A_FIELD
        if market is Market.A_SHARE
        else FLOW_ONE_MONTH_HK_FIELD
    )


def FlowOneMonthDays_Get(market: Market) -> int:
    return 22 if market is Market.A_SHARE else 20
