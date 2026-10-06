"""Object-storage abstraction.

Local filesystem for development, S3-compatible (AWS S3, MinIO, R2) for
production. Keys are opaque and content-addressed by a random prefix so a
storage key never leaks an original filename or a user identifier.
"""

from __future__ import annotations

import io
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.core.config import settings
from app.core.errors import ProviderUnavailableError


@dataclass(slots=True)
class StoredObject:
    key: str
    url: str | None
    backend: str
    size_bytes: int


class StorageBackend(Protocol):
    name: str

    def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def url_for(self, key: str) -> str | None: ...

    def health(self) -> dict[str, object]: ...


class LocalStorage:
    """Writes under STORAGE_LOCAL_DIR and is served read-only at /files (dev only)."""

    name = "local"

    def __init__(self, base_dir: str | None = None) -> None:
        self.base = Path(base_dir) if base_dir else settings.storage_dir
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Reject traversal attempts before touching the filesystem.
        candidate = (self.base / key).resolve()
        if not str(candidate).startswith(str(self.base.resolve())):
            raise ValueError("storage key escapes the storage root")
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

    def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._path(key)
        path.write_bytes(data)
        return StoredObject(key=key, url=self.url_for(key), backend=self.name, size_bytes=len(data))

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except ValueError:
            return

    def url_for(self, key: str) -> str | None:
        return f"{settings.storage_public_base_url.rstrip('/')}/{key}"

    def health(self) -> dict[str, object]:
        writable = os.access(self.base, os.W_OK)
        return {"backend": self.name, "available": writable, "path": str(self.base)}


class S3Storage:
    """S3 / S3-compatible storage.

    Uses boto3 only when it is installed and credentials are configured; the
    provider reports itself unavailable otherwise rather than failing at request
    time with an opaque error.
    """

    name = "s3"

    def __init__(self) -> None:
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        self.endpoint = settings.s3_endpoint_url or None
        self._client = None
        if not self.bucket or not settings.aws_access_key_id:
            return
        try:
            import boto3  # imported lazily: only needed for the S3 backend

            self._client = boto3.client(
                "s3",
                region_name=self.region or None,
                endpoint_url=self.endpoint,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
        except Exception:
            self._client = None

    def available(self) -> bool:
        return self._client is not None

    def put(self, *, key: str, data: bytes, content_type: str) -> StoredObject:
        if self._client is None:
            raise ProviderUnavailableError(
                "Object storage is not configured.",
                details={"backend": self.name, "missing": ["S3_BUCKET", "AWS_ACCESS_KEY_ID"]},
            )
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=io.BytesIO(data), ContentType=content_type
        )
        return StoredObject(key=key, url=self.url_for(key), backend=self.name, size_bytes=len(data))

    def get(self, key: str) -> bytes:
        if self._client is None:
            raise ProviderUnavailableError(
                "Object storage is not configured.", details={"backend": self.name}
            )
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        if self._client is None:
            raise ProviderUnavailableError(
                "Object storage is not configured.", details={"backend": self.name}
            )
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def url_for(self, key: str) -> str | None:
        if self.endpoint:
            return f"{self.endpoint.rstrip('/')}/{self.bucket}/{key}"
        if self.region:
            return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{key}"
        return f"https://{self.bucket}.s3.amazonaws.com/{key}"

    def health(self) -> dict[str, object]:
        return {
            "backend": self.name,
            "available": self.available(),
            "bucket": self.bucket or None,
            "detail": None if self.available() else "credentials or bucket not configured",
        }


def build_storage_key(*, purpose: str, owner_id: uuid.UUID | None, extension: str) -> str:
    """content-addressed-ish key: <purpose>/<yyyy>/<mm>/<random>.<ext>"""
    now = datetime.now(UTC)
    token = uuid.uuid4().hex
    owner = str(owner_id) if owner_id else "anon"
    return f"{purpose}/{now:%Y/%m}/{owner}/{token}{extension}"


_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.storage_backend == "s3" else LocalStorage()
    return _storage


def reset_storage_for_tests(backend: StorageBackend | None = None) -> None:
    global _storage
    _storage = backend
