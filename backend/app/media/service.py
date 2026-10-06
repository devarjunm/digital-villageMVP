"""Upload validation and persistence.

Uploads are treated as hostile input:
  * size is capped before the body is fully read (MAX_UPLOAD_MB);
  * the real format is sniffed with Pillow, never trusted from the filename;
  * declared extension and MIME must agree with the sniffed format;
  * pixel dimensions are bounded to stop decompression bombs;
  * EXIF metadata is retained only in the stored file, and GPS coordinates are
    reported to the caller (so the app can ask before publishing a location).
Binary content goes to the object store; PostgreSQL keeps only metadata.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import PayloadTooLargeError, UnsupportedMediaError, ValidationError
from app.database.base import utcnow
from app.media.models import MediaAsset
from app.providers.storage import build_storage_key, get_storage

ALLOWED_FORMATS = {
    "JPEG": (".jpg", ("image/jpeg",)),
    "PNG": (".png", ("image/png",)),
    "WEBP": (".webp", ("image/webp",)),
    "HEIF": (".heic", ("image/heic", "image/heif")),
}
ALLOWED_PURPOSES = {
    "post_image",
    "disease_scan",
    "profile_avatar",
    "soil_report",
    "scheme_document",
}

Image.MAX_IMAGE_PIXELS = 60_000_000  # explicit decompression-bomb ceiling


@dataclass(slots=True)
class ValidatedImage:
    data: bytes
    mime_type: str
    extension: str
    format_name: str
    width: int
    height: int
    checksum: str
    has_gps: bool
    notes: list[str]


def sniff_and_validate(
    data: bytes, *, declared_mime: str | None, filename: str | None
) -> ValidatedImage:
    if not data:
        raise ValidationError("The uploaded file is empty.")
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise PayloadTooLargeError(
            f"Images must be smaller than {settings.max_upload_mb} MB.",
            details={"max_mb": settings.max_upload_mb, "size_bytes": len(data)},
        )
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # cheap integrity check
        with Image.open(io.BytesIO(data)) as image:
            fmt = (image.format or "").upper()
            width, height = image.size
            has_gps = bool((image.getexif() or {}).get(34853))  # GPSInfo
    except (UnidentifiedImageError, OSError) as exc:
        raise UnsupportedMediaError(
            "That file is not a readable image. Please upload a JPEG, PNG or WebP photo.",
            details={"declared_mime": declared_mime, "filename": filename},
        ) from exc

    if fmt not in ALLOWED_FORMATS:
        raise UnsupportedMediaError(
            "Unsupported image format. Please use JPEG, PNG or WebP.",
            details={"detected_format": fmt, "allowed": sorted(ALLOWED_FORMATS)},
        )
    extension, mimes = ALLOWED_FORMATS[fmt]
    if declared_mime and declared_mime.lower() not in mimes:
        raise UnsupportedMediaError(
            "The file extension does not match the file contents.",
            details={"detected_format": fmt, "declared_mime": declared_mime},
        )
    if min(width, height) < settings.image_min_side_px:
        raise ValidationError(
            f"Image is too small ({width}×{height}). Please use a photo of at least "
            f"{settings.image_min_side_px}×{settings.image_min_side_px} pixels.",
            details={"width": width, "height": height},
        )
    if max(width, height) > settings.image_max_side_px:
        raise ValidationError(
            f"Image is too large ({width}×{height}). Maximum side is {settings.image_max_side_px} pixels.",
            details={"width": width, "height": height},
        )
    notes: list[str] = []
    if fmt in ("JPEG", "HEIF") and data.upper().find(b"EXIF") == -1:
        notes.append("no_camera_metadata")
    if has_gps:
        notes.append("contains_gps_metadata")
    if max(width, height) < 320:
        notes.append("low_resolution")
    return ValidatedImage(
        data=data,
        mime_type=mimes[0],
        extension=extension,
        format_name=fmt,
        width=width,
        height=height,
        checksum=hashlib.sha256(data).hexdigest(),
        has_gps=has_gps,
        notes=notes,
    )


def store_image(
    db: Session,
    *,
    data: bytes,
    declared_mime: str | None,
    filename: str | None,
    owner_id: uuid.UUID | None,
    purpose: str = "post_image",
    is_demo: bool = False,
) -> tuple[MediaAsset, dict[str, object]]:
    if purpose not in ALLOWED_PURPOSES:
        raise ValidationError(
            "Unknown upload purpose.", details={"allowed": sorted(ALLOWED_PURPOSES)}
        )
    validated = sniff_and_validate(data, declared_mime=declared_mime, filename=filename)
    storage = get_storage()
    key = build_storage_key(purpose=purpose, owner_id=owner_id, extension=validated.extension)
    try:
        stored = storage.put(key=key, data=validated.data, content_type=validated.mime_type)
    except Exception as exc:
        from app.core.errors import ProviderUnavailableError

        raise ProviderUnavailableError(
            "Image storage is temporarily unavailable. Please try again.",
            details={"backend": storage.name},
        ) from exc

    asset = MediaAsset(
        owner_id=owner_id,
        purpose=purpose,
        storage_backend=stored.backend,
        storage_key=stored.key,
        public_url=stored.url,
        original_filename=(filename or "")[:255] or None,
        mime_type=validated.mime_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=validated.checksum,
        width=validated.width,
        height=validated.height,
        validated_at=utcnow(),
        validation_notes=validated.notes,
        is_demo=is_demo,
    )
    db.add(asset)
    db.flush()
    validation_report = {
        "format": validated.format_name,
        "width": validated.width,
        "height": validated.height,
        "mime_type": validated.mime_type,
        "size_bytes": stored.size_bytes,
        "checksum_sha256": validated.checksum,
        "quality_notes": validated.notes,
        "contains_gps_metadata": validated.has_gps,
        "max_upload_mb": settings.max_upload_mb,
    }
    return asset, validation_report


def read_image_bytes(asset: MediaAsset) -> bytes:
    return get_storage().get(asset.storage_key)


def delete_media(db: Session, asset: MediaAsset) -> None:
    get_storage().delete(asset.storage_key)
    db.delete(asset)
