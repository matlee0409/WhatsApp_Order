"""Telegram OUTBOUND notifications to the owner/kitchen (Section 3).

OUTBOUND ONLY. There is no Telegram inbound webhook and no command handling in
this build (Section 13) — the owner marks orders ready by editing the sheet.

Two uses:
- notify_kitchen(): full order details on payment (Section 7.3 step 8).
- notify_admin(): fail-loud alerts when something needs a human (Section 0.7).

Sends via the Telegram Bot HTTP API. Never raises into a webhook path.
"""

import requests

import config
from logger import get_logger

log = get_logger("notifier")

_TIMEOUT = 15


def _send(text: str) -> bool:
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_ADMIN_CHAT_ID
    if not token or not chat_id:
        log.error("Telegram not configured — cannot send notification")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.error("Telegram send failed: %s", exc)
        return False


def notify_admin(message: str) -> bool:
    """Fail-loud alert to the owner (errors, order-not-found, send failures)."""
    return _send(f"⚠️ <b>Order Bot Alert</b>\n{message}")


def notify_kitchen(order_ref, name, phone, cart, total) -> bool:
    """Full order details for the kitchen when a payment is confirmed.

    `cart` is the list of item dicts {name, quantity, unit_price, line_total}.
    The customer phone is included here because the kitchen legitimately needs
    it to coordinate pickup (this is an owner-facing channel, not a log).
    """
    lines = [
        "🍽️ <b>New Paid Order</b>",
        f"Ref: <b>{order_ref}</b>",
    ]
    if name:
        lines.append(f"Customer: {name}")
    if phone:
        lines.append(f"Phone: {phone}")
    lines.append("")
    for item in cart:
        lines.append(
            f"{item['quantity']}x {item['name']} — N{int(item['line_total']):,}"
        )
    lines.append("")
    lines.append(f"<b>Total: N{int(total):,}</b>")
    return _send("\n".join(lines))
