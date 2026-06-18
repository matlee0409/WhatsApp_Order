"""Twilio WhatsApp send wrapper + inbound signature validation.

send_whatsapp(): outbound message via the Twilio REST API.
validate_twilio_signature(): RequestValidator SDK check against the configured
PUBLIC_WEBHOOK_URL — NOT request.url — with no sandbox bypass (Section 12.2).

The Twilio client is built lazily so this module imports with no credentials.
"""

from twilio.rest import Client
from twilio.request_validator import RequestValidator

import config
from logger import get_logger, redact_phone

log = get_logger("whatsapp")

_client = None


def _get_client():
    """Build the Twilio REST client on first use. Raises clearly if creds are
    missing (only when actually sending)."""
    global _client
    if _client is None:
        sid = config.require("TWILIO_ACCOUNT_SID")
        token = config.require("TWILIO_AUTH_TOKEN")
        _client = Client(sid, token)
    return _client


def _to_whatsapp(phone: str) -> str:
    """Ensure a number carries the whatsapp: channel prefix Twilio expects."""
    phone = (phone or "").strip()
    if phone.startswith("whatsapp:"):
        return phone
    return f"whatsapp:{phone}"


def send_whatsapp(to_phone: str, body: str) -> bool:
    """Send a WhatsApp message. Returns True on success, False on failure
    (logged with redacted phone, never raising into the webhook path)."""
    from_number = config.TWILIO_WHATSAPP_FROM
    if not from_number:
        log.error("TWILIO_WHATSAPP_FROM not configured — cannot send")
        return False
    try:
        client = _get_client()
        message = client.messages.create(
            from_=_to_whatsapp(from_number),
            to=_to_whatsapp(to_phone),
            body=body,
        )
        log.info("Sent WhatsApp to %s (sid=%s)",
                 redact_phone(to_phone), message.sid)
        return True
    except Exception as exc:  # Twilio raises various exception types
        log.error("Failed to send WhatsApp to %s: %s",
                  redact_phone(to_phone), exc)
        return False


def validate_twilio_signature(signature: str, form_params: dict) -> bool:
    """Validate an inbound Twilio webhook (Section 12.2).

    Validates against config.PUBLIC_WEBHOOK_URL (the public HTTPS URL Twilio
    actually signed), never request.url, and with no sandbox bypass. Returns
    False on missing config/signature — caller responds 403 on False.
    """
    token = config.TWILIO_AUTH_TOKEN
    url = config.PUBLIC_WEBHOOK_URL
    if not token or not url:
        log.error("Twilio auth token / public URL not configured — rejecting")
        return False
    if not signature:
        return False
    validator = RequestValidator(token)
    return validator.validate(url, form_params or {}, signature)
