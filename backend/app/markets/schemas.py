"""Market information API contracts.

Provenance is explicit everywhere: `provider`, `source`, `source_url`, `is_demo`,
`retrieved_at`, plus `is_estimate` on rows that came from a model rather than a
mandi. Estimates are never mixed into observed series, and no response is allowed
to present synthetic demo prices as real quotes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MarketCropOut(BaseModel):
    crop_code: str
    name: str
    unit: str = "INR_per_quintal"
    has_demo_prices: bool = Field(
        default=False, description="True when the active provider is the demo provider."
    )


class MarketOut(BaseModel):
    code: str
    name: str
    state: str | None = None
    district: str | None = None
    market_type: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    is_demo: bool = False


class PriceRow(BaseModel):
    market_code: str
    market_name: str
    state: str | None = None
    district: str | None = None
    crop_code: str
    crop_name: str
    price_date: date
    min_price: float | None = None
    max_price: float | None = None
    modal_price: float | None = Field(
        default=None, description="The most frequently traded price of the day, where reported."
    )
    unit: str = "INR_per_quintal"
    arrivals_tonnes: float | None = None
    source: str
    source_url: str | None = None
    is_estimate: bool = Field(
        default=False,
        description="True when a model produced this row. Estimates are never mixed into observed series.",
    )
    is_demo: bool = Field(
        default=False, description="True when the row came from the demo provider."
    )
    retrieved_at: datetime


class PriceListOut(BaseModel):
    items: list[PriceRow]
    provider: str
    source: str
    source_url: str | None = None
    is_demo: bool = False
    retrieved_at: datetime
    count: int
    cached: bool = False
    notices: list[str] = []
    disclaimer: str = "Mandi prices vary by lot, grade and time of day. Treat these figures as a reference, not an offer."


class TrendPoint(BaseModel):
    price_date: date
    modal_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    is_estimate: bool = False


class TrendOut(BaseModel):
    crop_code: str
    market_code: str | None = None
    unit: str
    points: list[TrendPoint]
    provider: str
    source: str
    is_demo: bool = False
    retrieved_at: datetime
    direction: Literal["rising", "falling", "stable", "unknown"]
    change_percent: float | None = None
    notices: list[str] = []
    method_note: str = (
        "Direction compares the mean of the first half of the window with the second half; a move smaller than "
        "3% is reported as stable, and fewer than 4 data points is reported as unknown."
    )


class EstimateRequest(BaseModel):
    crop_code: str = Field(min_length=2, max_length=48)
    market_code: str | None = Field(default=None, max_length=64)
    horizon_days: int = Field(
        default=1,
        ge=1,
        le=14,
        description="Forward horizon. Only supported where a price model is installed; otherwise "
        "the API reports the model as unavailable rather than guessing.",
    )


class EstimateOut(BaseModel):
    crop_code: str
    market_code: str | None = None
    horizon_days: int
    available: bool = Field(
        description="False when no price model artefact is installed for this crop."
    )
    estimate: dict | None = None
    reason: str | None = None
    data_class: Literal["model_output"] = "model_output"
    disclaimer: str = "AI-assisted estimate — not a market guarantee. Do not use it as the sole basis for a sale decision."


class ArrivalsOut(BaseModel):
    crop_code: str
    market_code: str | None = None
    items: list[dict] = []
    provider: str
    source: str
    is_demo: bool = False
    retrieved_at: datetime
    count: int
    notices: list[str] = []
    note: str = (
        "Arrival volumes are only reported where the data source provides them; a blank arrival figure means "
        "'not reported', never zero."
    )


class MarketProviderHealth(BaseModel):
    provider: str
    available: bool
    is_demo: bool
    detail: str | None = None
    requires_api_key: bool | None = None
    configured: bool | None = None
    note: str | None = None
