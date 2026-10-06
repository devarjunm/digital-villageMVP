"""SMS delivery abstraction.

`SMSProvider.send` is the only way an OTP leaves the process.

  * ConsoleSMSProvider — development/demo default. Writes the message to the
    application log and, for non-production environments, returns the code so
    the API can expose it as an explicit `dev_otp` hint (gated by APP_ENV).
  * GatewaySMSProvider — generic HTTP gateway (URL + API key + sender id from
    the environment). This is the production path; it requires
    SMS_PROVIDER=sms_gateway plus credentials and raises
    ProviderUnavailableError when they are missing rather than silently
    pretending delivery succeeded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.errors import ProviderUnavailableError

logger = logging.getLogger(__name__)

PROVIDER_NAME = "sms"


@dataclass(slots=True)
class SMSResult:
    delivered: bool
    provider: str
    detail: str | None = None
    # Only populated by the console provider in non-production environments.
    dev_code: str | None = None


class SMSProvider(Protocol):
    name: str

    def send_otp(self, *, phone_e164: str, code: str, purpose: str, language: str) -> SMSResult: ...

    def available(self) -> bool: ...


class ConsoleSMSProvider:
    name = "console"

    def available(self) -> bool:
        return True

    def send_otp(self, *, phone_e164: str, code: str, purpose: str, language: str) -> SMSResult:
        masked = phone_e164[:3] + "****" + phone_e164[-2:]
        logger.info(
            "otp_dispatched_console",
            extra={"extra_fields": {"phone": masked, "purpose": purpose, "language": language}},
        )
        # The code itself is never logged. It is returned only so that
        # development clients can complete the flow; the API layer decides
        # whether it is allowed to expose it (non-production only).
        return SMSResult(
            delivered=True,
            provider=self.name,
            detail="Console provider: message not sent over SMS. Development use only.",
            dev_code=code if settings.app_env != "production" else None,
        )


class GatewaySMSProvider:
    """Generic transactional-SMS HTTP gateway.

    Configure with SMS_GATEWAY_URL / SMS_GATEWAY_API_KEY / SMS_SENDER_ID. The
    exact request shape depends on the vendor; the payload below covers the
    common JSON API style (MSG91/Fast2SMS/Gupshup-style) and should be adjusted
    to the contracted vendor.
    """

    name = "sms_gateway"

    def __init__(self) -> None:
        self.url = getattr(settings, "sms_gateway_url", "") or ""
        self.api_key = getattr(settings, "sms_gateway_api_key", "") or ""
        self.sender_id = getattr(settings, "sms_sender_id", "") or "DIGVIL"

    def available(self) -> bool:
        return bool(self.url and self.api_key)

    def send_otp(self, *, phone_e164: str, code: str, purpose: str, language: str) -> SMSResult:
        if not self.available():
            raise ProviderUnavailableError(
                "SMS delivery is not configured on this deployment.",
                details={
                    "provider": self.name,
                    "missing": ["SMS_GATEWAY_URL", "SMS_GATEWAY_API_KEY"],
                },
            )
        template = {
            "en": f"{code} is your Digital Village verification code. Valid for 5 minutes. Do not share it.",
            "mr": f"{code} हा तुमचा Digital Village पडताळणी कोड आहे. ५ मिनिटांसाठी वैध. कोणालाही सांगू नका.",
            "hi": f"{code} आपका Digital Village सत्यापन कोड है। 5 मिनट के लिए मान्य। किसी को न बताएं।",
        }.get(language, f"{code} is your Digital Village verification code.")
        try:
            response = httpx.post(
                self.url,
                json={
                    "sender": self.sender_id,
                    "to": phone_e164,
                    "message": template,
                    "type": "otp",
                    "purpose": purpose,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "The SMS gateway could not be reached. Please try again.",
                details={"provider": self.name},
            ) from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError(
                "The SMS gateway rejected the request.",
                details={"provider": self.name, "status": response.status_code},
            )
        return SMSResult(delivered=True, provider=self.name)


def get_sms_provider() -> SMSProvider:
    if settings.sms_provider == "sms_gateway":
        return GatewaySMSProvider()
    return ConsoleSMSProvider()
