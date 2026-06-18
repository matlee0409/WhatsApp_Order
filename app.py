"""Flask app — TWO inbound webhooks: WhatsApp (Twilio) + Paystack (Section 3).

There is deliberately NO Telegram inbound route — Telegram is outbound only
(Section 13). Both webhooks validate their signatures, are idempotent, and
return 200 quickly (Section 12.9). debug is forced off in production and no
stack traces are returned to callers.
"""

import json
import threading
import time
from collections import deque
from contextlib import contextmanager

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

import config
import sheets
import whatsapp
from conversation import handle_message
from emailer import send_receipt
from logger import get_logger, redact_phone
from notifier import notify_admin, notify_kitchen
from paystack import parse_event, verify_signature

log = get_logger("app")

app = Flask(__name__)

# Bounded in-memory store of processed Twilio MessageSids (Section 12.3).
_MAX_SEEN = 2000
_seen_sids = deque(maxlen=_MAX_SEEN)
_seen_set = set()


def _already_seen_sid(sid: str) -> bool:
    if not sid:
        return False
    if sid in _seen_set:
        return True
    if len(_seen_sids) == _MAX_SEEN:
        _seen_set.discard(_seen_sids[0])  # evicted oldest
    _seen_sids.append(sid)
    _seen_set.add(sid)
    return False


def _valid_phone(phone: str) -> bool:
    """E.164-ish: digits only after optional +, at least 7 digits
    (Section 12.4)."""
    if not phone:
        return False
    digits = phone[1:] if phone.startswith("+") else phone
    return digits.isdigit() and len(digits) >= 7


# ─── Per-number rate limiter (H-1) — ~10 inbound / 60s ──────────────────────
# Same sliding-window approach as the Ajo Bot, for consistency.
class _RateLimiter:
    def __init__(self, limit: int = 10, window: int = 60):
        self._limit = limit
        self._window = window
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            while dq and now - dq[0] > self._window:
                dq.popleft()
            if len(dq) >= self._limit:
                return False
            dq.append(now)
            return True


_rate = _RateLimiter()


# ─── Per-reference processing lock (H-5) ────────────────────────────────────
class _ReferenceLocks:
    """Hand out one lock per payment reference so the idempotency check and the
    paid-write are serialized for the SAME reference. Two simultaneous duplicate
    webhooks for one reference cannot both pass payment_ref_processed() before
    either writes.

    Bounded: locks are reference-counted and dropped once no caller holds them,
    so the map only ever holds entries for references being processed right now.
    """

    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[str, list] = {}  # reference -> [lock, waiter_count]

    @contextmanager
    def hold(self, reference: str):
        with self._guard:
            entry = self._locks.get(reference)
            if entry is None:
                entry = self._locks[reference] = [threading.Lock(), 0]
            entry[1] += 1
            lock = entry[0]
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                entry = self._locks.get(reference)
                if entry is not None:
                    entry[1] -= 1
                    if entry[1] <= 0:
                        self._locks.pop(reference, None)


_reference_locks = _ReferenceLocks()


# ─── Flask hardening (M-6) ──────────────────────────────────────────────────
@app.errorhandler(Exception)
def _handle_exception(exc):
    """Generic error responses only — never leak stack traces to callers."""
    if isinstance(exc, HTTPException):
        return jsonify(error=exc.name), exc.code
    log.error("Unhandled application error: %s", exc)
    return jsonify(error="Internal Server Error"), 500


@app.get("/health")
def health():
    return {"status": "ok"}, 200


# ─── WhatsApp inbound (Twilio) ──────────────────────────────────────────────

@app.post("/whatsapp/webhook")
def whatsapp_webhook():
    # Validate Twilio signature against PUBLIC_WEBHOOK_URL (Section 12.2).
    signature = request.headers.get("X-Twilio-Signature", "")
    form = request.form.to_dict()
    if not whatsapp.validate_twilio_signature(signature, form):
        log.warning("Rejected WhatsApp webhook: bad Twilio signature")
        return Response("Forbidden", status=403)

    # Idempotency by MessageSid (Section 12.3).
    message_sid = form.get("MessageSid", "")
    if _already_seen_sid(message_sid):
        log.info("Duplicate WhatsApp message %s ignored", message_sid)
        return Response("", status=200, mimetype="text/xml")

    raw_from = form.get("From", "")  # e.g. "whatsapp:+2348012345890"
    phone = raw_from.replace("whatsapp:", "").strip()
    body = form.get("Body", "")

    if not _valid_phone(phone):
        log.warning("Rejected WhatsApp webhook: invalid phone %s",
                    redact_phone(phone))
        return Response("", status=200, mimetype="text/xml")

    # Per-number rate limit (H-1): beyond the window, ignore silently.
    if not _rate.allow(phone):
        log.warning("Rate limit hit for %s — ignoring", redact_phone(phone))
        return Response("", status=200, mimetype="text/xml")

    try:
        reply = handle_message(phone, body)
    except Exception as exc:
        log.error("Conversation handler error: %s", exc)
        notify_admin(f"Conversation handler crashed: {exc}")
        reply = "Sorry, something went wrong. Please try again shortly."

    if reply:
        whatsapp.send_whatsapp(phone, reply)

    # Empty TwiML — we replied via the REST API above.
    return Response("<Response></Response>", status=200, mimetype="text/xml")


