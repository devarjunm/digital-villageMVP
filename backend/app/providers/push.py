"""Push notification provider abstraction.

Development default is the console provider: notifications are stored in the
database and reported as `delivered=False, reason="console_provider"` — the app
never claims a push was delivered when no push service was called.

Production uses Firebase Cloud Messaging (HTTP v1). It requires a service
account JSON file; when `PUSH_PROVIDER=fcm` is selected without credentials the
provider raises `PushNotConfiguredError`, which the service records on the
notification (`push_error`) instead of silently succeeding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class PushMessage:
    token: str
    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    deep_link: str | None = None


@dataclass(slots=True)
class PushResult:
    delivered: bool
    reason: str | None = None
    detail: str | None = None
    provider: str = "console"


def _service_account_assertion(credentials: dict[str, Any], *, scope: str) -> str:
    """Signed JWT used for the OAuth2 service-account flow (RFC 7523)."""
    import time

    import jwt

    now = int(time.time())
    claims = {
        "iss": credentials["client_email"],
        "scope": scope,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(claims, credentials["private_key"], algorithm="RS256")


class PushNotConfiguredError(ConfigurationError):
    """Raised when a real push provider is selected but not configured."""


class PushProvider(Protocol):
    name: str
    is_demo: bool

    def send(self, messages: list[PushMessage]) -> list[PushResult]: ...

    def health(self) -> dict[str, Any]: ...


class ConsolePushProvider:
    """Stores nothing, sends nothing. Used in development and in tests."""

    name = "console"
    is_demo = True

    def send(self, messages: list[PushMessage]) -> list[PushResult]:
        for message in messages:
            logger.info(
                "push_console",
                extra={
                    "extra_fields": {
                        "token_suffix": message.token[-6:],
                        "title": message.title,
                        "deep_link": message.deep_link,
                    }
                },
            )
        return [
            PushResult(
                delivered=False,
                reason="console_provider",
                detail="No push service was called (PUSH_PROVIDER=console).",
                provider=self.name,
            )
            for _ in messages
        ]

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "is_demo": True,
            "configured": True,
            "note": "Push messages are logged, not delivered. Set PUSH_PROVIDER=fcm for production.",
        }


class FcmPushProvider:
    """Firebase Cloud Messaging HTTP v1 sender."""

    name = "fcm"
    is_demo = False
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self) -> None:
        credentials_path = settings.push_credentials_file
        if not credentials_path:
            raise PushNotConfiguredError(
                "PUSH_PROVIDER=fcm requires PUSH_CREDENTIALS_FILE (Firebase service account JSON)."
            )
        path = Path(credentials_path)
        if not path.exists():
            raise PushNotConfiguredError(f"Push credentials file not found: {path}")
        self._credentials = json.loads(path.read_text())
        self.project_id = self._credentials.get("project_id")
        if not self.project_id:
            raise PushNotConfiguredError("Service account JSON is missing project_id.")
        self._cached_token: tuple[str, float] | None = None

    def _access_token(self) -> str:
        import time

        now = time.time()
        if self._cached_token and self._cached_token[1] > now + 60:
            return self._cached_token[0]
        assertion = _service_account_assertion(
            self._credentials, scope="https://www.googleapis.com/auth/firebase.messaging"
        )
        response = httpx.post(
            self.TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload["access_token"]
        self._cached_token = (token, now + float(payload.get("expires_in", 3600)))
        return token

    def send(self, messages: list[PushMessage]) -> list[PushResult]:
        token = self._access_token()
        url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
        headers = {"Authorization": f"Bearer {token}"}
        results: list[PushResult] = []
        for message in messages:
            payload = {
                "message": {
                    "token": message.token,
                    "notification": {"title": message.title, "body": message.body},
                    "data": {
                        **message.data,
                        **({"deep_link": message.deep_link} if message.deep_link else {}),
                    },
                    "android": {"priority": "high"},
                }
            }
            try:
                response = httpx.post(url, headers=headers, json=payload, timeout=15.0)
                if response.status_code >= 400:
                    detail = response.text[:200]
                    # 404/400 with UNREGISTERED means the token is stale.
                    results.append(
                        PushResult(
                            delivered=False,
                            reason="invalid_token"
                            if "UNREGISTERED" in detail
                            else "provider_error",
                            detail=detail,
                            provider=self.name,
                        )
                    )
                else:
                    results.append(PushResult(delivered=True, provider=self.name))
            except Exception as exc:
                results.append(
                    PushResult(
                        delivered=False,
                        reason="provider_error",
                        detail=str(exc)[:200],
                        provider=self.name,
                    )
                )
        return results

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "is_demo": False,
            "configured": True,
            "project_id": self.project_id,
        }


def get_push_provider() -> PushProvider:
    if settings.push_provider == "fcm":
        return FcmPushProvider()
    return ConsolePushProvider()
