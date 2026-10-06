"""Market / mandi endpoints.

Reads are cached for 15 minutes (mandi prices do not change minute to minute) and
always carry the provider, source link, retrieval time and — for the demo
provider — an unmissable DEMO notice.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.auth.dependencies import CurrentUser, DbSession
from app.core.ratelimit import enforce_rate_limit
from app.markets.schemas import (
    ArrivalsOut,
    EstimateOut,
    EstimateRequest,
    MarketCropOut,
    MarketOut,
    MarketProviderHealth,
    PriceListOut,
    TrendOut,
)
from app.markets.service import MarketService

router = APIRouter()


@router.get("/crops", response_model=list[MarketCropOut], summary="Crops tracked for market prices")
def crops(db: DbSession, request: Request) -> list[MarketCropOut]:
    enforce_rate_limit(request, "read")
    return MarketService(db).crops()


@router.get(
    "/markets", response_model=list[MarketOut], summary="Markets (filter by state/district/name)"
)
def markets(
    db: DbSession,
    request: Request,
    state: Annotated[str | None, Query(max_length=120)] = None,
    district: Annotated[str | None, Query(max_length=120)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
) -> list[MarketOut]:
    enforce_rate_limit(request, "read")
    return MarketService(db).markets(state=state, district=district, query=q)


@router.get("/prices", response_model=PriceListOut, summary="Prices for a crop (max 90-day window)")
def prices(
    db: DbSession,
    request: Request,
    crop: Annotated[str, Query(min_length=2, max_length=48)],
    state: Annotated[str | None, Query(max_length=120)] = None,
    district: Annotated[str | None, Query(max_length=120)] = None,
    market: Annotated[str | None, Query(max_length=64)] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> PriceListOut:
    enforce_rate_limit(request, "read")
    return MarketService(db).prices(
        crop_code=crop,
        state=state,
        district=district,
        market_code=market,
        from_date=from_date,
        to_date=to_date,
    )


@router.get(
    "/prices/trend",
    response_model=TrendOut,
    summary="Price trend (documented half-window comparison)",
)
def trend(
    db: DbSession,
    request: Request,
    crop: Annotated[str, Query(min_length=2, max_length=48)],
    market: Annotated[str | None, Query(max_length=64)] = None,
    state: Annotated[str | None, Query(max_length=120)] = None,
    days: Annotated[int, Query(ge=7, le=365)] = 90,
) -> TrendOut:
    enforce_rate_limit(request, "read")
    return MarketService(db).trend(crop_code=crop, market_code=market, state=state, days=days)


@router.get(
    "/arrivals", response_model=ArrivalsOut, summary="Arrival volumes where the source reports them"
)
def arrivals(
    db: DbSession,
    request: Request,
    crop: Annotated[str, Query(min_length=2, max_length=48)],
    market: Annotated[str | None, Query(max_length=64)] = None,
    state: Annotated[str | None, Query(max_length=120)] = None,
) -> ArrivalsOut:
    enforce_rate_limit(request, "read")
    prices_out = MarketService(db).prices(crop_code=crop, market_code=market, state=state)
    items = [
        {
            "market_code": row.market_code,
            "market_name": row.market_name,
            "price_date": row.price_date.isoformat(),
            "arrivals_tonnes": row.arrivals_tonnes,
            "reported": row.arrivals_tonnes is not None,
            "source": row.source,
            "is_demo": row.is_demo,
        }
        for row in prices_out.items
    ]
    return ArrivalsOut(
        crop_code=crop,
        market_code=market,
        items=items,
        provider=prices_out.provider,
        source=prices_out.source,
        is_demo=prices_out.is_demo,
        retrieved_at=prices_out.retrieved_at,
        count=len(items),
        notices=prices_out.notices,
    )


@router.post(
    "/prices/estimate",
    response_model=EstimateOut,
    summary="Forward price estimate (only when a price model is installed)",
)
def estimate(
    payload: EstimateRequest, db: DbSession, user: CurrentUser, request: Request
) -> EstimateOut:
    """Never fabricates a number: if no price model artefact is installed the
    response says so (`available=false`) with the reason."""
    enforce_rate_limit(request, "ai")
    from app.ai.registry import available_versions

    versions = available_versions("price-prediction")
    if not versions:
        service = MarketService(db)
        history, dates, is_demo = service.price_history_for_model(
            crop_code=payload.crop_code, market_code=payload.market_code, days=365
        )
        return EstimateOut(
            crop_code=payload.crop_code,
            market_code=payload.market_code,
            horizon_days=payload.horizon_days,
            available=False,
            reason=(
                "No price-forecast model is installed. Install a trained model artefact to enable estimates; "
                "the observed history is available at /markets/prices/trend instead."
            ),
            estimate=None,
        )
    from ai.price_prediction.service import PriceForecastService  # type: ignore[import-not-found]

    return PriceForecastService(db=db).forecast(
        crop_code=payload.crop_code,
        market_code=payload.market_code,
        horizon_days=payload.horizon_days,
    )


@router.get("/provider", response_model=MarketProviderHealth, summary="Market data provider status")
def provider(db: DbSession) -> MarketProviderHealth:
    return MarketProviderHealth(**MarketService(db).health())
