"""Optional Brevo email receipt (Section 7.3 step 9).

Entirely optional: enabled only when BREVO_API_KEY and BREVO_SENDER_EMAIL are
set (config.EMAIL_ENABLED). When disabled, send_receipt() is a quiet no-op so
the payment flow never depends on email being configured.
"""

import requests

import config
from logger import get_logger

log = get_logger("emailer")

_API_URL = "https://api.brevo.com/v3/smtp/email"
_TIMEOUT = 15


def send_receipt(to_email, order_ref, cart, total) -> bool:
    """Send an order receipt via Brevo. No-op (returns False) when email is not
    enabled. Never raises into the payment path."""
    if not config.EMAIL_ENABLED:
        return False
    if not to_email:
        return False

    rows = "".join(
        f"<tr><td>{item['quantity']}x {item['name']}</td>"
        f"<td style='text-align:right'>N{int(item['line_total']):,}</td></tr>"
        for item in cart
    )
    html = (
        f"<h2>Order {order_ref}</h2>"
        f"<table style='width:100%;max-width:400px'>{rows}"
        f"<tr><td><b>Total</b></td>"
        f"<td style='text-align:right'><b>N{int(total):,}</b></td></tr></table>"
        f"<p>Thank you for ordering from {config.BUSINESS_NAME}.</p>"
    )

    payload = {
        "sender": {
            "email": config.BREVO_SENDER_EMAIL,
            "name": config.BREVO_SENDER_NAME or config.BUSINESS_NAME,
        },
        "to": [{"email": to_email}],
        "subject": f"Your {config.BUSINESS_NAME} order {order_ref}",
        "htmlContent": html,
    }
    headers = {
        "api-key": config.BREVO_API_KEY,
        "Content-Type": "application/json",
        "accept": "application/json",
    }
    try:
        resp = requests.post(_API_URL, json=payload, headers=headers,
                             timeout=_TIMEOUT)
        resp.raise_for_status()
        log.info("Sent email receipt for order %s", order_ref)
        return True
    except requests.RequestException as exc:
        log.error("Brevo email failed for %s: %s", order_ref, exc)
        return False
