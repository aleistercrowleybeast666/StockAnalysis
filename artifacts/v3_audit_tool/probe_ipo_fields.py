from __future__ import annotations

import httpx


URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
CODES = ("601398.SH", "600941.SH", "601988.SH", "300750.SZ")
HEADERS = {
    "Referer": "https://emweb.securities.eastmoney.com/",
    "User-Agent": "Mozilla/5.0",
}

for code in CODES:
    response = httpx.get(
        URL,
        params={
            "reportName": "RPT_PCF10_ORG_ISSUEINFO",
            "columns": "ALL",
            "filter": f'(SECUCODE="{code}")',
            "pageNumber": 1,
            "pageSize": 5,
            "source": "HSF10",
            "client": "PC",
        },
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    rows = ((response.json().get("result") or {}).get("data") or [])
    row = rows[0] if rows else {}
    print("\n", code, "fields=", len(row))
    for key in sorted(row):
        if any(
            marker in key
            for marker in ("ISSUE", "SHARE", "CAPITAL", "RATIO", "PERCENT", "LIST")
        ):
            print(key, "=", row[key])
