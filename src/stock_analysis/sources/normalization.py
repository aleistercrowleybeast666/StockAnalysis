from __future__ import annotations

import re

from stock_analysis.domain.enums import Market


def Security_FinancialClassify(name: str, industry: str | None = None) -> bool:
    normalized_name = " ".join(str(name or "").upper().split())
    normalized_industry = " ".join(str(industry or "").upper().split())
    if any(
        keyword in normalized_industry
        for keyword in (
            "金融",
            "银行",
            "保险",
            "证券",
            "BANK",
            "INSURANCE",
            "FINANCIAL",
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
