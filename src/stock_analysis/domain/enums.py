from __future__ import annotations

from enum import StrEnum


class Market(StrEnum):
    A_SHARE = "A股"
    HK = "港股"


class MarketScopeMode(StrEnum):
    ALL = "全部公司"
    TOP_MARKET_CAP = "总市值前 N 家"


class TableSortMode(StrEnum):
    MARKET_CAP = "按最新总市值"
    REVENUE = "按分析年度营业收入"


class NetworkMode(StrEnum):
    SYSTEM_PROXY = "系统代理"
    DIRECT = "全部直连"
    DOMESTIC_DIRECT = "国内数据源优先直连"


class DataStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    OPTIONAL_MISSING = "optional_missing"
    SOURCE_UNAVAILABLE = "source_unavailable"
    CALCULATION_UNDEFINED = "calculation_undefined"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class PipelineRunResult(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CompanyStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    EXCLUDED = "excluded"


class WorkbookExportResult(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class SourceCapability(StrEnum):
    SECURITY_LIST = "security_list"
    FINANCIALS = "financials"
    QUOTE = "quote"
    IPO = "ipo"
    BLOCK_TRADE = "block_trade"
    FLOW = "flow"
