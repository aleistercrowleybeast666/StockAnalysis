from __future__ import annotations

import re
import html
from pathlib import Path


root = Path(__file__).resolve().parent
for path in sorted(root.glob("aastocks_*.html")):
    text = path.read_text(encoding="utf-8", errors="replace")
    print(f"## {path.name}")
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)', text, re.I):
        print("SCRIPT", src)
    for index, script in enumerate(
        re.findall(r"<script[^>]*>(.*?)</script>", text, re.I | re.S), 1
    ):
        if re.search(
            r"historicalchart|moneyflow|blocktrade|SQ_Chart|MFData|GetMF|GetBT",
            script,
            re.I,
        ):
            cleaned = re.sub(r"\s+", " ", script).strip()
            print(f"INLINE_SCRIPT_{index}", cleaned)
    for match in re.finditer(
        r".{0,220}(?:moneyflow|blocktrade|wdata\.aastocks|ajax|\.ashx|\.asmx|Get[A-Z][A-Za-z]+).{0,300}",
        text,
        re.I | re.S,
    ):
        snippet = re.sub(r"\s+", " ", match.group(0)).strip()
        print("REF", snippet)
    for needle in [
        "historicalchart",
        "chartdata",
        "histData",
        "Net Inflow",
        "5 Days",
        "20 Days",
        "Data =",
    ]:
        start = 0
        while True:
            pos = text.lower().find(needle.lower(), start)
            if pos < 0:
                break
            snippet = re.sub(r"\s+", " ", text[max(0, pos - 500) : pos + 1500])
            print(f"AROUND_{needle}_{pos}", snippet)
            start = pos + len(needle)
    visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
    visible = html.unescape(re.sub(r"<[^>]+>", "\n", visible))
    visible_lines = [re.sub(r"\s+", " ", line).strip() for line in visible.splitlines()]
    for line in visible_lines:
        if line and re.search(
            r"inflow|outflow|net|turnover|volume|date|average|major|retail|00700",
            line,
            re.I,
        ):
            print("VISIBLE", line)
