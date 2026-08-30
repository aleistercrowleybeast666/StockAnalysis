from __future__ import annotations

import httpx

from stock_analysis.sources.parsers import Parser_ParseHtmlTable


for code, listing_date in (
    ("600941", "2022-01-05"),
    ("601398", "2006-10-27"),
    ("601988", "2006-07-05"),
    ("300750", "2018-06-11"),
):
    response = httpx.get(
        f"https://basic.10jqka.com.cn/{code}/equity.html",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    print(code, response.headers.get("content-type"), len(response.content))
    for encoding in ("utf-8", "gb18030"):
        text = response.content.decode(encoding, errors="replace")
        rows = Parser_ParseHtmlTable(text)
        matches = [row for row in rows if row and row[0].strip() == listing_date]
        print(
            " ",
            encoding,
            "replacement=",
            text.count("\ufffd"),
            "rows=",
            len(rows),
            "matches=",
            ascii(matches),
        )
