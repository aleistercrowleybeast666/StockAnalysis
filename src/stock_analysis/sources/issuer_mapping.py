from __future__ import annotations

from dataclasses import dataclass

from stock_analysis.domain.enums import Market
from stock_analysis.domain.models import Security


@dataclass(slots=True, frozen=True)
class IssuerSecurityMapping:
    hk_code: str
    a_share_exchange: str
    a_share_code: str
    issuer_name: str
    evidence: str

    def AShareSecurity_Create(self) -> Security:
        return Security(
            Market.A_SHARE,
            self.a_share_exchange,
            self.a_share_code,
            self.issuer_name,
        )


# Only mappings whose two securities belong to the same legal issuer are kept here.
# This intentionally remains a small, reviewable registry instead of fuzzy name matching.
_HK_TO_A_SHARE = {
    "03308": IssuerSecurityMapping(
        hk_code="03308",
        a_share_exchange="SZSE",
        a_share_code="300308",
        issuer_name="中际旭创",
        evidence="中际旭创股份有限公司：03308.HK / 300308.SZ",
    ),
}


def IssuerMapping_Find(security: Security) -> IssuerSecurityMapping | None:
    if security.market is not Market.HK:
        return None
    return _HK_TO_A_SHARE.get(security.code.zfill(5))
