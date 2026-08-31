from __future__ import annotations

from datetime import date

import pytest

from stock_analysis.domain.calculations import (
    Calculation_Cagr,
    Calculation_ConvertCurrency,
    Calculation_GrossMargin,
    Calculation_IssueMarketCap,
    Calculation_MarketCapGrowth,
    Calculation_NetMargin,
    Calculation_PointChange,
    Calculation_RevenueGrowth,
    Calculation_SignedGrowth,
    Calculation_ToHundredMillion,
)
from stock_analysis.domain.enums import DataStatus, Market
from stock_analysis.domain.models import AnalysisRecord, FinancialPeriod, Security
from stock_analysis.pipeline.metrics import Metrics_Calculate


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(120.0, 100.0, 0.2), (100.0, 0.0, None), (None, 10.0, None)],
)
def test_revenue_growth(current: float | None, previous: float | None, expected: float | None) -> None:
    result = Calculation_RevenueGrowth(current, previous)
    assert result == pytest.approx(expected) if expected is not None else result is None


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(-5.0, -10.0, 0.5), (5.0, -10.0, 1.5), (-5.0, 10.0, -1.5), (5.0, 0.0, None)],
)
def test_signed_growth_handles_loss_and_turnaround(
    current: float, previous: float, expected: float | None
) -> None:
    result = Calculation_SignedGrowth(current, previous)
    assert result == pytest.approx(expected) if expected is not None else result is None


def test_cagr_and_margin_boundaries() -> None:
    assert Calculation_Cagr(133.1, 100.0, 3) == pytest.approx(0.1)
    assert Calculation_Cagr(-1.0, 100.0, 3) is None
    assert Calculation_Cagr(100.0, 0.0, 3) is None
    assert Calculation_GrossMargin(100.0, 60.0) == pytest.approx(0.4)
    assert Calculation_GrossMargin(0.0, 0.0) is None
    assert Calculation_NetMargin(100.0, -5.0) == pytest.approx(-0.05)
    assert Calculation_NetMargin(0.0, 2.0) is None
    assert Calculation_PointChange(0.42, 0.40) == pytest.approx(0.02)


def test_ipo_market_cap_requires_post_issue_total_shares() -> None:
    exact, exact_approximate = Calculation_IssueMarketCap(10.0, 1_000.0, 100.0)
    fallback, fallback_approximate = Calculation_IssueMarketCap(10.0, None, 100.0)
    missing, missing_approximate = Calculation_IssueMarketCap(None, 1_000.0, 100.0)
    assert exact == 10_000.0
    assert exact_approximate is False
    assert fallback is None
    assert fallback_approximate is False
    assert missing is None
    assert missing_approximate is False
    assert Calculation_MarketCapGrowth(2_000.0, 1_000.0) == pytest.approx(1.0)


def test_currency_and_display_unit_conversion() -> None:
    assert Calculation_ConvertCurrency(100.0, 0.91) == pytest.approx(91.0)
    assert Calculation_ConvertCurrency(100.0, 0.0) is None
    assert Calculation_ToHundredMillion(500_000_000.0) == pytest.approx(5.0)
    assert Calculation_ToHundredMillion(None) is None


def test_financial_company_gross_margin_is_not_applicable() -> None:
    security = Security(
        Market.A_SHARE,
        "SZSE",
        "000001",
        "平安银行",
        is_financial=True,
    )
    current = FinancialPeriod(
        security.key,
        date(2025, 12, 31),
        2025,
        None,
        "CNY",
        100.0,
        30.0,
        20.0,
        10.0,
    )
    record = AnalysisRecord(security=security, current=current)
    metrics = Metrics_Calculate(record)
    assert metrics.gross_margin is None
    assert record.field_statuses["毛利率"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["毛利率同比变化（百分点）"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["毛利率三年变化（百分点）"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["营业收入三年 CAGR"] is DataStatus.MISSING


def test_nonfinancial_nonpositive_revenue_marks_whole_gross_margin_family_not_applicable() -> None:
    security = Security(Market.A_SHARE, "SSE", "600001", "测试制造公司")
    current = FinancialPeriod(
        security.key,
        date(2025, 12, 31),
        2025,
        None,
        "CNY",
        0.0,
        20.0,
        -5.0,
        0.0,
    )
    previous = FinancialPeriod(
        security.key,
        date(2024, 12, 31),
        2024,
        None,
        "CNY",
        100.0,
        60.0,
        5.0,
        10.0,
    )
    base = FinancialPeriod(
        security.key,
        date(2022, 12, 31),
        2022,
        None,
        "CNY",
        80.0,
        50.0,
        4.0,
        8.0,
    )
    record = AnalysisRecord(
        security=security,
        current=current,
        previous=previous,
        three_year_base=base,
    )

    Metrics_Calculate(record)

    assert record.field_statuses["毛利率"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["毛利率同比变化（百分点）"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["毛利率三年变化（百分点）"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["营业收入三年 CAGR"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["归母净利润三年 CAGR"] is DataStatus.NOT_APPLICABLE
    assert record.field_statuses["经营活动现金流三年 CAGR"] is DataStatus.NOT_APPLICABLE


def test_cagr_history_missing_stays_blank_status_instead_of_not_applicable() -> None:
    security = Security(Market.HK, "HKEX", "00700", "测试公司")
    current = FinancialPeriod(
        security.key,
        date(2025, 12, 31),
        2025,
        None,
        "HKD",
        100.0,
        60.0,
        10.0,
        8.0,
    )
    record = AnalysisRecord(security=security, current=current)

    Metrics_Calculate(record)

    assert record.field_statuses["营业收入三年 CAGR"] is DataStatus.MISSING
    assert record.field_statuses["归母净利润三年 CAGR"] is DataStatus.MISSING
    assert record.field_statuses["经营活动现金流三年 CAGR"] is DataStatus.MISSING
