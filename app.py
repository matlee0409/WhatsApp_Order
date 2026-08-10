"""Flask app — Zernio WhatsApp and Paystack webhooks.

There is deliberately NO Telegram inbound route — Telegram is outbound only
(Section 13). Both webhooks validate their signatures, are idempotent, and
return 200 quickly (Section 12.9). debug is forced off in production and no
stack traces are returned to callers.
"""

import hmac
import json
import secrets
import threading
import time
from collections import deque
from contextlib import contextmanager
from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.exceptions import HTTPException

import config
import sheets
import zernio
from conversation import handle_interactive, handle_message, interactive_payload
from dashboard import dashboard_context
from db import session_scope
from models import MenuCategory, MenuItem, MenuItemImage
from logger import get_logger
from notifier import notify_admin
from paystack import parse_event, verify_signature

log = get_logger("app")

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY or ("preview-only-secret" if not config.is_production() else secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=config.is_production(),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)

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


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}, 200


_login_rate = _RateLimiter(limit=8, window=300)


def _safe_next(target: str) -> bool:
    host = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target or ""))
    return candidate.scheme in {"http", "https"} and candidate.netloc == host.netloc


def _dashboard_password() -> str:
    if config.DASHBOARD_PASSWORD:
        return config.DASHBOARD_PASSWORD
    if not config.is_production():
        return "dashboard"
    return ""


