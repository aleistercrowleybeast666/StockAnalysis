from __future__ import annotations

from pathlib import Path

import httpx


root = Path(__file__).resolve().parent
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/140 Safari/537.36"
    ),
    "Referer": "https://www.aastocks.com/en/stocks/quote/quick-quote.aspx?symbol=00700",
}
with httpx.Client(headers=headers, follow_redirects=True, timeout=20) as client:
    client.cookies.set("MasterSymbol", "00700", domain="www.aastocks.com", path="/")
    client.cookies.set(
        "LatestRTQuotedStocks", "00700", domain="www.aastocks.com", path="/"
    )
    client.cookies.set("AALTP", "1", domain="www.aastocks.com", path="/")
    for name, url in [
        (
            "quick",
            "https://www.aastocks.com/en/stocks/quote/quick-quote.aspx?symbol=00700",
        ),
        (
            "flow_recent",
            "https://www.aastocks.com/en/stocks/analysis/moneyflow.aspx?symbol=00700",
        ),
        (
            "flow_history",
            "https://www.aastocks.com/en/stocks/analysis/moneyflow.aspx?symbol=00700&type=h",
        ),
        (
            "block",
            "https://www.aastocks.com/en/stocks/analysis/blocktrade.aspx?symbol=00700",
        ),
    ]:
        response = client.get(url)
        print(
            name,
            response.status_code,
            len(response.content),
            str(response.url),
            response.request.headers.get("cookie", ""),
        )
        (root / f"aastocks_session_{name}.html").write_bytes(response.content)
