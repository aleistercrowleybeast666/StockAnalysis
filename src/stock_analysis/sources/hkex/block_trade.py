from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date

from stock_analysis.domain.enums import DataStatus
from stock_analysis.domain.models import BlockTradeData, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceError,
    SourceSchemaError,
    SourceValue,
)


@dataclass(slots=True, frozen=True)
class _DailyBlockTrades:
    traded_on: date
    values: dict[str, tuple[int, float]]


class HkexBlockTradeSource:
    """HKEX Daily Quotations fallback for annual Hong Kong block trades.

    ETNet calls pre-opening transactions of at least HKD30m and manual/special-lot
    transactions of at least HKD20m block trades.  HKEX Daily Quotations exposes
    the underlying P/M/X flags, so the same thresholds can be reproduced without
    treating ordinary auction/automatched transactions as block trades.
    """

    source_name = "HKEX"
    DAILY_URL_TEMPLATE = (
        "https://www.hkex.com.hk/eng/stat/smstat/dayquot_12m/"
        "d{traded_on:%y%m%d}e.htm"
    )
    TRADING_CALENDAR_URL = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    )
    _SECTION_START = "SALES RECORDS OVER $500,000"
    _SECTION_END = "AMENDMENT RECORDS FOR TRADE"
    _RANGE_SIZES = (2 * 1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024)
    _PREOPEN_MINIMUM_HKD = 30_000_000.0
    _MANUAL_MINIMUM_HKD = 20_000_000.0
    _STOCK_ROW_PATTERN = re.compile(
        r"(?ms)^\s*(\d{1,5})\s+[A-Z].*?(?=^\s*\d{1,5}\s+[A-Z]|\Z)"
    )
    _TRADE_PATTERN = re.compile(r"([PMX])\s*([\d,]+)-([\d.]+)")

    def __init__(
        self,
        hkex_client: HttpJsonClient,
        calendar_client: HttpJsonClient,
        *,
        concurrency: int = 4,
    ) -> None:
        self._hkex_client = hkex_client
        self._calendar_client = calendar_client
        self._concurrency = max(1, concurrency)

    def BlockTrades_Fetch(
        self,
        securities: list[Security],
        year: int,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict[str, SourceValue[BlockTradeData]]:
        if not securities:
            return {}
        try:
            trading_dates = self._TradingDates_Fetch(year)
            archive_start = self._ArchiveStart_Find(trading_dates)
        except Exception as error:
            return {
                security.key: self._Missing_Create(
                    security,
                    year,
                    DataStatus.ERROR,
                    f"HKEX 年度交易日或公开日报边界验证失败：{error}",
                )
                for security in securities
            }
        if archive_start is None:
            return {
                security.key: self._Missing_Create(
                    security,
                    year,
                    DataStatus.SOURCE_UNAVAILABLE,
                    f"HKEX 公开 Daily Quotations 未保留 {year} 年可验证日报",
                )
                for security in securities
            }

        year_end = date(year, 12, 31)
        required_starts: dict[str, date] = {}
        results: dict[str, SourceValue[BlockTradeData]] = {}
        for security in securities:
            if security.listing_date is not None and security.listing_date > year_end:
                results[security.key] = self._Missing_Create(
                    security,
                    year,
                    DataStatus.NOT_APPLICABLE,
                    f"证券于 {security.listing_date.isoformat()} 上市，{year} 年不适用",
                )
                continue
            required_start = max(
                date(year, 1, 1),
                security.listing_date or date(year, 1, 1),
            )
            first_required = next(
                (item for item in trading_dates if item >= required_start), None
            )
            if first_required is None:
                results[security.key] = self._Missing_Create(
                    security,
                    year,
                    DataStatus.NOT_APPLICABLE,
                    f"证券在 {year} 年没有适用的港股交易日",
                )
                continue
            if first_required < archive_start:
                results[security.key] = self._Missing_Create(
                    security,
                    year,
                    DataStatus.MISSING,
                    (
                        "HKEX Daily Quotations 为滚动公开档案；"
                        f"该证券所需首个交易日={first_required.isoformat()}，"
                        f"当前最早可验证日报={archive_start.isoformat()}；"
                        "无法证明完整年度，字段留空"
                    ),
                    archive_start=archive_start,
                )
                continue
            required_starts[security.key] = first_required

        eligible = [
            security for security in securities if security.key in required_starts
        ]
        if not eligible:
            return results
        first_fetch_date = min(required_starts.values())
        dates_to_fetch = [item for item in trading_dates if item >= first_fetch_date]
        report_total = len(dates_to_fetch)
        if progress_callback is not None:
            progress_callback(0, report_total)
        target_codes = {security.code for security in eligible}
        daily_values: dict[date, _DailyBlockTrades] = {}
        daily_errors: dict[date, str] = {}
        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            futures = {
                executor.submit(
                    self._DailyBlockTrades_Fetch, traded_on, target_codes
                ): traded_on
                for traded_on in dates_to_fetch
            }
            for report_completed, future in enumerate(as_completed(futures), 1):
                traded_on = futures[future]
                try:
                    daily_values[traded_on] = future.result()
                except Exception as error:
                    daily_errors[traded_on] = str(error)
                if progress_callback is not None:
                    progress_callback(report_completed, report_total)

        for security in eligible:
            required_start = required_starts[security.key]
            relevant_errors = [
                (traded_on, reason)
                for traded_on, reason in sorted(daily_errors.items())
                if traded_on >= required_start
            ]
            if relevant_errors:
                traded_on, reason = relevant_errors[0]
                results[security.key] = self._Missing_Create(
                    security,
                    year,
                    DataStatus.ERROR,
                    (
                        f"HKEX 年度区间共 {len(relevant_errors)} 个交易日报未能完整解析；"
                        f"首个={traded_on.isoformat()}：{reason}；字段留空"
                    ),
                    archive_start=archive_start,
                )
                continue
            trade_count = 0
            total_amount = 0.0
            report_count = 0
            for traded_on, daily in sorted(daily_values.items()):
                if traded_on < required_start:
                    continue
                report_count += 1
                value = daily.values.get(security.code)
                if value is None:
                    continue
                trade_count += value[0]
                total_amount += value[1]
            results[security.key] = SourceValue(
                BlockTradeData(
                    security.key,
                    year,
                    trade_count,
                    total_amount,
                    "HKD",
                ),
                Provenance_Create(
                    security,
                    "大宗交易",
                    self.source_name,
                    (
                        "HKEX Daily Quotations / Sales Records Over $500,000；"
                        f"区间={required_start.isoformat()}..{trading_dates[-1].isoformat()}；"
                        f"完整日报={report_count}；P≥HKD30m，M/X≥HKD20m"
                    ),
                    DataStatus.OK,
                    original_currency="HKD",
                    standard_currency="HKD",
                    primary_source="ETNet",
                    field_statuses={
                        "当年累计大宗交易笔数": DataStatus.OK,
                        "当年累计大宗交易金额": DataStatus.OK,
                    },
                ),
            )
        return results

    def _TradingDates_Fetch(self, year: int) -> list[date]:
        payload = self._calendar_client.RequestJson(
            self.TRADING_CALENDAR_URL,
            params={
                "param": (
                    f"hkHSI,day,{year}-01-01,{year}-12-31,400,qfq"
                )
            },
            request_id=f"hkex-trading-calendar-{year}",
            referer="https://gu.qq.com/hkHSI/gp",
            endpoint_key="hk-hsi-trading-calendar",
            headers=self._PageHeaders_Get(),
        )
        root = ((payload.get("data") or {}).get("hkHSI") or {})
        rows = root.get("qfqday") or root.get("day") or []
        values: list[date] = []
        for row in rows:
            if not isinstance(row, list) or not row:
                continue
            try:
                traded_on = date.fromisoformat(str(row[0]))
            except ValueError:
                continue
            if traded_on.year == year:
                values.append(traded_on)
        result = sorted(set(values))
        if not result:
            raise SourceSchemaError(f"恒生指数日线未返回 {year} 年交易日")
        return result

    def _ArchiveStart_Find(self, trading_dates: list[date]) -> date | None:
        low = 0
        high = len(trading_dates) - 1
        first_available: date | None = None
        while low <= high:
            middle = (low + high) // 2
            traded_on = trading_dates[middle]
            if self._DailyReport_Exists(traded_on):
                first_available = traded_on
                high = middle - 1
            else:
                low = middle + 1
        return first_available

    def _DailyReport_Exists(self, traded_on: date) -> bool:
        try:
            self._hkex_client.RequestBytes(
                self.DAILY_URL_TEMPLATE.format(traded_on=traded_on),
                request_id=f"hkex-daily-probe-{traded_on.isoformat()}",
                referer=(
                    "https://www.hkex.com.hk/Market-Data/Statistics/"
                    "Securities-Market"
                ),
                endpoint_key="hkex-daily-quotation-probe",
                headers={**self._PageHeaders_Get(), "Range": "bytes=0-0"},
            )
        except SourceError as error:
            if "HTTP 404" in str(error):
                return False
            raise
        return True

    def _DailyBlockTrades_Fetch(
        self, traded_on: date, target_codes: set[str]
    ) -> _DailyBlockTrades:
        last_error = "日报片段不含完整的大额成交区间"
        for size in self._RANGE_SIZES:
            payload = self._hkex_client.RequestBytes(
                self.DAILY_URL_TEMPLATE.format(traded_on=traded_on),
                request_id=(
                    f"hkex-daily-block-{traded_on.isoformat()}-{size}"
                ),
                referer=(
                    "https://www.hkex.com.hk/Market-Data/Statistics/"
                    "Securities-Market"
                ),
                endpoint_key="hkex-daily-quotation-block-section",
                headers={
                    **self._PageHeaders_Get(),
                    "Accept-Encoding": "identity",
                    "Range": f"bytes=-{size}",
                },
            )
            text = payload.decode("latin-1", errors="replace")
            start = text.rfind(self._SECTION_START)
            end = text.find(self._SECTION_END, start + 1) if start >= 0 else -1
            if start < 0 or end < 0:
                last_error = (
                    f"读取末尾 {size} 字节仍未取得完整的 "
                    f"{self._SECTION_START} 区间"
                )
                continue
            return _DailyBlockTrades(
                traded_on,
                self._BlockSection_Parse(text[start:end], target_codes),
            )
        raise SourceSchemaError(last_error)

    @classmethod
    def _BlockSection_Parse(
        cls, section: str, target_codes: set[str] | None = None
    ) -> dict[str, tuple[int, float]]:
        targets = target_codes or set()
        result: dict[str, tuple[int, float]] = {}
        for match in cls._STOCK_ROW_PATTERN.finditer(section):
            code = match.group(1).zfill(5)
            if targets and code not in targets:
                continue
            count = 0
            amount = 0.0
            for flag, quantity_text, price_text in cls._TRADE_PATTERN.findall(
                match.group(0)
            ):
                try:
                    quantity = int(quantity_text.replace(",", ""))
                    price = float(price_text)
                except ValueError:
                    continue
                consideration = quantity * price
                minimum = (
                    cls._PREOPEN_MINIMUM_HKD
                    if flag == "P"
                    else cls._MANUAL_MINIMUM_HKD
                )
                if consideration < minimum:
                    continue
                count += 1
                amount += consideration
            if count:
                result[code] = (count, amount)
        return result

    def _Missing_Create(
        self,
        security: Security,
        year: int,
        status: DataStatus,
        reason: str,
        *,
        archive_start: date | None = None,
    ) -> SourceValue[BlockTradeData]:
        archive_text = (
            f"；当前最早公开日报={archive_start.isoformat()}"
            if archive_start is not None
            else ""
        )
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "大宗交易",
                self.source_name,
                f"HKEX Daily Quotations；年度={year}{archive_text}",
                status,
                standard_currency="HKD",
                missing_reason=reason,
                primary_source="ETNet",
                field_statuses={
                    "当年累计大宗交易笔数": status,
                    "当年累计大宗交易金额": status,
                },
            ),
        )

    @staticmethod
    def _PageHeaders_Get() -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
            ),
        }
