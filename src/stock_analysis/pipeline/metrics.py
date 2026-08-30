from __future__ import annotations

from stock_analysis.domain.calculations import (
    Calculation_Cagr,
    Calculation_GrossMargin,
    Calculation_MarketCapGrowth,
    Calculation_NetMargin,
    Calculation_PointChange,
    Calculation_RevenueGrowth,
    Calculation_SignedGrowth,
)
from stock_analysis.domain.enums import DataStatus
from stock_analysis.domain.models import AnalysisMetrics, AnalysisRecord


def _ValueStatus_Get(value: float | None) -> DataStatus:
    return DataStatus.OK if value is not None else DataStatus.MISSING


def _CagrStatus_Get(
    current: float | None, base: float | None, result: float | None
) -> DataStatus:
    if current is None or base is None:
        return DataStatus.MISSING
    if current <= 0 or base <= 0:
        return DataStatus.NOT_APPLICABLE
    return DataStatus.OK if result is not None else DataStatus.CALCULATION_UNDEFINED


def _GrowthStatus_Get(
    current: float | None, previous: float | None, result: float | None
) -> DataStatus:
    if current is None or previous is None:
        return DataStatus.MISSING
    if previous == 0:
        return DataStatus.NOT_APPLICABLE
    return DataStatus.OK if result is not None else DataStatus.CALCULATION_UNDEFINED


def Metrics_Calculate(record: AnalysisRecord) -> AnalysisMetrics:
    current = record.current
    previous = record.previous
    base = record.three_year_base
    current_revenue = current.revenue if current else None
    previous_revenue = previous.revenue if previous else None
    base_revenue = base.revenue if base else None
    current_profit = current.parent_net_profit if current else None
    previous_profit = previous.parent_net_profit if previous else None
    base_profit = base.parent_net_profit if base else None
    current_cash = current.operating_cash_flow if current else None
    previous_cash = previous.operating_cash_flow if previous else None
    base_cash = base.operating_cash_flow if base else None
    if record.security.is_financial:
        current_margin = previous_margin = base_margin = None
    else:
        current_margin = Calculation_GrossMargin(
            current_revenue, current.operating_cost if current else None
        )
        previous_margin = Calculation_GrossMargin(
            previous_revenue, previous.operating_cost if previous else None
        )
        base_margin = Calculation_GrossMargin(
            base_revenue, base.operating_cost if base else None
        )
    revenue_growth = Calculation_RevenueGrowth(current_revenue, previous_revenue)
    revenue_cagr = Calculation_Cagr(current_revenue, base_revenue)
    profit_growth = Calculation_SignedGrowth(current_profit, previous_profit)
    profit_cagr = Calculation_Cagr(current_profit, base_profit)
    cash_growth = Calculation_SignedGrowth(current_cash, previous_cash)
    cash_cagr = Calculation_Cagr(current_cash, base_cash)
    market_cap_growth = Calculation_MarketCapGrowth(
        record.quote.market_cap if record.quote else None,
        record.ipo.issue_market_cap if record.ipo else None,
    )
    metrics = AnalysisMetrics(
        revenue_growth=revenue_growth,
        revenue_cagr=revenue_cagr,
        gross_margin=current_margin,
        gross_margin_yoy_change=Calculation_PointChange(
            current_margin, previous_margin
        ),
        gross_margin_three_year_change=Calculation_PointChange(
            current_margin, base_margin
        ),
        net_margin=Calculation_NetMargin(current_revenue, current_profit),
        profit_growth=profit_growth,
        profit_cagr=profit_cagr,
        cash_growth=cash_growth,
        cash_cagr=cash_cagr,
        market_cap_growth=market_cap_growth,
    )
    record.metrics = metrics
    record.field_statuses.update(
        {
            "营业收入": _ValueStatus_Get(current_revenue),
            "营业收入同比": _GrowthStatus_Get(
                current_revenue, previous_revenue, revenue_growth
            ),
            "营业收入三年 CAGR": _CagrStatus_Get(
                current_revenue, base_revenue, revenue_cagr
            ),
            "毛利率": (
                DataStatus.NOT_APPLICABLE
                if record.security.is_financial and current_margin is None
                else _ValueStatus_Get(current_margin)
            ),
            "毛利率同比变化（百分点）": (
                DataStatus.NOT_APPLICABLE
                if record.security.is_financial
                else _ValueStatus_Get(metrics.gross_margin_yoy_change)
            ),
            "毛利率三年变化（百分点）": (
                DataStatus.NOT_APPLICABLE
                if record.security.is_financial
                else _ValueStatus_Get(metrics.gross_margin_three_year_change)
            ),
            "归母净利润": _ValueStatus_Get(current_profit),
            "归母净利率": (
                DataStatus.MISSING
                if current_revenue is None or current_profit is None
                else DataStatus.NOT_APPLICABLE
                if current_revenue == 0
                else _ValueStatus_Get(metrics.net_margin)
            ),
            "归母净利润同比": _GrowthStatus_Get(
                current_profit, previous_profit, profit_growth
            ),
            "归母净利润三年 CAGR": _CagrStatus_Get(
                current_profit, base_profit, profit_cagr
            ),
            "经营活动现金流净额": _ValueStatus_Get(current_cash),
            "经营活动现金流同比": _GrowthStatus_Get(
                current_cash, previous_cash, cash_growth
            ),
            "经营活动现金流三年 CAGR": _CagrStatus_Get(
                current_cash, base_cash, cash_cagr
            ),
            "市值增长率": (
                DataStatus.OK
                if market_cap_growth is not None
                else DataStatus.MISSING
                if record.quote is None
                or record.quote.market_cap is None
                or record.ipo is None
                or record.ipo.issue_market_cap is None
                else DataStatus.NOT_APPLICABLE
            ),
        }
    )
    return metrics