# ─── Paystack inbound ───────────────────────────────────────────────────────

@app.post("/paystack/webhook")
def paystack_webhook():
    # Read the RAW body BEFORE parsing (Section 7.2).
    raw_body = request.get_data()
    signature = request.headers.get("x-paystack-signature", "")
    if not verify_signature(raw_body, signature):
        log.warning("Rejected Paystack webhook: bad signature")
        return Response("Unauthorized", status=401)

    event, data = parse_event(raw_body)

    # Ignore everything but charge.success (Section 7.3 step 2).
    if event != "charge.success":
        return Response("", status=200)

    payment_ref = data.get("reference", "")
    metadata = data.get("metadata", {}) or {}
    order_ref = metadata.get("order_ref") or payment_ref

    try:
        # H-5: serialize the check-then-write for this reference so duplicate
        # simultaneous webhooks can't both pass the idempotency check.
        with _reference_locks.hold(payment_ref or order_ref):
            _process_successful_charge(order_ref, payment_ref, data)
    except Exception as exc:
        log.error("Error processing charge for %s: %s", order_ref, exc)
        notify_admin(f"Error processing Paystack charge {order_ref}: {exc}")

    # Always 200 so Paystack does not retry a handled event.
    return Response("", status=200)


def _process_successful_charge(order_ref, payment_ref, data):
    # Idempotency by payment reference in the Orders sheet (Section 7.3 step 3).
    if sheets.payment_ref_processed(payment_ref):
        log.info("Payment %s already processed — skipping", payment_ref)
        return

    # Find the order by reference, falling back to payment reference.
    row_num, record = sheets.find_order_by_ref(order_ref)
    if record is None:
        row_num, record = sheets.find_order_by_payment_ref(payment_ref)

    if record is None:
        log.warning("Paid order not found: ref=%s payref=%s",
                    order_ref, payment_ref)
        notify_admin(
            f"Payment received but order not found (ref={order_ref}, "
            f"payref={payment_ref})."
        )
        return

    resolved_ref = record["order_ref"]

    # C-2: Verify the paid amount covers the order's stored total BEFORE
    # fulfilling. Paystack reports `amount` in kobo, so convert the stored
    # Naira total to kobo for an exact integer comparison.
    expected_kobo = int(round(record["total"] * 100))
    paid_kobo = int(data.get("amount") or 0)
    if paid_kobo < expected_kobo:
        log.warning("Underpayment for order %s: paid=%s expected=%s kobo — "
                    "not fulfilling.", resolved_ref, paid_kobo, expected_kobo)
        notify_admin(
            f"Underpayment detected for order {resolved_ref}: paid "
            f"{paid_kobo} kobo, expected {expected_kobo} kobo. Not fulfilled."
        )
        return

    # Mark Paid + record Paid At (Section 7.3 step 6).
    sheets.mark_order_paid(resolved_ref, payment_ref)

    # Reconstruct the cart for notifications.
    try:
        cart = json.loads(record["items"]) if record["items"] else []
    except (ValueError, TypeError):
        cart = []
    total = record["total"]
    name = record["name"]
    phone = record["phone"]

    # Customer WhatsApp confirmation (Section 7.3 step 7).
    whatsapp.send_whatsapp(
        phone,
        f"Payment confirmed! Your order {resolved_ref} is being prepared.\n"
        f"We will let you know when it is ready for pickup.\n"
        f"Pickup address: {config.PICKUP_ADDRESS}"
    )

    # Telegram kitchen notification (Section 7.3 step 8).
    notify_kitchen(resolved_ref, name, phone, cart, total)

    # Optional Brevo email receipt (Section 7.3 step 9).
    if config.EMAIL_ENABLED:
        email = data.get("customer", {}).get("email")
        if email and not email.endswith("@orders.local"):
            send_receipt(email, resolved_ref, cart, total)

    log.info("Processed payment for order %s", resolved_ref)


if __name__ == "__main__":
    # C-3: refuse to start with a Paystack test key in production.
    config.check_production_safety()
    # Section 12.9: debug off in production, never expose stack traces.
    app.run(
        host="0.0.0.0",
        port=config.PORT,
        debug=not config.is_production(),
    )
