from __future__ import annotations

from datetime import date

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market
from stock_analysis.domain.models import Quote, Security
from stock_analysis.pipeline.fetch import FetchCoordinator
from stock_analysis.pipeline.universe import Universe_Build, Universe_RankByMarketCap


def _Securities_Create(market: Market, count: int) -> list[Security]:
    width = 5 if market is Market.HK else 6
    exchange = "HKEX" if market is Market.HK else "SSE"
    return [
        Security(market, exchange, str(index + 1).zfill(width), f"{market.value}{index + 1}")
        for index in range(count)
    ]


class FakeUniverseCoordinator:
    def __init__(self, a_count: int, hk_count: int) -> None:
        self._pools = {
            Market.A_SHARE: _Securities_Create(Market.A_SHARE, a_count),
            Market.HK: _Securities_Create(Market.HK, hk_count),
        }

    def SecurityList_Fetch(self, market: Market, limit: int = 0) -> list[Security]:
        values = self._pools[market]
        return values[:limit] if limit > 0 else values


def _Counts_Get(securities: list[Security]) -> tuple[int, int]:
    return (
        sum(item.market is Market.A_SHARE for item in securities),
        sum(item.market is Market.HK for item in securities),
    )


def test_default_limits_select_all_companies_from_both_markets() -> None:
    config = AppConfig()
    result = Universe_Build(config, FakeUniverseCoordinator(200, 200))  # type: ignore[arg-type]
    assert len(result) == 400
    assert _Counts_Get(result) == (200, 200)


def test_market_cap_ranking_is_not_security_list_order() -> None:
    securities = _Securities_Create(Market.A_SHARE, 4)
    market_caps = [300.0, 400.0, 100.0, 500.0]
    quotes = {
        security.key: Quote(security.key, date.today(), 10.0, market_cap, "CNY")
        for security, market_cap in zip(securities, market_caps, strict=True)
    }
    ranked = Universe_RankByMarketCap(securities, quotes)
    assert [item.code for item in ranked[:2]] == ["000004", "000002"]


def test_market_cap_ranking_excludes_missing_and_uses_code_as_tie_breaker() -> None:
    securities = _Securities_Create(Market.HK, 4)
    quotes = {
        securities[0].key: Quote(securities[0].key, date.today(), 10.0, None, "HKD"),
        securities[1].key: Quote(securities[1].key, date.today(), 10.0, 50.0, "HKD"),
        securities[2].key: Quote(securities[2].key, date.today(), 10.0, 50.0, "HKD"),
        securities[3].key: None,
    }
    ranked = Universe_RankByMarketCap(securities, quotes)
    assert [item.code for item in ranked] == ["00002", "00003"]


def test_universe_filters_delisted_but_keeps_current_st() -> None:
    active_st = Security(Market.A_SHARE, "SSE", "600001", "ST 正常公司", is_st=True)
    delisted = Security(
        Market.A_SHARE,
        "SSE",
        "600002",
        "已退公司",
        listing_status="终止上市",
    )
    name_fallback = Security(Market.A_SHARE, "SSE", "600003", "样例退")
    coordinator = FakeUniverseCoordinator(0, 0)
    coordinator._pools[Market.A_SHARE] = [active_st, delisted, name_fallback]
    result = Universe_Build(
        AppConfig(markets=[Market.A_SHARE]), coordinator  # type: ignore[arg-type]
    )
    assert result == [active_st]


def test_include_st_toggle_only_filters_a_share_st_companies() -> None:
    a_share_st = Security(
        Market.A_SHARE, "SSE", "600001", "ST 样例", is_st=True
    )
    hk_name_with_st = Security(
        Market.HK, "HKEX", "00001", "ST-like HK name", is_st=True
    )
    coordinator = FakeUniverseCoordinator(0, 0)
    coordinator._pools[Market.A_SHARE] = [a_share_st]
    coordinator._pools[Market.HK] = [hk_name_with_st]
    result = Universe_Build(
        AppConfig(
            markets=[Market.A_SHARE, Market.HK],
            include_st=False,
        ),
        coordinator,  # type: ignore[arg-type]
    )
    assert result == [hk_name_with_st]


class FakeCachedListSource:
    source_name = "fake-list"

    def __init__(self, values: list[Security]) -> None:
        self.values = values
        self.calls = 0

    def SecurityList_Fetch(self, _market: Market, limit: int = 0) -> list[Security]:
        self.calls += 1
        return self.values[:limit] if limit > 0 else list(self.values)


def test_security_list_is_reused_only_within_current_run() -> None:
    source = FakeCachedListSource(_Securities_Create(Market.HK, 20))
    coordinator = FetchCoordinator(source)  # type: ignore[arg-type]
    result = coordinator.SecurityList_Fetch(Market.HK, 10)
    second = coordinator.SecurityList_Fetch(Market.HK, 10)
    assert len(result) == 10
    assert len(second) == 10
    assert source.calls == 1
    assert coordinator.reuse_count == 1


def test_abnormally_small_live_hk_pool_is_logged(caplog) -> None:
    source = FakeCachedListSource(_Securities_Create(Market.HK, 5))
    source.security_list_minimums = {Market.HK: 10}  # type: ignore[attr-defined]
    coordinator = FetchCoordinator(source)  # type: ignore[arg-type]
    result = coordinator.SecurityList_Fetch(Market.HK)
    assert len(result) == 5
    assert source.calls == 1
    assert "低于完整性阈值" in caplog.text
    assert "不使用跨运行缓存" in caplog.text
