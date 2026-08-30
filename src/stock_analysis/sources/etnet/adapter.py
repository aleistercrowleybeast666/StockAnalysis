from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime

from stock_analysis.domain.calculations import Calculation_IssueMarketCap
from stock_analysis.domain.enums import DataStatus
from stock_analysis.domain.models import BlockTradeData, IPOInfo, Security
from stock_analysis.sources.base import (
    HttpJsonClient,
    Provenance_Create,
    SourceError,
    SourceValue,
)


@dataclass(slots=True, frozen=True)
class _BlockNewsEntry:
    news_id: str
    page: int
    published_on: date
    code: str


@dataclass(slots=True, frozen=True)
class _BlockNewsList:
    entries: tuple[_BlockNewsEntry, ...]
    page_count: int
    oldest_date: date | None
    complete_for_year: bool
    stop_reason: str


@dataclass(slots=True, frozen=True)
class _BlockNewsDetail:
    values: dict[str, tuple[int, float]]
    error: str | None = None


class EtnetSource:
    source_name = "ETNet"
    BLOCK_LIST_URL = (
        "https://www.etnet.com.hk/www/eng/stocks/realtime/quote_blocktrade.php"
    )
    BLOCK_DETAIL_URL = (
        "https://www.etnet.com.hk/www/eng/stocks/realtime/"
        "quote_blocktrade_detail.php"
    )
    COMPANY_URL = "https://www.etnet.com.hk/www/eng/stocks/realtime/quote_ci_brief.php"
    _ARCHIVE_SAFETY_PAGE_LIMIT = 250
    _DETAIL_PATTERN = re.compile(
        r"(?:<p[^>]*class=['\"]date['\"][^>]*>|"
        r"<span[^>]*class=['\"]date['\"][^>]*>)\s*"
        r"(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}.*?"
        r"href=['\"]([^'\"]*quote_blocktrade_detail\.php\?[^'\"]+)['\"]",
        re.I | re.S,
    )
    _NUMBER_WORDS = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }

    def __init__(self, client: HttpJsonClient, *, concurrency: int = 4) -> None:
        self._client = client
        self._concurrency = max(1, concurrency)

    def BlockTrade_Fetch(
        self, security: Security, year: int
    ) -> SourceValue[BlockTradeData]:
        return self.BlockTrades_Fetch([security], year)[security.key]

    def BlockTrades_Fetch(
        self, securities: list[Security], year: int
    ) -> dict[str, SourceValue[BlockTradeData]]:
        if not securities:
            return {}
        news_lists: dict[str, _BlockNewsList] = {}
        list_errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            futures = {
                executor.submit(self._BlockNewsList_Fetch, security, year): security
                for security in securities
            }
            for future in as_completed(futures):
                security = futures[future]
                try:
                    news_lists[security.key] = future.result()
                except Exception as error:
                    list_errors[security.key] = str(error)

        detail_entries: dict[str, _BlockNewsEntry] = {}
        for security in securities:
            news_list = news_lists.get(security.key)
            if news_list is None or not news_list.complete_for_year:
                continue
            for entry in news_list.entries:
                detail_entries.setdefault(entry.news_id, entry)

        details: dict[str, _BlockNewsDetail] = {}
        with ThreadPoolExecutor(max_workers=self._concurrency) as executor:
            futures = {
                executor.submit(self._BlockNewsDetail_Fetch, entry): news_id
                for news_id, entry in detail_entries.items()
            }
            for future in as_completed(futures):
                news_id = futures[future]
                try:
                    details[news_id] = future.result()
                except Exception as error:
                    details[news_id] = _BlockNewsDetail({}, str(error))

        return {
            security.key: self._BlockTradeResult_Create(
                security,
                year,
                news_lists.get(security.key),
                list_errors.get(security.key),
                details,
            )
            for security in securities
        }

    def _BlockNewsList_Fetch(self, security: Security, year: int) -> _BlockNewsList:
        year_start = date(year, 1, 1)
        entries_by_id: dict[str, _BlockNewsEntry] = {}
        page_signatures: set[tuple[str, ...]] = set()
        oldest_date: date | None = None
        page_count = 0
        complete = False
        stop_reason = "达到安全页数"
        for page in range(1, self._ARCHIVE_SAFETY_PAGE_LIMIT + 1):
            text = self._BlockNewsPage_Fetch(security, page)
            page_count = page
            page_entries = self._BlockNewsEntries_Parse(text, security.code, page)
            signature = tuple(entry.news_id for entry in page_entries)
            if signature and signature in page_signatures:
                stop_reason = f"第 {page} 页与前页内容重复"
                break
            if signature:
                page_signatures.add(signature)
            new_entries = [
                entry for entry in page_entries if entry.news_id not in entries_by_id
            ]
            if not page_entries:
                stop_reason = f"第 {page} 页没有新闻记录"
                break
            if not new_entries:
                stop_reason = f"第 {page} 页没有新增新闻 ID"
                break
            for entry in new_entries:
                entries_by_id[entry.news_id] = entry
            oldest_date = min(
                (entry.published_on for entry in entries_by_id.values()),
                default=None,
            )
            if oldest_date is not None and oldest_date <= year_start:
                complete = True
                stop_reason = f"最早日期已跨过 {year_start.isoformat()}"
                break
        selected = tuple(
            sorted(
                (
                    entry
                    for entry in entries_by_id.values()
                    if entry.published_on.year == year
                ),
                key=lambda entry: (entry.published_on, entry.news_id),
            )
        )
        return _BlockNewsList(
            selected, page_count, oldest_date, complete, stop_reason
        )

    def IPO_Fetch(self, security: Security) -> SourceValue[IPOInfo]:
        payload = self._client.RequestBytes(
            self.COMPANY_URL,
            params={"code": str(int(security.code))},
            request_id=f"etnet-company-{security.code}",
            referer=(
                "https://www.etnet.com.hk/www/eng/stocks/realtime/"
                f"quote.php?code={int(security.code)}"
            ),
            endpoint_key=f"etnet-company-{security.code}",
            headers=self._PageHeaders_Get(),
        )
        text = html.unescape(payload.decode("utf-8", errors="replace"))
        listing_match = re.search(
            r"Listing\s+Date\s*</td>\s*<td[^>]*>\s*(\d{2}/\d{2}/\d{4})",
            text,
            re.I | re.S,
        )
        price_match = re.search(
            r"Listing\s+Price[^<]*</td>\s*<td[^>]*>\s*([\d,.]+)",
            text,
            re.I | re.S,
        )
        listing_date = None
        if listing_match is not None:
            try:
                listing_date = datetime.strptime(
                    listing_match.group(1), "%d/%m/%Y"
                ).date()
            except ValueError:
                listing_date = None
        issue_price = self._Number_Parse(price_match.group(1)) if price_match else None
        issue_market_cap, approximate = Calculation_IssueMarketCap(
            issue_price, None, None
        )
        value = IPOInfo(
            security.key,
            listing_date,
            issue_price,
            None,
            None,
            issue_market_cap,
            approximate,
        )
        has_data = listing_date is not None or issue_price is not None
        statuses = {
            "上市日期": DataStatus.OK if listing_date is not None else DataStatus.MISSING,
            "发行价": DataStatus.OK if issue_price is not None else DataStatus.MISSING,
            "发行股数": DataStatus.MISSING,
            "发行后总股本": DataStatus.MISSING,
            "发行时总市值": DataStatus.MISSING,
        }
        return SourceValue(
            value if has_data else None,
            Provenance_Create(
                security,
                "上市与发行信息",
                self.source_name,
                f"quote_ci_brief.php?code={int(security.code)}（Listing Date/Price）",
                DataStatus.OK if has_data else DataStatus.MISSING,
                original_currency="HKD",
                standard_currency="HKD",
                missing_reason=(
                    "ETNet 公司资料页未解析到上市日期或上市价"
                    if not has_data
                    else "ETNet 仅补上市日期/上市价；不以当前已发行股本冒充发行后总股本"
                ),
                primary_source="东方财富",
                field_statuses=statuses,
            ),
        )

    def _BlockNewsPage_Fetch(self, security: Security, page: int) -> str:
        payload = self._client.RequestBytes(
            self.BLOCK_LIST_URL,
            params={"code": str(int(security.code)), "page": page},
            request_id=f"etnet-block-list-{security.code}-page-{page}",
            referer=(
                "https://www.etnet.com.hk/www/eng/stocks/realtime/"
                f"quote.php?code={int(security.code)}"
            ),
            endpoint_key=f"etnet-block-list-{security.code}",
            headers=self._PageHeaders_Get(),
        )
        return payload.decode("utf-8", errors="replace")

    def _BlockNewsDetail_Fetch(self, entry: _BlockNewsEntry) -> _BlockNewsDetail:
        payload = self._client.RequestBytes(
            self.BLOCK_DETAIL_URL,
            params={
                "newsid": entry.news_id,
                "page": entry.page,
                "code": str(int(entry.code)),
            },
            request_id=f"etnet-block-detail-{entry.news_id}",
            referer=(
                f"{self.BLOCK_LIST_URL}?code={int(entry.code)}&page={entry.page}"
            ),
            endpoint_key=f"etnet-block-detail-{entry.news_id}",
            headers=self._PageHeaders_Get(),
        )
        values = self._BlockNewsDetail_Parse(
            payload.decode("utf-8", errors="replace")
        )
        if not values:
            raise SourceError(f"ETNet 明细 {entry.news_id} 未解析到公司笔数和金额")
        return _BlockNewsDetail(values)

    def _BlockTradeResult_Create(
        self,
        security: Security,
        year: int,
        news_list: _BlockNewsList | None,
        list_error: str | None,
        details: dict[str, _BlockNewsDetail],
    ) -> SourceValue[BlockTradeData]:
        if news_list is None:
            return self._Missing_Create(
                security,
                year,
                DataStatus.ERROR,
                list_error or "ETNet 年度列表请求失败",
            )
        if not news_list.complete_for_year:
            oldest = (
                news_list.oldest_date.isoformat()
                if news_list.oldest_date is not None
                else "未取得"
            )
            return self._Missing_Create(
                security,
                year,
                DataStatus.MISSING,
                (
                    f"ETNet 已连续读取 {news_list.page_count} 页，"
                    f"最早可见日期为 {oldest}，晚于 {year}-01-01；"
                    f"停止原因：{news_list.stop_reason}；无法证明年度区间完整"
                ),
                news_list,
            )
        trade_count = 0
        total_amount = 0.0
        missing_details: list[str] = []
        for entry in news_list.entries:
            detail = details.get(entry.news_id)
            value = detail.values.get(security.code) if detail is not None else None
            if detail is None or detail.error is not None:
                missing_details.append(
                    f"{entry.news_id}:"
                    f"{detail.error if detail is not None else '明细缺失或未包含该代码'}"
                )
                continue
            if value is None:
                continue
            trade_count += value[0]
            total_amount += value[1]
        if missing_details:
            return self._Missing_Create(
                security,
                year,
                DataStatus.ERROR,
                (
                    f"ETNet 年度列表完整，但 {len(missing_details)} 篇明细未能可靠解析；"
                    f"首项={missing_details[0]}"
                ),
                news_list,
            )
        value = BlockTradeData(
            security.key,
            year,
            trade_count,
            total_amount,
            "HKD",
        )
        return SourceValue(
            value,
            Provenance_Create(
                security,
                "大宗交易",
                self.source_name,
                self._SourceRef_Get(security, year, news_list),
                DataStatus.OK,
                original_currency="HKD",
                standard_currency="HKD",
                primary_source=self.source_name,
                field_statuses={
                    "当年累计大宗交易笔数": DataStatus.OK,
                    "当年累计大宗交易金额": DataStatus.OK,
                },
            ),
        )

    def _Missing_Create(
        self,
        security: Security,
        year: int,
        status: DataStatus,
        reason: str,
        news_list: _BlockNewsList | None = None,
    ) -> SourceValue[BlockTradeData]:
        source_ref = (
            self._SourceRef_Get(security, year, news_list)
            if news_list is not None
            else f"quote_blocktrade.php?code={int(security.code)}；年度={year}"
        )
        return SourceValue(
            None,
            Provenance_Create(
                security,
                "大宗交易",
                self.source_name,
                source_ref,
                status,
                standard_currency="HKD",
                missing_reason=reason,
                primary_source=self.source_name,
                field_statuses={
                    "当年累计大宗交易笔数": status,
                    "当年累计大宗交易金额": status,
                },
            ),
        )

    @staticmethod
    def _SourceRef_Get(
        security: Security, year: int, news_list: _BlockNewsList
    ) -> str:
        oldest = (
            news_list.oldest_date.isoformat()
            if news_list.oldest_date is not None
            else "无记录"
        )
        return (
            f"quote_blocktrade.php?code={int(security.code)}；"
            f"实际读取页数={news_list.page_count}；最早可见={oldest}；"
            f"停止原因={news_list.stop_reason}；"
            f"{year} 年明细={len(news_list.entries)} 篇"
        )

    @classmethod
    def _BlockPageCount_Parse(cls, text: str) -> int:
        pages = [
            int(value)
            for value in re.findall(r"quote_blocktrade\.php\?page=(\d+)", text, re.I)
        ]
        return max(pages, default=1)

    @staticmethod
    def _Number_Parse(value: str) -> float | None:
        try:
            return float(value.replace(",", "").strip())
        except (AttributeError, ValueError):
            return None

    @classmethod
    def _BlockNewsEntries_Parse(
        cls, text: str, code: str, page: int
    ) -> list[_BlockNewsEntry]:
        result: list[_BlockNewsEntry] = []
        for day_text, link in cls._DETAIL_PATTERN.findall(text):
            decoded_link = html.unescape(link)
            news_match = re.search(r"[?&]newsid=(\d+)", decoded_link, re.I)
            if news_match is None:
                continue
            try:
                published_on = datetime.strptime(day_text, "%d/%m/%Y").date()
            except ValueError:
                continue
            result.append(
                _BlockNewsEntry(news_match.group(1), page, published_on, code)
            )
        return result

    @classmethod
    def _BlockNewsDetail_Parse(cls, text: str) -> dict[str, tuple[int, float]]:
        content_match = re.search(
            r"id=['\"]NewsContent['\"][^>]*>(.*?)</article>", text, re.I | re.S
        )
        if content_match is None:
            return {}
        content = html.unescape(content_match.group(1))
        values: dict[str, tuple[int, float]] = {}
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", content, re.I | re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
            if len(cells) < 4:
                continue
            company = cls._HtmlText_Get(cells[0])
            code_match = re.search(r"\((\d{1,5})\)", company)
            count = cls._TradeCount_Parse(cls._HtmlText_Get(cells[1]))
            amount = cls._HkdAmount_Parse(cls._HtmlText_Get(cells[-1]))
            if code_match is None or count is None or amount is None:
                continue
            values[code_match.group(1).zfill(5)] = (count, amount)
        if values:
            return values

        plain = cls._HtmlText_Get(content)
        code_match = re.search(r"\((\d{1,5})\)", plain)
        count = cls._TradeCount_Parse(plain)
        amount_match = re.search(
            r"(?:deal|deals|trade|trades).*?"
            r"(?:amounted\s+to|worth)\s+(HK\$\s*[\d,.]+\s*[KMBT]?)",
            plain,
            re.I | re.S,
        )
        amount = cls._HkdAmount_Parse(amount_match.group(1)) if amount_match else None
        if code_match is None or count is None or amount is None:
            return {}
        return {code_match.group(1).zfill(5): (count, amount)}

    @classmethod
    def _TradeCount_Parse(cls, value: str) -> int | None:
        match = re.search(
            r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b"
            r"(?:\s+[a-z-]+){0,4}\s+trades?\b",
            value,
            re.I,
        )
        if match is not None:
            token = match.group(1).lower()
            return int(token) if token.isdigit() else cls._NUMBER_WORDS[token]
        if re.search(r"\b(?:a|an)\b(?:\s+[a-z-]+){0,4}\s+trade\b", value, re.I):
            return 1
        return None

    @staticmethod
    def _HkdAmount_Parse(value: str) -> float | None:
        match = re.search(r"HK\$\s*([\d,.]+)\s*([KMBT]?)", value, re.I)
        if match is None:
            return None
        try:
            number = float(match.group(1).replace(",", ""))
        except ValueError:
            return None
        scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(
            match.group(2).upper(), 1.0
        )
        return number * scale

    @staticmethod
    def _HtmlText_Get(fragment: str) -> str:
        text = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", html.unescape(text)).strip()

    @staticmethod
    def _PageHeaders_Get() -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
            ),
        }

    def close(self) -> None:
        self._client.close()
