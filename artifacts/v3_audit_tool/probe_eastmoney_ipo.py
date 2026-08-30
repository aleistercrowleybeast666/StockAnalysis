from __future__ import annotations

import json

import httpx


URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
SAMPLES = (
    ("A", "RPT_PCF10_ORG_ISSUEINFO", "600519.SH", "HSF10"),
    ("H", "RPT_HKF10_INFO_SECURITYINFO", "00700.HK", "F10"),
)

for tag, report, code, source in SAMPLES:
    response = httpx.get(
        URL,
        params={
            "reportName": report,
            "columns": "ALL",
            "filter": f'(SECUCODE="{code}")',
            "pageNumber": 1,
            "pageSize": 5,
            "source": source,
            "client": "PC",
        },
        headers={
            "Referer": "https://emweb.securities.eastmoney.com/",
            "User-Agent": "Mozilla/5.0",
        },
        timeout=30,
    )
    print(tag, response.status_code, len(response.content))
    payload = response.json()
    rows = ((payload.get("result") or {}).get("data") or [])
    print("rows", len(rows))
    print(json.dumps(rows[0] if rows else {}, ensure_ascii=True, indent=2))

response = httpx.get(
    URL,
    params={
        "reportName": "RPT_HKF10_INFO_EQUITY",
        "columns": "SECUCODE,CHANGE_DATE,HK_SHARES,CHANGE_REASON,NOTICE_DATE",
        "filter": '(SECUCODE="00700.HK")',
        "pageNumber": 1,
        "pageSize": 2000,
        "sortTypes": "1",
        "sortColumns": "CHANGE_DATE",
        "source": "F10",
        "client": "PC",
    },
    headers={
        "Referer": "https://emweb.securities.eastmoney.com/",
        "User-Agent": "Mozilla/5.0",
    },
    timeout=30,
)
payload = response.json()
result = payload.get("result") or {}
rows = result.get("data") or []
print("H-EQUITY", response.status_code, len(response.content), len(rows), result.get("pages"))
print(json.dumps(rows[:15], ensure_ascii=True, indent=2))
print("H-EQUITY-LAST")
print(json.dumps(rows[-3:], ensure_ascii=True, indent=2))
