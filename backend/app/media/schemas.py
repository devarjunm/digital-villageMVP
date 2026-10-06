"""Media API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MediaAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purpose: str
    storage_backend: str
    storage_key: str
    public_url: str | None
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    checksum_sha256: str
    created_at: datetime
    validation_notes: list[str] = []


class UploadResponse(BaseModel):
    media: MediaAssetOut
    validation: dict[str, object]
    message: str
