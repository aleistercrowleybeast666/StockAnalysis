from __future__ import annotations

import io
import json
from typing import Any

from openpyxl import Workbook

from stock_analysis.sources.exchanges import OfficialAShareListSource


class FakeOfficialListClient:
    def RequestJson(
        self, _url: str, *, params: dict[str, Any], request_id: str, **_kwargs
    ) -> dict[str, Any]:
        stock_type = str(params["STOCK_TYPE"])
        code = "600000" if stock_type == "1" else "688001"
        name = "浦发银行" if stock_type == "1" else "科创样例"
        return {
            "result": [
                {
                    "A_STOCK_CODE": code,
                    "SEC_NAME_CN": name,
                    "LIST_DATE": "19991110",
                    "CSRC_CODE_DESC": "金融业" if stock_type == "1" else "制造业",
                }
            ],
            "request_id": request_id,
        }

    def RequestBytes(
        self,
        url: str,
        *,
        request_id: str,
        data: dict[str, Any] | None = None,
        **_kwargs,
    ) -> bytes:
        if "szse.cn" in url:
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["板块", "A股代码", "A股简称", "A股上市日期", "所属行业"])
            sheet.append(["主板", "000001", "平安银行", "1991-04-03", "J 金融业"])
            output = io.BytesIO()
            workbook.save(output)
            return output.getvalue()
        if "code_mapping" in url:
            return """
            <table>
              <tr><th>序号</th><th>证券简称</th><th>上市日期</th><th>旧代码</th><th>新代码</th></tr>
              <tr><td>1</td><td>北交样例1</td><td>2024/1/1</td><td>832001</td><td>920001</td></tr>
              <tr><td>2</td><td>北交样例2</td><td>2024/1/2</td><td>832002</td><td>920002</td></tr>
            </table>
            """.encode()
        form = data or {}
        page = int(form["page"])
        payload = {
            "content": [
                {
                    "xxzqdm": f"92000{page + 1}",
                    "xxzqjc": f"北交样例{page + 1}",
                    "fxssrq": "20240102",
                    "xxhyzl": "制造业",
                }
            ],
            "totalPages": 2,
            "request_id": request_id,
        }
        return f"stockAnalysisCallback({json.dumps([payload], ensure_ascii=False)})".encode()

    def close(self) -> None:
        return None


def test_official_a_share_list_combines_three_exchanges() -> None:
    source = OfficialAShareListSource(FakeOfficialListClient())  # type: ignore[arg-type]
    securities = source.SecurityList_Fetch()
    assert [security.code for security in securities] == [
        "000001",
        "600000",
        "688001",
        "920001",
        "920002",
    ]
    assert {security.exchange for security in securities} == {"SSE", "SZSE", "BSE"}
    assert securities[0].is_financial is True
    assert securities[1].listing_date is not None
    assert securities[-2].legacy_codes == ("832001",)
    assert securities[-1].legacy_codes == ("832002",)
