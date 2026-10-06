"""Market service: provider orchestration, storage, trends and cache.

Guarantees enforced here:
  * rows persisted from providers keep `source` + `retrieved_at`;
  * demo-provider rows are stored with `is_demo=True` and are never returned
    without a notice;
  * model estimates are stored/returned with `is_estimate=True` and a model
    version, and are never merged into observed price rows.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import get_cache
from app.core.config import settings
from app.core.errors import ProviderUnavailableError, ValidationError
from app.core.logging import get_logger
from app.core.observability import observe_provider_call
from app.markets.models import Market, MarketPrice
from app.markets.schemas import (
    MarketCropOut,
    MarketOut,
    PriceListOut,
    PriceRow,
    TrendOut,
    TrendPoint,
)
from app.providers.market import PriceRecord, get_market_provider

logger = get_logger(__name__)

CROP_DISPLAY = {
    "onion": "Onion",
    "tomato": "Tomato",
    "potato": "Potato",
    "wheat": "Wheat",
    "rice_paddy": "Paddy (rice)",
    "maize": "Maize",
    "soybean": "Soybean",
    "cotton": "Cotton",
    "sugarcane": "Sugarcane",
    "groundnut": "Groundnut",
    "chilli": "Chilli (dry)",
    "turmeric": "Turmeric",
    "grapes": "Grapes",
    "banana": "Banana",
    "pomegranate": "Pomegranate",
    "mango": "Mango",
    "bajra": "Pearl millet (bajra)",
    "jowar": "Sorghum (jowar)",
    "gram": "Chickpea (gram)",
    "mustard": "Mustard",
}
DEMO_NOTICE = (
    "DEMO DATA: these prices are synthetic and produced by the local demo provider. "
    "They are not real mandi quotes and must not be used for trading decisions."
)


class MarketService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.provider = get_market_provider()
        self.cache = get_cache()

    # --------------------------------------------------------------- catalogs
    def crops(self) -> list[MarketCropOut]:
        cache_key = f"dv:market:crops:{self.provider.name}"
        cached = self.cache.get_json(cache_key)
        if cached:
            return [MarketCropOut(**row) for row in cached]
        rows = [
            MarketCropOut(
                crop_code=code,
                name=name,
                unit="INR_per_quintal",
                has_demo_prices=self.provider.is_demo,
            )
            for code, name in sorted(CROP_DISPLAY.items())
        ]
        self.cache.set_json(cache_key, [r.model_dump() for r in rows], ttl=3600)
        return rows

    def markets(
        self, *, state: str | None = None, district: str | None = None, query: str | None = None
    ) -> list[MarketOut]:
        cache_key = f"dv:market:markets:{self.provider.name}:{state}:{district}:{query}"
        cached = self.cache.get_json(cache_key)
        if cached:
            return [MarketOut(**row) for row in cached]
        try:
            with observe_provider_call(self.provider.name, "markets"):
                infos = self.provider.markets(state=state, district=district, query=query)
        except ProviderUnavailableError:
            # Fall back to markets already stored in the database.
            stmt = select(Market).where(Market.deleted_at.is_(None))
            if state:
                stmt = stmt.where(Market.state == state)
            if district:
                stmt = stmt.where(Market.district == district)
            if query:
                stmt = stmt.where(Market.name.ilike(f"%{query}%"))
            rows = self.db.execute(stmt.limit(200)).scalars().all()
            return [
                MarketOut(
                    code=row.code,
                    name=row.name,
                    state=row.state,
                    district=row.district,
                    market_type=row.market_type,
                    source_name=row.source_name,
                    source_url=row.source_url,
                    is_demo=row.is_demo,
                )
                for row in rows
            ]
        out = [
            MarketOut(
                code=info.code,
                name=info.name,
                state=info.state,
                district=info.district,
                market_type=info.market_type,
                source_name=info.source_name,
                source_url=info.source_url,
                is_demo=info.is_demo,
            )
            for info in infos
        ]
        self.cache.set_json(
            cache_key,
            [r.model_dump(mode="json") for r in out],
            ttl=settings.cache_ttl_market_seconds,
        )
        return out

    # ---------------------------------------------------------------- prices
    def prices(
        self,
        *,
        crop_code: str,
        state: str | None = None,
        district: str | None = None,
        market_code: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        persist: bool = True,
    ) -> PriceListOut:
        if crop_code not in CROP_DISPLAY:
            raise ValidationError(
                "Unknown crop for market prices.",
                details={"crop_code": crop_code, "supported": sorted(CROP_DISPLAY)[:20]},
            )
        end = to_date or date.today()
        start = from_date or (end - timedelta(days=6))
        if start > end:
            raise ValidationError("The start date must be before the end date.")
        if (end - start).days > 90:
            raise ValidationError("Price queries are limited to a 90-day window.")

        cache_key = f"dv:market:prices:{self.provider.name}:{crop_code}:{state}:{district}:{market_code}:{start}:{end}"
        cached = self.cache.get_json(cache_key)
        if cached:
            payload = PriceListOut(**cached)
            payload.cached = True
            return payload

        try:
            with observe_provider_call(self.provider.name, "prices"):
                result = self.provider.prices(
                    crop_code=crop_code,
                    state=state,
                    district=district,
                    market_code=market_code,
                    from_date=start,
                    to_date=end,
                )
        except ProviderUnavailableError:
            stored = self._stored_prices(
                crop_code=crop_code,
                state=state,
                district=district,
                market_code=market_code,
                start=start,
                end=end,
            )
            if not stored:
                raise
            return PriceListOut(
                items=stored,
                provider="stored",
                source="Last stored prices (provider unavailable)",
                is_demo=any(row.is_demo for row in stored),
                retrieved_at=datetime.now(UTC),
                count=len(stored),
                notices=[
                    "The live market data provider is unavailable; showing the most recent stored prices.",
                    *([DEMO_NOTICE] if any(row.is_demo for row in stored) else []),
                ],
            )

        if persist:
            self._persist(result.records)
        rows = [
            PriceRow(
                market_code=rec.market_code,
                market_name=rec.market_name,
                state=rec.state,
                district=rec.district,
                crop_code=rec.crop_code,
                crop_name=rec.crop_name,
                price_date=rec.price_date,
                min_price=rec.min_price,
                max_price=rec.max_price,
                modal_price=rec.modal_price,
                unit=rec.unit,
                arrivals_tonnes=rec.arrivals_tonnes,
                source=rec.source,
                source_url=rec.source_url,
                is_estimate=False,
                is_demo=rec.is_demo,
                retrieved_at=rec.retrieved_at,
            )
            for rec in result.records
        ]
        rows.sort(key=lambda r: (r.price_date, r.market_name), reverse=True)
        notices = list(result.notices)
        if result.is_demo and DEMO_NOTICE not in notices:
            notices.append(DEMO_NOTICE)
        payload = PriceListOut(
            items=rows,
            provider=result.provider,
            source=result.source_name,
            source_url=result.source_url,
            is_demo=result.is_demo,
            retrieved_at=result.retrieved_at,
            count=len(rows),
            notices=notices,
        )
        self.cache.set_json(
            cache_key, payload.model_dump(mode="json"), ttl=settings.cache_ttl_market_seconds
        )
        return payload

    def trend(
        self,
        *,
        crop_code: str,
        market_code: str | None = None,
        days: int = 90,
        state: str | None = None,
    ) -> TrendOut:
        end = date.today()
        start = end - timedelta(days=max(7, min(days, 365)))
        prices = self.prices(
            crop_code=crop_code, market_code=market_code, state=state, from_date=start, to_date=end
        )
        # aggregate by date (mean of modal prices across markets when no market is fixed)
        buckets: dict[date, list[PriceRow]] = {}
        for row in prices.items:
            buckets.setdefault(row.price_date, []).append(row)
        points: list[TrendPoint] = []
        for day in sorted(buckets):
            rows = buckets[day]
            modals = [r.modal_price for r in rows if r.modal_price is not None]
            mins = [r.min_price for r in rows if r.min_price is not None]
            maxs = [r.max_price for r in rows if r.max_price is not None]
            points.append(
                TrendPoint(
                    price_date=day,
                    modal_price=round(sum(modals) / len(modals), 2) if modals else None,
                    min_price=min(mins) if mins else None,
                    max_price=max(maxs) if maxs else None,
                    is_estimate=any(r.is_estimate for r in rows),
                )
            )
        direction, change = self._direction(points)
        return TrendOut(
            crop_code=crop_code,
            market_code=market_code,
            unit=prices.items[0].unit if prices.items else "INR_per_quintal",
            points=points,
            provider=prices.provider,
            source=prices.source,
            is_demo=prices.is_demo,
            retrieved_at=prices.retrieved_at,
            direction=direction,
            change_percent=change,
            notices=prices.notices,
        )

    @staticmethod
    def _direction(points: list[TrendPoint]) -> tuple[str, float | None]:
        values = [p.modal_price for p in points if p.modal_price is not None]
        if len(values) < 4:
            return "unknown", None
        first_half = sum(values[: len(values) // 2]) / (len(values) // 2)
        second_half = sum(values[len(values) // 2 :]) / (len(values) - len(values) // 2)
        if first_half == 0:
            return "unknown", None
        change = (second_half - first_half) / first_half * 100
        if change > 3:
            return "rising", round(change, 2)
        if change < -3:
            return "falling", round(change, 2)
        return "stable", round(change, 2)

    def save_estimate(
        self,
        *,
        crop_code: str,
        market_code: str | None,
        state: str | None,
        price_date: date,
        modal_price: float,
        lower: float | None,
        upper: float | None,
        model_name: str,
        model_version: str,
    ) -> None:
        """Store a model estimate in its own row (`is_estimate=True`), never mixed
        with observed prices."""
        market = self.db.execute(
            select(Market).where(Market.code == (market_code or f"est_{crop_code}"))
        ).scalar_one_or_none()
        if market is None:
            market = Market(
                code=market_code or f"model_estimate_{crop_code}",
                name=f"Model estimate ({crop_code})",
                state=state or "All India",
                district=None,
                market_type="model_estimate",
                is_demo=True,
            )
            self.db.add(market)
            self.db.flush()
        row = MarketPrice(
            market_id=market.id,
            crop_code=crop_code,
            crop_name=CROP_DISPLAY.get(crop_code, crop_code),
            price_date=price_date,
            min_price=lower,
            max_price=upper,
            modal_price=modal_price,
            unit="INR_per_quintal",
            source=f"{model_name}:{model_version}",
            is_estimate=True,
            model_name=model_name,
            model_version=model_version,
            retrieved_at=datetime.now(UTC),
            is_demo=False,
        )
        self.db.add(row)
        self.db.commit()

    # -------------------------------------------------------------- internals
    def _persist(self, records: list[PriceRecord]) -> None:
        if not records:
            return
        try:
            market_cache: dict[str, Market] = {}
            for rec in records:
                market = market_cache.get(rec.market_code)
                if market is None:
                    market = self.db.execute(
                        select(Market).where(Market.code == rec.market_code)
                    ).scalar_one_or_none()
                    if market is None:
                        market = Market(
                            code=rec.market_code,
                            name=rec.market_name,
                            state=rec.state,
                            district=rec.district,
                            market_type="regulated_mandi",
                            source_name=rec.source,
                            source_url=rec.source_url,
                            is_demo=rec.is_demo,
                        )
                        self.db.add(market)
                        self.db.flush()
                    market_cache[rec.market_code] = market
                existing = self.db.execute(
                    select(MarketPrice).where(
                        MarketPrice.market_id == market.id,
                        MarketPrice.crop_code == rec.crop_code,
                        MarketPrice.price_date == rec.price_date,
                        MarketPrice.source == rec.source,
                        MarketPrice.is_estimate.is_(False),
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.min_price = rec.min_price
                    existing.max_price = rec.max_price
                    existing.modal_price = rec.modal_price
                    existing.arrivals_tonnes = rec.arrivals_tonnes
                    existing.retrieved_at = rec.retrieved_at
                    continue
                self.db.add(
                    MarketPrice(
                        market_id=market.id,
                        crop_code=rec.crop_code,
                        crop_name=rec.crop_name,
                        price_date=rec.price_date,
                        min_price=rec.min_price,
                        max_price=rec.max_price,
                        modal_price=rec.modal_price,
                        unit=rec.unit,
                        arrivals_tonnes=rec.arrivals_tonnes,
                        source=rec.source,
                        source_url=rec.source_url,
                        is_estimate=False,
                        retrieved_at=rec.retrieved_at,
                        is_demo=rec.is_demo,
                    )
                )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning(
                "market_persist_failed", extra={"extra_fields": {"error": str(exc)[:200]}}
            )

    def _stored_prices(
        self,
        *,
        crop_code: str,
        state: str | None,
        district: str | None,
        market_code: str | None,
        start: date,
        end: date,
    ) -> list[PriceRow]:
        stmt = (
            select(MarketPrice, Market)
            .join(Market, Market.id == MarketPrice.market_id)
            .where(
                MarketPrice.crop_code == crop_code,
                MarketPrice.price_date >= start,
                MarketPrice.price_date <= end,
                MarketPrice.is_estimate.is_(False),
            )
        )
        if state:
            stmt = stmt.where(Market.state == state)
        if district:
            stmt = stmt.where(Market.district == district)
        if market_code:
            stmt = stmt.where(Market.code == market_code)
        rows = self.db.execute(stmt.order_by(MarketPrice.price_date.desc()).limit(500)).all()
        return [
            PriceRow(
                market_code=market.code,
                market_name=market.name,
                state=market.state,
                district=market.district,
                crop_code=price.crop_code,
                crop_name=price.crop_name or CROP_DISPLAY.get(price.crop_code, price.crop_code),
                price_date=price.price_date,
                min_price=float(price.min_price) if price.min_price is not None else None,
                max_price=float(price.max_price) if price.max_price is not None else None,
                modal_price=float(price.modal_price) if price.modal_price is not None else None,
                unit=price.unit,
                arrivals_tonnes=float(price.arrivals_tonnes)
                if price.arrivals_tonnes is not None
                else None,
                source=price.source,
                source_url=price.source_url,
                is_estimate=price.is_estimate,
                model_name=price.model_name,
                model_version=price.model_version,
                is_demo=price.is_demo,
                retrieved_at=price.retrieved_at,
            )
            for price, market in rows
        ]

    def price_history_for_model(
        self, *, crop_code: str, market_code: str | None, days: int
    ) -> tuple[list[float], list[date], bool]:
        """Training/inference input: observed modal prices only (never estimates)."""
        end = date.today()
        start = end - timedelta(days=days)
        rows = self._stored_prices(
            crop_code=crop_code,
            state=None,
            district=None,
            market_code=market_code,
            start=start,
            end=end,
        )
        aggregated: dict[date, list[float]] = {}
        for row in rows:
            if row.modal_price is None:
                continue
            aggregated.setdefault(row.price_date, []).append(row.modal_price)
        dates = sorted(aggregated)
        values = [round(sum(aggregated[d]) / len(aggregated[d]), 2) for d in dates]
        is_demo = any(row.is_demo for row in rows) if rows else False
        return values, dates, is_demo

    def health(self) -> dict:
        return self.provider.health()