def dashboard_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("dashboard_authenticated"):
            return redirect(url_for("dashboard_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/dashboard/login", methods=["GET", "POST"])
def dashboard_login():
    if session.get("dashboard_authenticated"):
        return redirect(url_for("dashboard_page", page="orders"))
    error = None
    if request.method == "POST":
        remote_key = request.remote_addr or "unknown"
        supplied = request.form.get("password", "")
        expected = _dashboard_password()
        if not _login_rate.allow(remote_key):
            error = "Too many attempts. Please wait a few minutes and try again."
        elif expected and hmac.compare_digest(supplied, expected):
            session.clear()
            session["dashboard_authenticated"] = True
            session.permanent = True
            target = request.form.get("next", "")
            destination = target if target and _safe_next(target) else url_for("dashboard_page", page="orders")
            return redirect(destination)
        else:
            error = "The password you entered is not correct."
    return render_template("login.html", error=error, next=request.args.get("next", ""))


@app.post("/dashboard/logout")
def dashboard_logout():
    session.clear()
    return redirect(url_for("dashboard_login"))


@app.get("/")
def index():
    return redirect(url_for("dashboard_page", page="orders"))


@app.get("/dashboard")
@dashboard_required
def dashboard_home():
    return redirect(url_for("dashboard_page", page="orders"))


@app.get("/dashboard/<page>")
@dashboard_required
def dashboard_page(page):
    allowed = {"orders", "analytics", "products", "catalog", "payments", "settings", "support"}
    if page not in allowed:
        return jsonify(error="Not Found"), 404
    return render_template(
        "dashboard.html",
        **dashboard_context(page, session.get("zernio_connection")),
        zernio_configured=bool(config.ZERNIO_API_KEY),
    )


@app.get("/media/products/<int:item_id>")
def product_image(item_id):
    with session_scope() as db_session:
        image = db_session.query(MenuItemImage).filter_by(menu_item_id=item_id).first()
        if image is None:
            return Response(status=404)
        return Response(image.data, mimetype=image.mime_type, headers={"Cache-Control": "public, max-age=3600"})


@app.post("/dashboard/menu-items/<int:item_id>/image")
@dashboard_required
def upload_menu_item_image(item_id):
    upload = request.files.get("image")
    if upload is None or not upload.mimetype.startswith("image/"):
        return jsonify(error="Choose an image file."), 400
    data = upload.read()
    if not data or len(data) > 5 * 1024 * 1024:
        return jsonify(error="Images must be smaller than 5 MB."), 400
    with session_scope() as db_session:
        item = db_session.get(MenuItem, item_id)
        if item is None:
            return jsonify(error="Menu item not found."), 404
        image = db_session.query(MenuItemImage).filter_by(menu_item_id=item_id).first()
        if image is None:
            image = MenuItemImage(menu_item_id=item_id, mime_type=upload.mimetype, data=data)
            db_session.add(image)
        else:
            image.mime_type = upload.mimetype
            image.data = data
    return jsonify(ok=True, image_url=f"/media/products/{item_id}")


@app.post("/dashboard/menu-items/<int:item_id>")
@dashboard_required
def update_menu_item(item_id):
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    category_id = payload.get("category_id")
    try:
        price_kobo = int(round(float(payload.get("price")) * 100))
    except (TypeError, ValueError):
        return jsonify(error="Enter a valid price."), 400
    if not name or price_kobo < 0 or not isinstance(category_id, int):
        return jsonify(error="Name, category, and price are required."), 400
    with session_scope() as db_session:
        item = db_session.get(MenuItem, item_id)
        category = db_session.get(MenuCategory, category_id)
        if item is None or category is None:
            return jsonify(error="Menu item or category not found."), 404
        item.name = name
        item.description = (payload.get("description") or "").strip() or None
        item.price_kobo = price_kobo
        item.category = category
        item.is_available = bool(payload.get("active"))
    return jsonify(ok=True)


@app.post("/dashboard/menu-categories/<int:category_id>")
@dashboard_required
def update_menu_category(category_id):
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify(error="Category name is required."), 400
    with session_scope() as db_session:
        category = db_session.get(MenuCategory, category_id)
        if category is None:
            return jsonify(error="Category not found."), 404
        category.name = name
        category.is_active = bool(payload.get("active"))
    return jsonify(ok=True)


@app.get("/dashboard/zernio/connect")
@dashboard_required
def zernio_connect():
    try:
        auth_url, state = zernio.get_whatsapp_auth_url(
            config.ZERNIO_REDIRECT_URI or url_for("zernio_callback", _external=True)
        )
    except Exception as exc:
        log.error("Unable to start Zernio WhatsApp connection: %s", exc)
        return redirect(url_for("dashboard_page", page="settings", zernio_error="unavailable"))
    session["zernio_oauth_state"] = state
    return redirect(auth_url)


@app.get("/dashboard/zernio/callback")
@dashboard_required
def zernio_callback():
    expected_state = session.pop("zernio_oauth_state", "")
    supplied_state = request.args.get("state", "")
    if not expected_state or not hmac.compare_digest(expected_state, supplied_state):
        log.warning("Rejected Zernio callback with invalid state")
        return redirect(url_for("dashboard_page", page="settings", zernio_error="invalid_state"))
    try:
        session["zernio_connection"] = zernio.callback_connection(request.args)
    except ValueError as exc:
        log.warning("Zernio WhatsApp connection was incomplete: %s", exc)
        return redirect(url_for("dashboard_page", page="settings", zernio_error="incomplete"))
    return redirect(url_for("dashboard_page", page="settings", zernio_connected="1"))


@app.post("/zernio/webhook")
def zernio_webhook():
    raw_body = request.get_data()
    supplied = (
        request.headers.get("X-Zernio-Signature")
        or request.headers.get("X-Webhook-Signature")
        or request.headers.get("X-Zernio-Webhook-Secret", "")
    )
    if not zernio.verify_webhook_signature(raw_body, supplied):
        return Response("Forbidden", status=403)
    payload = request.get_json(silent=True) or {}
    event = payload.get("data", payload)
    if not isinstance(event, dict):
        return Response("", status=200)
    message = event.get("message", event)
    if not isinstance(message, dict):
        message = {}
    contact = event.get("contact", {}) or {}
    account = event.get("account", {}) or {}
    phone = (event.get("from") or contact.get("phoneNumber") or "").strip()
    account_id = event.get("accountId") or account.get("accountId")
    conversation = event.get("conversation", {}) or {}
    conversation_id = event.get("conversationId") or conversation.get("id")
    interaction = message.get("interactive") or event.get("interactive") or event.get("metadata")
    body = message.get("text") or event.get("text") or ""
    if not _valid_phone(phone) or not account_id or not conversation_id:
        return Response("", status=200)
    zernio.remember_conversation(phone, account_id, conversation_id)
    if not _rate.allow(phone):
        return Response("", status=200)
    try:
        reply = handle_interactive(phone, interaction) if interaction else handle_message(phone, body)
        rich_reply = interactive_payload(phone)
        zernio.send_message(account_id, conversation_id, reply, rich_reply)
    except Exception as exc:
        log.error("Zernio webhook processing failed: %s", exc)
        notify_admin(f"Zernio webhook processing failed: {exc}")
    return Response("", status=200)


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
    zernio.send_message_to_phone(
        phone,
        f"Payment confirmed! Your order {resolved_ref} is being prepared.\n"
        f"We will let you know when it is ready for pickup.\n"
        f"Pickup address: {config.PICKUP_ADDRESS}"
    )

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
