"""External-service providers.

Every integration the platform depends on is expressed as a small Protocol with
at least two implementations: a real one (requires credentials from the
environment) and a local/demo one used when credentials are absent, so the whole
application runs without paid infrastructure. Provider selection is centralised
here and every demo response is tagged `is_demo=true`.
"""

from __future__ import annotations

from app.providers.sms import ConsoleSMSProvider, GatewaySMSProvider, SMSProvider, get_sms_provider

__all__ = [
    "ConsoleSMSProvider",
    "GatewaySMSProvider",
    "SMSProvider",
    "get_sms_provider",
]
