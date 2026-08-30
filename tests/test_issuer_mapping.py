from stock_analysis.domain.enums import Market
from stock_analysis.domain.models import Security
from stock_analysis.sources.issuer_mapping import IssuerMapping_Find


def test_verified_ah_issuer_mapping_is_explicit_and_directional() -> None:
    hk = Security(Market.HK, "HKEX", "03308", "中际旭创")
    mapping = IssuerMapping_Find(hk)

    assert mapping is not None
    assert mapping.a_share_code == "300308"
    assert mapping.AShareSecurity_Create().key == "A股:300308"
    assert IssuerMapping_Find(
        Security(Market.HK, "HKEX", "00700", "腾讯控股")
    ) is None
