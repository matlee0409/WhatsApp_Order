"""Paystack integration (Section 7) — payment links + webhook security.

- generate_payment_link(): POST /transaction/initialize for an exact amount.
- verify_signature(): HMAC-SHA512 of the RAW body keyed by the webhook secret,
  compared with hmac.compare_digest (Section 7.2 / 12.1).
- parse_event(): safely decode a webhook payload into event fields.

No secret is read at import time — credentials are pulled from config when a
function actually runs, so this module imports cleanly without a .env.
"""

import hashlib
import hmac
import json

import requests

import config
from logger import get_logger

log = get_logger("paystack")

_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"
_TIMEOUT = 15


def generate_payment_link(amount_naira, order_ref, phone, email=None):
    """Create a unique exact-amount payment link (Section 7.1).

    amount_naira is converted to kobo (×100). Email defaults to a synthetic
    {order_ref}@orders.local since Paystack requires the field but it need not
    be real here. Returns the authorization_url, or None on any failure so the
    conversation can ask the customer to retry shortly.
    """
    secret = config.PAYSTACK_SECRET_KEY
    if not secret:
        log.error("PAYSTACK_SECRET_KEY not configured — cannot create link")
        return None

    if not email:
        email = config.BUSINESS_EMAIL or f"orders@{config.BUSINESS_NAME.lower().replace(' ', '')}.com"

    payload = {
        "email": email,
        "amount": int(round(float(amount_naira) * 100)),  # Naira -> kobo
        "reference": order_ref,
        "metadata": {"phone": phone, "order_ref": order_ref},
        "channels": ["card", "bank", "ussd", "bank_transfer"],
    }
    headers = {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(
            _INITIALIZE_URL, json=payload, headers=headers, timeout=_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("Paystack initialize failed for %s: %s", order_ref, exc)
        return None

    if not data.get("status"):
        log.error("Paystack initialize rejected for %s: %s",
                  order_ref, data.get("message"))
        return None

    url = data.get("data", {}).get("authorization_url")
    if not url:
        log.error("Paystack response missing authorization_url for %s", order_ref)
        return None

    log.info("Generated payment link for order %s", order_ref)
    return url


def verify_signature(raw_body: bytes, signature: str) -> bool:
    """Validate the x-paystack-signature header (Section 7.2 / 12.1).

    HMAC-SHA512 of the RAW request body keyed by PAYSTACK_WEBHOOK_SECRET,
    constant-time compared. Returns False on any missing input — caller must
    respond 401 on False.
    """
    secret = config.PAYSTACK_WEBHOOK_SECRET
    if not secret:
        log.error("PAYSTACK_WEBHOOK_SECRET not configured — rejecting webhook")
        return False
    if not signature or raw_body is None:
        return False
    signature = signature.strip()  # L-5: tolerate surrounding whitespace

    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_event(raw_body: bytes):
    """Decode a webhook body into (event_name, data_dict).

    Returns (None, {}) if the body is not valid JSON. Caller checks the event
    name and ignores anything other than charge.success (Section 7.3).
    """
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, AttributeError, UnicodeDecodeError):
        log.warning("Paystack webhook body was not valid JSON")
        return None, {}
    return payload.get("event"), payload.get("data", {}) or {}
