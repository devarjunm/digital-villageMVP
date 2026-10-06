"""Market-data providers.

Two data classes are separated by construction:

  * `MarketProvider` returns *actual* observations retrieved from a named source
    (data.gov.in Agmarknet feed, or a state APMC portal via the generic
    provider). Every row carries `source`, `source_url` and `retrieved_at`.
  * model-based price estimates are produced by ai/price_prediction and stored
    with `is_estimate=True`, never through this interface.

`MARKET_PROVIDER=mock` (default) generates *deterministic synthetic* prices that
are labelled `is_demo=True` and `source="demo-provider"`. They are not real
mandi prices and the API says so in the response.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar, Protocol

import httpx

from app.core.config import settings
from app.core.errors import ProviderUnavailableError

# Reference ranges used ONLY by the demo provider to generate plausible-looking
# synthetic series. Values are order-of-magnitude anchors, not market quotes.
DEMO_PRICE_ANCHORS: dict[str, float] = {
    "onion": 1800.0,
    "tomato": 1500.0,
    "potato": 1200.0,
    "wheat": 2400.0,
    "rice_paddy": 2100.0,
    "maize": 2000.0,
    "soybean": 4500.0,
    "cotton": 6800.0,
    "sugarcane": 300.0,
    "groundnut": 5800.0,
    "chilli": 12000.0,
    "turmeric": 9000.0,
    "grapes": 5500.0,
    "banana": 1600.0,
    "pomegranate": 7000.0,
    "mango": 4500.0,
    "bajra": 2300.0,
    "jowar": 2800.0,
    "gram": 5200.0,
    "mustard": 5400.0,
}
DEMO_DEFAULT_ANCHOR = 2200.0


@dataclass(slots=True)
class MarketInfo:
    code: str
    name: str
    state: str
    district: str | None
    market_type: str = "regulated_mandi"
    source_name: str | None = None
    source_url: str | None = None
    is_demo: bool = False


@dataclass(slots=True)
class PriceRecord:
    market_code: str
    market_name: str
    state: str
    district: str | None
    crop_code: str
    crop_name: str
    price_date: date
    min_price: float | None
    max_price: float | None
    modal_price: float | None
    unit: str
    arrivals_tonnes: float | None
    source: str
    source_url: str | None
    is_demo: bool
    retrieved_at: datetime


@dataclass(slots=True)
class ProviderResult:
    """Envelope returned by providers so the service can record provenance."""

    records: list[PriceRecord]
    provider: str
    is_demo: bool
    retrieved_at: datetime
    source_name: str
    source_url: str | None = None
    notices: list[str] = field(default_factory=list)


class MarketProvider(Protocol):
    name: str
    is_demo: bool

    def markets(
        self, *, state: str | None = None, district: str | None = None, query: str | None = None
    ) -> list[MarketInfo]: ...

    def prices(
        self,
        *,
        crop_code: str,
        state: str | None = None,
        district: str | None = None,
        market_code: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> ProviderResult: ...

    def health(self) -> dict[str, object]: ...


class MockMarketProvider:
    """Deterministic synthetic prices for development.

    The series is generated with a stable hash so the same crop/market/date always
    yields the same numbers (reproducible demos and tests). Seasonal shape and
    weekly volatility are simulated; nothing here reflects any real market.
    """

    name = "mock"
    is_demo = True
    source_label = "demo-provider (synthetic, not real mandi data)"

    DEMO_MARKETS: ClassVar[list[MarketInfo]] = [
        MarketInfo(
            code="demo_mkt_nashik",
            name="Nashik (demo)",
            state="Maharashtra",
            district="Nashik",
            is_demo=True,
        ),
        MarketInfo(
            code="demo_mkt_pune",
            name="Pune (demo)",
            state="Maharashtra",
            district="Pune",
            is_demo=True,
        ),
        MarketInfo(
            code="demo_mkt_latur",
            name="Latur (demo)",
            state="Maharashtra",
            district="Latur",
            is_demo=True,
        ),
        MarketInfo(
            code="demo_mkt_nagpur",
            name="Nagpur (demo)",
            state="Maharashtra",
            district="Nagpur",
            is_demo=True,
        ),
        MarketInfo(
            code="demo_mkt_indore",
            name="Indore (demo)",
            state="Madhya Pradesh",
            district="Indore",
            is_demo=True,
        ),
        MarketInfo(
            code="demo_mkt_jaipur",
            name="Jaipur (demo)",
            state="Rajasthan",
            district="Jaipur",
            is_demo=True,
        ),
    ]

    def markets(self, *, state=None, district=None, query=None) -> list[MarketInfo]:
        rows = self.DEMO_MARKETS
        if state:
            rows = [m for m in rows if m.state.lower() == state.lower()]
        if district:
            rows = [m for m in rows if (m.district or "").lower() == district.lower()]
        if query:
            needle = query.lower()
            rows = [
                m for m in rows if needle in m.name.lower() or needle in (m.district or "").lower()
            ]
        return list(rows)

    def _series_seed(self, crop_code: str, market_code: str, day: date) -> float:
        raw = f"{crop_code}:{market_code}:{day.isoformat()}"
        digest = hashlib.sha256(raw.encode()).digest()
        return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF

    def _price_for(self, crop_code: str, market_code: str, day: date) -> float:
        anchor = DEMO_PRICE_ANCHORS.get(crop_code, DEMO_DEFAULT_ANCHOR)
        seed = self._series_seed(crop_code, market_code, day)
        # seasonal component + weekly cycle + deterministic jitter, ±18% total
        doy = day.timetuple().tm_yday
        seasonal = math.sin(2 * math.pi * doy / 365.0) * 0.10
        weekly = math.sin(2 * math.pi * day.weekday() / 7.0) * 0.03
        jitter = (seed - 0.5) * 0.10
        return round(anchor * (1 + seasonal + weekly + jitter), 2)

    def prices(
        self,
        *,
        crop_code,
        state=None,
        district=None,
        market_code=None,
        from_date=None,
        to_date=None,
    ) -> ProviderResult:
        markets = self.markets(state=state, district=district)
        if market_code:
            markets = [m for m in markets if m.code == market_code]
            if not markets:
                markets = [
                    MarketInfo(
                        code=market_code,
                        name=f"{market_code} (demo)",
                        state=state or "Unknown",
                        district=district,
                        is_demo=True,
                    )
                ]
        end = to_date or date.today()
        start = from_date or end
        records: list[PriceRecord] = []
        for market in markets:
            day = start
            while day <= end:
                modal = self._price_for(crop_code, market.code, day)
                spread = modal * 0.12
                # Arrivals drop on Sundays, a real pattern in most regulated markets.
                arrivals = (
                    0.0
                    if day.weekday() == 6
                    else round(60 + self._series_seed(crop_code, market.code, day) * 240, 1)
                )
                records.append(
                    PriceRecord(
                        market_code=market.code,
                        market_name=market.name,
                        state=market.state,
                        district=market.district,
                        crop_code=crop_code,
                        crop_name=crop_code.replace("_", " ").title(),
                        price_date=day,
                        min_price=round(modal - spread, 2),
                        max_price=round(modal + spread, 2),
                        modal_price=modal,
                        unit="INR_per_quintal",
                        arrivals_tonnes=arrivals,
                        source=self.source_label,
                        source_url=None,
                        is_demo=True,
                        retrieved_at=datetime.now(UTC),
                    )
                )
                day += timedelta(days=1)
        return ProviderResult(
            records=records,
            provider=self.name,
            is_demo=True,
            retrieved_at=datetime.now(UTC),
            source_name=self.source_label,
            notices=[
                "DEMO DATA: prices are synthetic and must not be used for trading decisions.",
                "Configure MARKET_PROVIDER=data_gov_in (with MARKET_API_KEY) for real mandi prices.",
            ],
        )

    def health(self) -> dict[str, object]:
        return {"provider": self.name, "available": True, "is_demo": True}


class DataGovInProvider:
    """Real provider backed by the data.gov.in Agmarknet daily price resource.

    Requires MARKET_API_KEY (data.gov.in API key) and MARKET_RESOURCE_ID for the
    *Variety-wise Daily Market Prices Data of Commodity* resource. Field names in
    that dataset are `state`, `district`, `market`, `commodity`, `variety`,
    `arrival_date`, `min_price`, `max_price`, `modal_price`, with prices in
    INR/quintal.
    """

    name = "data_gov_in"
    is_demo = False
    SOURCE_NAME = "Agmarknet daily market prices via data.gov.in"

    def __init__(self) -> None:
        self.api_key = settings.market_api_key
        self.resource_id = settings.market_resource_id
        self.base_url = (settings.market_api_base_url or "https://api.data.gov.in").rstrip("/")

    def _require_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("MARKET_API_KEY", self.api_key),
                ("MARKET_RESOURCE_ID", self.resource_id),
            )
            if not value
        ]
        if missing:
            raise ProviderUnavailableError(
                "Live mandi prices are not configured on this deployment.",
                details={"provider": self.name, "missing": missing},
            )

    def markets(self, *, state=None, district=None, query=None) -> list[MarketInfo]:
        self._require_config()
        params = {
            "api-key": self.api_key,
            "format": "json",
            "limit": 100,
            "fields": "state,district,market",
        }
        if state:
            params["filters[state]"] = state
        if district:
            params["filters[district]"] = district
        try:
            response = httpx.get(
                f"{self.base_url}/resource/{self.resource_id}", params=params, timeout=15.0
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "The market data service could not be reached.",
                details={"provider": self.name},
            ) from exc
        seen: dict[str, MarketInfo] = {}
        for row in response.json().get("records", []):
            name = row.get("market") or "Unknown"
            code = name.strip().lower().replace(" ", "_")[:48]
            if (
                query
                and query.lower() not in name.lower()
                and query.lower() not in (row.get("district") or "").lower()
            ):
                continue
            seen.setdefault(
                code,
                MarketInfo(
                    code=code,
                    name=name,
                    state=row.get("state", ""),
                    district=row.get("district"),
                    source_name=self.SOURCE_NAME,
                    source_url=f"{self.base_url}/resource/{self.resource_id}",
                ),
            )
        return list(seen.values())

    def prices(
        self,
        *,
        crop_code,
        state=None,
        district=None,
        market_code=None,
        from_date=None,
        to_date=None,
    ) -> ProviderResult:
        self._require_config()
        params: dict[str, object] = {
            "api-key": self.api_key,
            "format": "json",
            "limit": 500,
            "fields": "state,district,market,commodity,variety,arrival_date,min_price,max_price,modal_price",
        }
        if state:
            params["filters[state]"] = state
        if district:
            params["filters[district]"] = district
        if crop_code:
            params["filters[commodity]"] = crop_code.replace("_", " ").title()
        try:
            response = httpx.get(
                f"{self.base_url}/resource/{self.resource_id}", params=params, timeout=20.0
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "The market data service could not be reached.",
                details={"provider": self.name},
            ) from exc

        retrieved_at = datetime.now(UTC)
        records: list[PriceRecord] = []
        for row in response.json().get("records", []):
            try:
                price_date = datetime.strptime(str(row.get("arrival_date")), "%d/%m/%Y").date()
            except (ValueError, TypeError):
                continue
            if from_date and price_date < from_date:
                continue
            if to_date and price_date > to_date:
                continue
            market_name = row.get("market") or "Unknown"
            records.append(
                PriceRecord(
                    market_code=(market_name.strip().lower().replace(" ", "_"))[:48],
                    market_name=market_name,
                    state=row.get("state", ""),
                    district=row.get("district"),
                    crop_code=crop_code,
                    crop_name=str(row.get("commodity", crop_code)),
                    price_date=price_date,
                    min_price=_to_float(row.get("min_price")),
                    max_price=_to_float(row.get("max_price")),
                    modal_price=_to_float(row.get("modal_price")),
                    unit="INR_per_quintal",
                    arrivals_tonnes=None,
                    source=self.SOURCE_NAME,
                    source_url=f"{self.base_url}/resource/{self.resource_id}",
                    is_demo=False,
                    retrieved_at=retrieved_at,
                )
            )
        return ProviderResult(
            records=records,
            provider=self.name,
            is_demo=False,
            retrieved_at=retrieved_at,
            source_name=self.SOURCE_NAME,
            source_url=f"{self.base_url}/resource/{self.resource_id}",
        )

    def health(self) -> dict[str, object]:
        configured = bool(self.api_key and self.resource_id)
        return {
            "provider": self.name,
            "available": configured,
            "is_demo": False,
            "detail": None if configured else "MARKET_API_KEY / MARKET_RESOURCE_ID not set",
        }


def _to_float(value: object) -> float | None:
    if value in (None, "", "NA"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def get_market_provider() -> MarketProvider:
    if settings.market_provider in ("data_gov_in", "agmarknet"):
        return DataGovInProvider()
    return MockMarketProvider()
