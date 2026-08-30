from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime

from stock_analysis.domain.enums import DataStatus
from stock_analysis.domain.models import BlockTradeData, Security
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
    _ARCHIVE_PAGE_LIMIT = 10
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
        first_text = self._BlockNewsPage_Fetch(security, 1)
        page_count = self._BlockPageCount_Parse(first_text)
        entries = self._BlockNewsEntries_Parse(first_text, security.code, 1)
        pages_to_fetch: list[int]
        if page_count >= self._ARCHIVE_PAGE_LIMIT:
            pages_to_fetch = [self._ARCHIVE_PAGE_LIMIT]
        else:
            pages_to_fetch = list(range(2, page_count + 1))
        for page in pages_to_fetch:
            text = self._BlockNewsPage_Fetch(security, page)
            entries.extend(self._BlockNewsEntries_Parse(text, security.code, page))

        oldest_date = min((entry.published_on for entry in entries), default=None)
        year_start = date(year, 1, 1)
        complete = oldest_date is not None and oldest_date <= year_start
        if year == date.today().year and page_count < self._ARCHIVE_PAGE_LIMIT:
            complete = True
        if not entries and year == date.today().year:
            complete = page_count < self._ARCHIVE_PAGE_LIMIT
        if complete and page_count >= self._ARCHIVE_PAGE_LIMIT:
            known_pages = {1, self._ARCHIVE_PAGE_LIMIT}
            for page in range(2, self._ARCHIVE_PAGE_LIMIT):
                if page in known_pages:
                    continue
                text = self._BlockNewsPage_Fetch(security, page)
                entries.extend(self._BlockNewsEntries_Parse(text, security.code, page))
        entries_by_id = {entry.news_id: entry for entry in entries}
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
        return _BlockNewsList(selected, page_count, oldest_date, complete)

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
            archive_reason = (
                f"ETNet 公开列表已达 {news_list.page_count} 页上限"
                if news_list.page_count >= self._ARCHIVE_PAGE_LIMIT
                else f"ETNet 公开列表当前仅返回 {news_list.page_count} 页"
            )
            return self._Missing_Create(
                security,
                year,
                DataStatus.MISSING,
                (
                    f"{archive_reason}，"
                    f"最早可见日期为 {oldest}，晚于 {year}-01-01；"
                    "无法证明年度区间完整"
                ),
                news_list,
            )
        trade_count = 0
        total_amount = 0.0
        missing_details: list[str] = []
        for entry in news_list.entries:
            detail = details.get(entry.news_id)
            value = detail.values.get(security.code) if detail is not None else None
            if detail is None or detail.error is not None or value is None:
                missing_details.append(
                    f"{entry.news_id}:"
                    f"{detail.error if detail is not None else '明细缺失或未包含该代码'}"
                )
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
            f"页数={news_list.page_count}；最早可见={oldest}；"
            f"{year} 年明细={len(news_list.entries)} 篇"
        )

    @classmethod
    def _BlockPageCount_Parse(cls, text: str) -> int:
        pages = [
            int(value)
            for value in re.findall(r"quote_blocktrade\.php\?page=(\d+)", text, re.I)
        ]
        return min(max(pages, default=1), cls._ARCHIVE_PAGE_LIMIT)

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
