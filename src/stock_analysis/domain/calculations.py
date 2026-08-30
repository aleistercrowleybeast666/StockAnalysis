from __future__ import annotations

import math


def Calculation_RevenueGrowth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - 1.0


def Calculation_SignedGrowth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def Calculation_Cagr(
    current: float | None, base: float | None, years: int = 3
) -> float | None:
    if current is None or base is None or current <= 0 or base <= 0 or years <= 0:
        return None
    result = math.pow(current / base, 1.0 / years) - 1.0
    return result if math.isfinite(result) else None


def Calculation_GrossMargin(revenue: float | None, cost: float | None) -> float | None:
    if revenue is None or cost is None or revenue <= 0:
        return None
    return (revenue - cost) / revenue


def Calculation_NetMargin(revenue: float | None, profit: float | None) -> float | None:
    if revenue is None or profit is None or revenue == 0:
        return None
    return profit / revenue


def Calculation_PointChange(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return current - previous


def Calculation_IssueMarketCap(
    issue_price: float | None,
    post_issue_total_shares: float | None,
    issued_shares: float | None,
) -> tuple[float | None, bool]:
    _ = issued_shares
    if issue_price is None or issue_price <= 0:
        return None, False
    if post_issue_total_shares is not None and post_issue_total_shares > 0:
        return issue_price * post_issue_total_shares, False
    return None, False


def Calculation_MarketCapGrowth(
    latest_market_cap: float | None, issue_market_cap: float | None
) -> float | None:
    if latest_market_cap is None or issue_market_cap is None or issue_market_cap <= 0:
        return None
    return latest_market_cap / issue_market_cap - 1.0


def Calculation_ToHundredMillion(value: float | None) -> float | None:
    return None if value is None else value / 100_000_000.0


def Calculation_ConvertCurrency(value: float | None, rate: float | None) -> float | None:
    if value is None:
        return None
    if rate is None or rate <= 0:
        return None
    return value * rate
