from __future__ import annotations

from stock_analysis.domain.models import FinancialPeriod


def Period_Select(
    periods: list[FinancialPeriod], fiscal_year: int
) -> FinancialPeriod | None:
    candidates = [period for period in periods if period.fiscal_year == fiscal_year]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda period: (
            period.report_end,
            period.announcement_date or period.report_end,
        ),
    )

