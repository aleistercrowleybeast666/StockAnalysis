from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stock_analysis.sources.base import HttpJsonClient, SourceSchemaError


@dataclass(slots=True, frozen=True)
class FxRate:
    rate: float
    rate_date: date


class FrankfurterFxSource:
    source_name = "Frankfurter"
    BASE_URL = "https://api.frankfurter.app"

    def __init__(self, client: HttpJsonClient) -> None:
        self._client = client
        self._run_rates: dict[tuple[str, str, date], FxRate] = {}

    def Rate_Fetch(self, source_currency: str, target_currency: str, on_date: date) -> FxRate:
        if source_currency == target_currency:
            return FxRate(1.0, on_date)
        run_key = (source_currency, target_currency, on_date)
        if run_key in self._run_rates:
            return self._run_rates[run_key]
        data = self._client.RequestJson(
            f"{self.BASE_URL}/{on_date.isoformat()}",
            params={"from": source_currency, "to": target_currency},
            request_id=f"fx-{on_date}-{source_currency}-{target_currency}",
            endpoint_key="fx-historical",
        )
        try:
            rate = float(data["rates"][target_currency])
            rate_date = date.fromisoformat(data["date"])
        except (KeyError, TypeError, ValueError) as error:
            raise SourceSchemaError("汇率响应缺少目标币种") from error
        if rate <= 0:
            raise SourceSchemaError("汇率必须大于零")
        result = FxRate(rate, rate_date)
        self._run_rates[run_key] = result
        return result

    def close(self) -> None:
        self._client.close()
