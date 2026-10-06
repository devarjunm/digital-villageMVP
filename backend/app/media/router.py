"""Media upload endpoints."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile, status

from app.auth.dependencies import CurrentUser, DbSession, require_capability
from app.core.errors import PayloadTooLargeError, ValidationError
from app.core.ratelimit import enforce_rate_limit
from app.media.schemas import MediaAssetOut, UploadResponse
from app.media.service import ALLOWED_PURPOSES, store_image

router = APIRouter()


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image (validated: type, size, dimensions)",
)
async def upload_image(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(..., description="JPEG, PNG or WebP image"),
    purpose: str = Form("post_image", description=f"One of: {', '.join(sorted(ALLOWED_PURPOSES))}"),
) -> UploadResponse:
    enforce_rate_limit(request, "upload")
    require_capability("post")
    chunk = await file.read()
    if len(chunk) > 0 and len(chunk) > 16 * 1024 * 1024:
        raise PayloadTooLargeError("File is too large to process.")
    if not chunk:
        raise ValidationError("No file was received.")
    asset, validation = store_image(
        db,
        data=chunk,
        declared_mime=file.content_type,
        filename=file.filename,
        owner_id=user.id,
        purpose=purpose,
    )
    db.commit()
    db.refresh(asset)
    return UploadResponse(
        media=MediaAssetOut.model_validate(asset),
        validation=validation,
        message="Image uploaded and validated.",
    )


@router.get("/{media_id}", response_model=MediaAssetOut, summary="Media metadata (no binary)")
def get_media(media_id: str, db: DbSession) -> MediaAssetOut:
    import uuid as _uuid

    from app.core.errors import NotFoundError
    from app.media.models import MediaAsset

    try:
        parsed = _uuid.UUID(media_id)
    except ValueError as exc:
        raise ValidationError("That media id is not valid.") from exc
    asset = db.get(MediaAsset, parsed)
    if asset is None:
        raise NotFoundError("That image was not found.")
    return MediaAssetOut.model_validate(asset)
