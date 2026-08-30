from __future__ import annotations

import re

from stock_analysis.domain.enums import Market

_HK_VERIFIED_FINANCIAL_CODES = {
    "00005",  # HSBC
    "00011",  # Hang Seng Bank
    "00267",  # CITIC financial holding group
    "00388",  # HKEX
    "00939",  # CCB
    "00945",  # Manulife
    "00998",  # CITIC Bank
    "01288",  # ABC
    "01299",  # AIA
    "01336",  # New China Life Insurance
    "01339",  # PICC Group
    "01398",  # ICBC
    "01658",  # PSBC
    "01776",  # GF Securities
    "01988",  # Minsheng Bank
    "02318",  # Ping An
    "02328",  # PICC P&C
    "02378",  # Prudential
    "02388",  # BOC Hong Kong
    "02601",  # CPIC
    "02611",  # GTHT / Guotai Haitong
    "02628",  # China Life
    "02888",  # Standard Chartered
    "03328",  # Bank of Communications
    "03968",  # CMB
    "03988",  # Bank of China
    "06030",  # CITIC Securities
    "06886",  # HTSC
}


def Security_FinancialClassify(
    name: str,
    industry: str | None = None,
    business: str | None = None,
    security_code: str | None = None,
) -> bool:
    normalized_name = " ".join(str(name or "").upper().split())
    normalized_industry = " ".join(str(industry or "").upper().split())
    normalized_business = " ".join(str(business or "").upper().split())
    normalized_code = re.sub(r"\D", "", str(security_code or "")).zfill(5)
    if normalized_code in _HK_VERIFIED_FINANCIAL_CODES:
        return True
    if any(
        keyword in f"{normalized_industry} {normalized_business}"
        for keyword in (
            "金融",
            "银行",
            "保险",
            "证券",
            "BANK",
            "INSURANCE",
            "FINANCIAL",
            "SECURITIES",
            "BROKERAGE",
            "INVESTMENT BANK",
            "ASSET MANAGEMENT",
            "STOCK EXCHANGE",
        )
    ):
        return True
    return any(
        keyword in normalized_name
        for keyword in (
            "银行",
            "证券",
            "保险",
            "信托",
            "金融控股",
            " BANK",
            "BANK OF ",
            "INSURANCE",
            "SECURITIES",
            "FINANCIAL",
            "HSBC",
            "HANG SENG",
            "AIA GROUP",
            "BOC HONG KONG",
            "ICBC",
            "CCB",
            "PRUDENTIAL",
            "MANULIFE",
            "PING AN",
            "CHINA LIFE",
            "CITIC SEC",
            "GF SEC",
            "PICC P&C",
            "PICC GROUP",
            "BANKCOMM",
            "STANCHART",
            "NCI",
            "GUOTAI HAITONG",
            "HONG KONG EXCHANGES",
            "HKEX",
        )
    )


def Security_NormalizeCode(value: str, market: Market) -> str:
    digits = re.sub(r"\D", "", value)
    if market is Market.HK:
        if not 1 <= len(digits) <= 5:
            raise ValueError(f"无效港股代码：{value}")
        return digits.zfill(5)
    if len(digits) != 6:
        raise ValueError(f"无效 A 股代码：{value}")
    return digits


def Security_ExchangeFromCode(code: str) -> str:
    if code.startswith(("60", "68")):
        return "SSE"
    if code.startswith(("00", "30")):
        return "SZSE"
    if code.startswith(("4", "8", "9")):
        return "BSE"
    return "UNKNOWN"


def Security_Secucode(security_code: str, market: Market) -> str:
    if market is Market.HK:
        return f"{Security_NormalizeCode(security_code, market)}.HK"
    code = Security_NormalizeCode(security_code, market)
    exchange = Security_ExchangeFromCode(code)
    suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(exchange, "")
    return f"{code}.{suffix}" if suffix else code
