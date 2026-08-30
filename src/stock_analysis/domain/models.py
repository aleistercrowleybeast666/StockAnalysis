from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from stock_analysis.domain.enums import (
    CompanyStatus,
    DataStatus,
    Market,
    PipelineRunResult,
)


@dataclass(slots=True, frozen=True)
class Security:
    market: Market
    exchange: str
    code: str
    name: str
    security_type: str = "普通股"
    listing_status: str = "上市"
    listing_date: date | None = None
    is_st: bool = False
    is_financial: bool = False
    industry: str | None = None

    @property
    def key(self) -> str:
        return f"{self.market.value}:{self.code}"


@dataclass(slots=True, frozen=True)
class FinancialPeriod:
    security_key: str
    report_end: date
    fiscal_year: int
    announcement_date: date | None
    currency: str
    revenue: float | None
    operating_cost: float | None
    parent_net_profit: float | None
    operating_cash_flow: float | None
    original_currency: str | None = None
    fx_rate: float | None = None
    fx_date: date | None = None
    is_consolidated: bool | None = None
    is_restatement: bool | None = None
    quality_note: str | None = None


@dataclass(slots=True, frozen=True)
class Quote:
    security_key: str
    quote_date: date
    price: float | None
    market_cap: float | None
    currency: str


@dataclass(slots=True, frozen=True)
class IPOInfo:
    security_key: str
    listing_date: date | None
    issue_price: float | None
    issued_shares: float | None
    post_issue_total_shares: float | None
    issue_market_cap: float | None
    approximate: bool = False


@dataclass(slots=True, frozen=True)
class FlowData:
    security_key: str
    end_date: date
    five_day_net: float | None
    one_month_net: float | None
    currency: str


@dataclass(slots=True, frozen=True)
class BlockTradeData:
    security_key: str
    year: int
    trade_count: int | None
    total_amount: float | None
    currency: str


@dataclass(slots=True, frozen=True)
class Provenance:
    market: Market
    code: str
    company_name: str
    field_group: str
    source_name: str
    source_ref: str
    fetched_at: datetime
    original_currency: str | None
    standard_currency: str | None
    status: DataStatus
    missing_reason: str | None = None
    approximate: bool = False
    primary_source: str | None = None
    field_statuses: dict[str, DataStatus] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AnalysisIssue:
    market: Market
    code: str
    company_name: str
    stage: str
    reason: str
    source_name: str | None = None
    field_name: str | None = None
    field_status: DataStatus = DataStatus.MISSING
    is_core: bool = False
    optional: bool = False
    primary_source: str | None = None
    endpoint: str | None = None
    fetched_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class AnalysisMetrics:
    revenue_growth: float | None = None
    revenue_cagr: float | None = None
    gross_margin: float | None = None
    gross_margin_yoy_change: float | None = None
    gross_margin_three_year_change: float | None = None
    net_margin: float | None = None
    profit_growth: float | None = None
    profit_cagr: float | None = None
    cash_growth: float | None = None
    cash_cagr: float | None = None
    market_cap_growth: float | None = None


@dataclass(slots=True)
class AnalysisRecord:
    security: Security
    current: FinancialPeriod | None = None
    previous: FinancialPeriod | None = None
    three_year_base: FinancialPeriod | None = None
    quote: Quote | None = None
    ipo: IPOInfo | None = None
    flow: FlowData | None = None
    block_trade: BlockTradeData | None = None
    provenance: list[Provenance] = field(default_factory=list)
    issues: list[AnalysisIssue] = field(default_factory=list)
    metrics: AnalysisMetrics = field(default_factory=AnalysisMetrics)
    field_statuses: dict[str, DataStatus] = field(default_factory=dict)
    excluded_reason: str | None = None

    @property
    def has_core_financials(self) -> bool:
        return self.current is not None and self.current.revenue is not None

    @property
    def is_partial(self) -> bool:
        return self.company_status is CompanyStatus.PARTIAL

    @property
    def company_status(self) -> CompanyStatus:
        if self.excluded_reason:
            return CompanyStatus.EXCLUDED
        if not self.has_core_financials:
            return CompanyStatus.FAILED
        if any(issue.is_core for issue in self.issues):
            return CompanyStatus.FAILED
        partial_statuses = {
            DataStatus.MISSING,
            DataStatus.ERROR,
            DataStatus.SOURCE_UNAVAILABLE,
            DataStatus.CALCULATION_UNDEFINED,
        }
        if any(
            not issue.optional and issue.field_status in partial_statuses
            for issue in self.issues
        ):
            return CompanyStatus.PARTIAL
        return CompanyStatus.SUCCESS


@dataclass(slots=True, frozen=True)
class RunProgress:
    stage: str
    current_company: str
    completed: int
    total: int
    success: int
    missing: int
    failed: int
    message: str
    excluded: int = 0
    overall_completed: int = 0
    overall_total: int = 0


@dataclass(slots=True)
class MarketSelectionStats:
    market: Market
    scope: str
    identified_count: int = 0
    ranked_count: int = 0
    selected_target_count: int | None = None
    candidate_count: int = 0
    generated_count: int = 0
    skipped_no_core_financial_count: int = 0
    skipped_delisted_count: int = 0


@dataclass(slots=True)
class RunSummary:
    result: PipelineRunResult
    started_at: datetime
    finished_at: datetime
    output_path: Path | None
    records: list[AnalysisRecord]
    issues: list[AnalysisIssue]
    success_count: int
    partial_count: int
    failed_count: int
    config_snapshot: dict[str, Any]
    excluded_count: int = 0
    performance: dict[str, Any] = field(default_factory=dict)
    market_stats: dict[Market, MarketSelectionStats] = field(default_factory=dict)
