from __future__ import annotations

from datetime import date

import httpx
import re


URL = (
    "https://emweb.securities.eastmoney.com/PC_HSF10/"
    "CapitalStockStructure/PageAjax"
)
SAMPLES = (
    ("SH601398", date(2006, 10, 27)),
    ("SH600941", date(2022, 1, 5)),
    ("SH601988", date(2006, 7, 5)),
    ("SZ300750", date(2018, 6, 11)),
)
HEADERS = {
    "Referer": "https://emweb.securities.eastmoney.com/",
    "User-Agent": "Mozilla/5.0",
}

for code, listing_date in SAMPLES:
    response = httpx.get(
        URL,
        params={"code": code},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json().get("lngbbd") or []
    rows.sort(key=lambda item: str(item.get("END_DATE") or ""))
    print(
        code,
        "listing=",
        listing_date.isoformat(),
        "rows=",
        len(rows),
        "min=",
        rows[0].get("END_DATE") if rows else None,
        "max=",
        rows[-1].get("END_DATE") if rows else None,
    )
    for row in rows[:8]:
        print(
            " ",
            row.get("END_DATE"),
            row.get("TOTAL_SHARES"),
            row.get("LISTED_A_SHARES"),
            row.get("CHANGE_REASON"),
        )

index_response = httpx.get(
    "https://emweb.securities.eastmoney.com/PC_HSF10/"
    "CapitalStockStructure/Index",
    params={"code": "SH600941", "type": "web"},
    headers=HEADERS,
    timeout=30,
)
index_response.raise_for_status()
print("INDEX HTML", len(index_response.text))
for marker in ("2022-01-05", "20475007209", "CapitalStockStructure/PageAjax"):
    print("INDEX CONTAINS", marker, marker in index_response.text)
for marker in ("seajs.config", "base:"):
    marker_index = index_response.text.find(marker)
    if marker_index >= 0:
        print("INDEX CONFIG", index_response.text[marker_index : marker_index + 1200])
for source in re.findall(r'<script[^>]+src=["\']([^"\']+)', index_response.text):
    print("SCRIPT", source)
for line in index_response.text.splitlines():
    if (
        "PageAjax" in line
        or "CapitalStockStructure" in line and ".js" in line
        or "EM.loader" in line
    ):
        print(line.strip())

for script_url in (
    "https://emweb.securities.eastmoney.com/PC_HSF10/Content/js/"
    "new/CapitalStockStructure.js?v=1.0.2.7054",
    "https://emweb.securities.eastmoney.com/PC_HSF10/Content/js/web/"
    "new/CapitalStockStructure.js?v=1.0.2.7054",
    "https://emweb.securities.eastmoney.com/PC_HSF10/Content/js/lib/"
    "new/CapitalStockStructure.js?v=1.0.2.7054",
    "https://emweb.securities.eastmoney.com/PC_HSF10/Content/js/"
    "lib/f10pcCommon.min.js?v=1.0.2.7054",
):
    script_response = httpx.get(script_url, headers=HEADERS, timeout=30)
    print("SCRIPT PROBE", script_url, script_response.status_code, len(script_response.text))
    for match in re.findall(
        r".{0,160}(?:PageAjax|lngbbd|baseUrl|loader).{0,240}",
        script_response.text,
        flags=re.IGNORECASE,
    ):
        print(match[:500])
    ajax_index = script_response.text.find('var url = "../CapitalStockStructure/PageAjax"')
    if ajax_index >= 0:
        print("CAPITAL AJAX", script_response.text[ajax_index - 800 : ajax_index + 2200])
    marker_index = script_response.text.find("EM.loader.use = function")
    if marker_index >= 0:
        print(script_response.text[marker_index : marker_index + 2500])
    for marker in ("seajs.config", "base:", "base :"):
        start = script_response.text.find(marker)
        if start >= 0:
            print("CONFIG", script_response.text[start : start + 800])
