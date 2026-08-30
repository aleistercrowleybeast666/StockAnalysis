from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from stock_analysis.config.models import AppConfig
from stock_analysis.domain.enums import Market
from stock_analysis.domain.models import Quote, Security
from stock_analysis.pipeline.fetch import FetchCoordinator

_TERMINATED_STATUSES = {
    "终止上市",
    "已退市",
    "退市",
    "DELISTED",
    "WITHDRAWN",
}


@dataclass(slots=True)
class UniverseBuildResult:
    securities: list[Security]
    identified_counts: dict[Market, int] = field(default_factory=dict)
    delisted_counts: dict[Market, int] = field(default_factory=dict)


def Security_CurrentlyListed_Check(security: Security) -> bool:
    status = security.listing_status.strip().upper()
    if status in _TERMINATED_STATUSES:
        return False
    normalized_name = "".join(security.name.upper().split())
    return not (
        normalized_name.endswith("退")
        or "退市" in normalized_name
        or normalized_name.endswith("DELISTED")
    )


def Universe_RankByMarketCap(
    securities: Sequence[Security], quotes: Mapping[str, Quote | None]
) -> list[Security]:
    ranked = [
        security
        for security in securities
        if quotes.get(security.key) is not None
        and quotes[security.key].market_cap is not None  # type: ignore[union-attr]
        and quotes[security.key].market_cap > 0  # type: ignore[union-attr]
    ]
    return sorted(
        ranked,
        key=lambda security: (
            -float(quotes[security.key].market_cap),  # type: ignore[union-attr]
            security.code,
        ),
    )


def Universe_BuildDetailed(
    config: AppConfig, coordinator: FetchCoordinator
) -> UniverseBuildResult:
    logger = logging.getLogger("stock_analysis.pipeline.universe")
    pools: dict[Market, list[Security]] = {}
    identified_counts: dict[Market, int] = {}
    delisted_counts: dict[Market, int] = {}
    for market in config.markets:
        securities = coordinator.SecurityList_Fetch(market)
        identified_counts[market] = len(securities)
        delisted_count = sum(
            not Security_CurrentlyListed_Check(security) for security in securities
        )
        delisted_counts[market] = delisted_count
        filtered = [
            security
            for security in securities
            if Security_CurrentlyListed_Check(security)
            and (
                market is not Market.A_SHARE
                or config.include_st
                or not security.is_st
            )
            and (config.include_financial or not security.is_financial)
        ]
        pools[market] = filtered
        logger.info(
            "%s 证券池：抓取=%s，终止上市过滤=%s，正常普通股=%s",
            market.value,
            len(securities),
            delisted_count,
            len(filtered),
        )

    logger.info(
        "证券池选择完成：%s",
        "，".join(f"{market.value}={len(pools[market])}" for market in config.markets),
    )

    interleaved: list[Security] = []
    for index in range(max((len(group) for group in pools.values()), default=0)):
        for market in config.markets:
            group = pools[market]
            if index < len(group):
                interleaved.append(group[index])
    return UniverseBuildResult(interleaved, identified_counts, delisted_counts)


def Universe_Build(config: AppConfig, coordinator: FetchCoordinator) -> list[Security]:
    return Universe_BuildDetailed(config, coordinator).securities
