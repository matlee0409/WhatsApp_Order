"""Order conversation state machine — CART MODEL (Section 6).

State is keyed by WhatsApp phone number in an in-memory dict. State resets on
restart — acceptable for Tier 1; Redis is the documented Tier 2 upgrade
(Section 13). The customer browses multiple categories, accumulates items in a
running cart, and checks out once. Nothing is written to Sheets until the
customer confirms with YES (Section 6 CART RULES).

All reply templates are fixed strings — order parsing matches against the live
menu. Customer text is untrusted (Section 12.4): order references are validated
before any lookup.

handle_message(phone, body) -> reply string. The caller (app.py) sends the reply
over WhatsApp. The order is written to Sheets inline at checkout.
"""

import json
import random
import re
import secrets
import string
import threading
import time
from collections import OrderedDict

import redis_store

_REDIS_ERRORS = (redis_store.RedisUnavailableError, OSError)
try:
    import redis
    _REDIS_ERRORS = _REDIS_ERRORS + (redis.RedisError,)
except ImportError:
    pass

import config
import nlu
import sheets
import interactive
from logger import get_logger, redact_phone
from notifier import notify_admin

log = get_logger("conversation")

# Conversation states.
START = "START"
AWAITING_CATEGORY = "AWAITING_CATEGORY"
AWAITING_ORDER = "AWAITING_ORDER"
AWAITING_MORE = "AWAITING_MORE"
AWAITING_CONFIRM = "AWAITING_CONFIRM"
AWAITING_FULFILMENT = "AWAITING_FULFILMENT"
AWAITING_NAME = "AWAITING_NAME"
AWAITING_EMAIL = "AWAITING_EMAIL"
AWAITING_PAYMENT = "AWAITING_PAYMENT"

# Bound memory: evict least-recently-used entries past this cap.
_MAX_TRACKED_NUMBERS = 5000

# In-memory conversation store: phone -> state dict.
_sessions = OrderedDict()
# H-1: guard the session/lock maps, and use a per-phone lock to serialize
# messages from the SAME number so concurrent requests cannot corrupt a session.
# Different numbers still proceed concurrently.
_store_lock = threading.Lock()
_phone_locks = OrderedDict()

_ORDER_REF_RE = re.compile(r"^ORD-[A-Z0-9]+$")
_ORDER_CMD_RE = re.compile(r"^ORDER\s+([A-Za-z0-9\-]{1,15})$", re.IGNORECASE)

# Customer-detail validation (checkout name/email collection).
_MIN_NAME_LEN = 2
_MAX_NAME_LEN = 60
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SESSION_TTL = 48 * 60 * 60
_LOCK_TTL = 30


def _redis_failure(exc):
    if config.is_production():
        raise exc
    log.warning("Redis unavailable in development; using in-memory state: %s", exc)


def _load_session(phone):
    try:
        raw = redis_store.get_redis().get(f"conversation:session:{phone}")
    except _REDIS_ERRORS as exc:
        _redis_failure(exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        if config.is_production():
            raise RuntimeError("Invalid Redis conversation session") from exc
        log.warning("Invalid Redis session in development; starting over")
        return None


def _save_session(phone, session):
    try:
        redis_store.get_redis().setex(
            f"conversation:session:{phone}", _SESSION_TTL, json.dumps(session)
        )
    except _REDIS_ERRORS as exc:
        _redis_failure(exc)


def _acquire_redis_lock(phone):
    token = secrets.token_urlsafe(24)
    try:
        client = redis_store.get_redis()
        if client.set(f"conversation:lock:{phone}", token, nx=True, ex=_LOCK_TTL):
            return client, token
        return None, None
    except _REDIS_ERRORS as exc:
        _redis_failure(exc)
        return None, None


def _release_redis_lock(client, phone, token):
    if not client:
        return
    script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
    try:
        client.eval(script, 1, f"conversation:lock:{phone}", token)
    except _REDIS_ERRORS as exc:
        _redis_failure(exc)


# ─── Order reference (Section 10) ───────────────────────────────────────────

def generate_order_ref() -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=5))
    return f"ORD-{suffix}"


def _unique_order_ref() -> str:
    """Generate an order ref, checking the Orders sheet for collisions
    (Section 10). Falls back to the generated ref if the check itself fails."""
    for _ in range(10):
        ref = generate_order_ref()
        try:
            if not sheets.order_ref_exists(ref):
                return ref
        except Exception as exc:
            log.error("Collision check failed, using generated ref: %s", exc)
            return ref
    return generate_order_ref()


# ─── Formatting helpers (fixed templates) ───────────────────────────────────

def _naira(amount) -> str:
    return f"N{int(round(amount)):,}"


def _categories_block(categories) -> str:
    return "\n".join(f"{i}. {c}" for i, c in enumerate(categories, 1))


def _cart_total(cart) -> float:
    return sum(item["line_total"] for item in cart)


def _cart_block(cart) -> str:
    return "\n".join(
        f"{item['quantity']}x {item['name']} — {_naira(item['line_total'])}"
        for item in cart
    )


def _menu_greeting(categories) -> str:
    return (
        f"Welcome to {config.BUSINESS_NAME}!\n"
        f"Here is our menu:\n"
        f"{_categories_block(categories)}\n"
        f"Reply with a number to browse that category."
    )


def _category_items_text(category, items) -> str:
    lines = [f"{category}:"]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['name']} — {_naira(item['price'])}")
    lines.append("Tell me what you would like (e.g. '2 jollof rice').")
    return "\n".join(lines)


def _added_text(added, cart, categories) -> str:
    return (
        "Added to your order:\n"
        f"{_cart_block(added)}\n\n"
        "Your cart so far:\n"
        f"{_cart_block(cart)}\n"
        f"Cart total: {_naira(_cart_total(cart))}\n\n"
        "Want to add more? Pick a category:\n"
        f"{_categories_block(categories)}\n"
        "Or reply DONE to checkout."
    )


def _checkout_summary(cart) -> str:
    return (
        "Here is your full order:\n"
        f"{_cart_block(cart)}\n"
        f"Total: {_naira(_cart_total(cart))}\n\n"
        "Reply YES to confirm and pay, or CANCEL to start over."
    )


# ─── Session + cart helpers ─────────────────────────────────────────────────

def _new_session():
    return {
        "state": START,
        "cart": [],
        "categories": [],
        "current_category": None,
        "retries": 0,
        "customer_name": None,
        "customer_email": None,
    }


def _get_session(phone):
    with _store_lock:
        persisted = _load_session(phone)
        if persisted is not None:
            _sessions[phone] = persisted
        elif phone not in _sessions:
            _sessions[phone] = _new_session()
        else:
            _sessions.move_to_end(phone)
        # Bound memory: evict least-recently-used sessions past the cap.
        while len(_sessions) > _MAX_TRACKED_NUMBERS:
            _sessions.popitem(last=False)
        return _sessions[phone]


def _phone_lock(phone):
    """Return the per-phone lock, creating it under the store guard."""
    with _store_lock:
        lock = _phone_locks.get(phone)
        if lock is None:
            lock = _phone_locks[phone] = threading.Lock()
        else:
            _phone_locks.move_to_end(phone)  # most-recently-used
        # Bound memory: evict least-recently-used locks past the cap.
        while len(_phone_locks) > _MAX_TRACKED_NUMBERS:
            _phone_locks.popitem(last=False)
        return lock


def _reset(session):
    session.update(_new_session())


def _add_to_cart(cart, items):
    """Merge parsed items into the cart: bump quantity if the item is already
    present, else append (Section 6 AWAITING_ORDER)."""
    for new in items:
        for existing in cart:
            if existing["name"].lower() == new["name"].lower():
                existing["quantity"] += new["quantity"]
                existing["line_total"] = (
                    existing["quantity"] * existing["unit_price"]
                )
                break
        else:
            cart.append(dict(new))


def _match_category(text, categories):
    """Resolve a customer reply to a category by number or name. Returns the
    category string or None."""
    text = (text or "").strip()
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(categories):
            return categories[idx]
        return None
    for c in categories:
        if c.lower() == text.lower():
            return c
    return None


def _valid_name(text):
    """Return a cleaned customer name, or None if it fails validation
    (2–60 chars after stripping, no control characters)."""
    name = (text or "").strip()
    if len(name) < _MIN_NAME_LEN or len(name) > _MAX_NAME_LEN:
        return None
    if _CONTROL_CHARS_RE.search(name):
        return None
    return name


def _valid_email(text):
    """Return a cleaned email address, or None if it does not look valid."""
    email = (text or "").strip()
    return email if _EMAIL_RE.match(email) else None


def _email_prompt():
    return ("What email should we send your receipt to?\n"
            "(Reply SKIP to continue without one.)")


# ─── Self-serve status (Section 1C) ─────────────────────────────────────────

def _handle_status_query(text, phone):
    """If the message is 'ORDER ORD-REF', return a status reply, else None.

    Order reference is validated (alphanumeric + hyphen, max 15 chars,
    Section 12.4) before any sheet lookup. The status is only revealed when the
    order belongs to the requesting (signature-validated) phone number (M-2),
    preventing enumeration of other customers' orders."""
    m = _ORDER_CMD_RE.match((text or "").strip())
    if not m:
        return None
    ref = m.group(1).upper()
    if not _ORDER_REF_RE.match(ref):
        return "That order reference does not look right. It should look like ORD-7F3A2."
    try:
        _, record = sheets.find_order_by_ref(ref)
    except Exception as exc:
        log.error("Status lookup failed for %s: %s", ref, exc)
        return "Sorry, I could not look that up right now. Please try again shortly."
    # M-2: mismatched/absent ownership gets the SAME generic reply, so an
    # attacker cannot distinguish "exists but not yours" from "does not exist".
    if record is None or record.get("phone") != phone:
        return f"No order found with reference {ref} for your number."
    return f"Order {ref} status: {record['status']}."


# ─── Main entry point ───────────────────────────────────────────────────────

def handle_interactive(phone, interaction):
    """Translate a Zernio button or list selection into the text flow."""
    command = interactive.parse_reply(interaction)
    if command.startswith("category:") or command.startswith("item:"):
        command = command.split(":", 1)[1]
    return handle_message(phone, command)


def interactive_payload(phone):
    session = _get_session(phone)
    state = session["state"]
    if state == AWAITING_CATEGORY:
        return interactive.category_list(session.get("categories", []))
    if state == AWAITING_ORDER and session.get("current_category"):
        items = sheets.get_items_in_category(session["current_category"])
        return interactive.product_list(session["current_category"], items)
    if state == AWAITING_MORE:
        return interactive.cart_actions()
    if state == AWAITING_FULFILMENT:
        return interactive.fulfilment_actions()
    if state == AWAITING_CONFIRM:
        return interactive.confirmation_actions()
    return None


def handle_message(phone, body):
    """Process one inbound WhatsApp message and return the reply text.

    Serialized per phone (H-1) so two concurrent messages from the same number
    cannot corrupt that number's session, including across workers.
    """
    with _phone_lock(phone):
        redis_client = redis_token = None
        while True:
            redis_client, redis_token = _acquire_redis_lock(phone)
            if redis_client is not None or redis_token is not None:
                break
            # A live Redis lock belongs to another worker; wait for its expiry.
            try:
                if redis_store.get_redis().exists(f"conversation:lock:{phone}"):
                    time.sleep(0.05)
                    continue
            except _REDIS_ERRORS as exc:
                _redis_failure(exc)
            break
        try:
            session = _get_session(phone)
            reply = _dispatch_message(phone, body)
            _save_session(phone, session)
            return reply
        finally:
            _release_redis_lock(redis_client, phone, redis_token)


def _dispatch_message(phone, body):
    text = (body or "").strip()
    log.info("Message from %s in state %s",
             redact_phone(phone), _get_session(phone)["state"])

    # Self-serve status works from any state and does not change state.
    status_reply = _handle_status_query(text, phone)
    if status_reply is not None:
        return status_reply

    session = _get_session(phone)
    upper = text.upper()

    # Global CANCEL/CLEAR — empty cart and start over (Section 6).
    if upper in ("CANCEL", "CLEAR"):
        _reset(session)
        return "No problem! Send a message anytime to start a new order."

    state = session["state"]
    if state in (START, AWAITING_PAYMENT):
        return _start(session)
    if state == AWAITING_CATEGORY:
        return _awaiting_category(session, text, upper)
    if state == AWAITING_ORDER:
        return _awaiting_order(session, text, phone)
    if state == AWAITING_MORE:
        return _awaiting_more(session, text, upper, phone)
    if state == AWAITING_FULFILMENT:
        return _awaiting_fulfilment(session, upper)
    if state == AWAITING_CONFIRM:
        return _awaiting_confirm(session, upper, phone)
    if state == AWAITING_NAME:
        return _awaiting_name(session, text, phone)
    if state == AWAITING_EMAIL:
        return _awaiting_email(session, text, phone)

    # Unknown state — recover safely.
    return _start(session)


def _load_categories(session):
    categories = sheets.get_categories()
    session["categories"] = categories
    return categories


def _start(session):
    _reset(session)
    try:
        categories = _load_categories(session)
    except Exception as exc:
        log.error("Menu load failed: %s", exc)
        notify_admin("Failed to load menu from Sheets on conversation start.")
        return "Sorry, our menu is unavailable right now. Please try again shortly."
    if not categories:
        return "Sorry, our menu is empty right now. Please check back soon."
    session["state"] = AWAITING_CATEGORY
    return _menu_greeting(categories)


def _show_category(session, category):
    items = sheets.get_items_in_category(category)
    if not items:
        return None
    session["current_category"] = category
    session["state"] = AWAITING_ORDER
    session["retries"] = 0
    return _category_items_text(category, items)


def _awaiting_category(session, text, upper):
    categories = session.get("categories") or _load_categories(session)

    # DONE with a non-empty cart jumps to checkout (Section 6).
    if upper == "DONE":
        if session["cart"]:
            session["state"] = AWAITING_FULFILMENT
            return "Choose the delivery option to continue."
        return "Your cart is empty. " + _menu_greeting(categories)

    category = _match_category(text, categories)
    if category is None:
        return ("I did not catch that. Reply with a category number:\n"
                f"{_categories_block(categories)}")
    reply = _show_category(session, category)
    if reply is None:
        return ("That category has no items right now. Pick another:\n"
                f"{_categories_block(categories)}")
    return reply


def _parse_and_add(session, text, phone):
    """Parse free text against the full available menu, add to cart. Returns
    (added_items, error_reply). One of the two is set."""
    try:
        available = sheets.get_available_menu()
    except Exception as exc:
        log.error("Menu load failed during parse: %s", exc)
        return None, "Sorry, our menu is unavailable right now. Please try again shortly."

    result = nlu.parse_order(text, available)
    if result["confidence"] != "high" or not result["items"]:
        return None, None  # caller handles re-prompt / escalation

    _add_to_cart(session["cart"], result["items"])
    return result["items"], None


def _awaiting_order(session, text, phone):
    added, error = _parse_and_add(session, text, phone)
    if error:
        return error

    categories = session.get("categories") or _load_categories(session)

    if added is None:
        session["retries"] += 1
        if session["retries"] >= 2:
            # Escalate to admin and reset the retry counter (Section 6).
            session["retries"] = 0
            notify_admin(
                f"Could not parse an order from {redact_phone(phone)} after "
                f"retries. Customer may need help."
            )
            return ("I am having trouble understanding that order. I have "
                    "flagged it for a team member. You can also reply with a "
                    "category number to start again:\n"
                    f"{_categories_block(categories)}")
        current = session.get("current_category")
        hint = f" from {current}" if current else ""
        return (f"Sorry, I did not catch what you want{hint}. Please tell me "
                "the item and quantity (e.g. '2 jollof rice').")

    session["retries"] = 0
    session["state"] = AWAITING_MORE
    return _added_text(added, session["cart"], categories)


def _awaiting_more(session, text, upper, phone):
    categories = session.get("categories") or _load_categories(session)

    if upper == "DONE":
        session["state"] = AWAITING_FULFILMENT
        return "Choose the delivery option to continue."
    if upper == "MORE":
        session["state"] = AWAITING_CATEGORY
        return "Choose another category."

    # A category pick -> show that category's items.
    category = _match_category(text, categories)
    if category is not None:
        reply = _show_category(session, category)
        if reply is not None:
            return reply

    # Otherwise treat it as a direct order against the full menu (Section 6).
    added, error = _parse_and_add(session, text, phone)
    if error:
        return error
    if added is not None:
        return _added_text(added, session["cart"], categories)

    # Unclear — re-show the hub prompt.
    return ("Pick a category to add more:\n"
            f"{_categories_block(categories)}\n"
            "Or reply DONE to checkout.")


def _awaiting_fulfilment(session, upper):
    if upper not in ("DELIVERY", "PICKUP"):
        return "Please choose Delivery or Pick up to continue."
    session["fulfilment"] = upper.lower()
    session["state"] = AWAITING_CONFIRM
    return _checkout_summary(session["cart"])


def _awaiting_confirm(session, upper, phone):
    if upper != "YES":
        _reset(session)
        return "No problem! Send a message anytime to start a new order."

    cart = session["cart"]
    if not cart:
        _reset(session)
        return "Your cart is empty. Send a message anytime to start a new order."

    total = _cart_total(cart)

    # L-4: never accept a non-positive total.
    if total <= 0:
        _reset(session)
        return ("Your order total came to zero, so there is nothing to pay for. "
                "Send a message anytime to start a new order.")

    # H-4: reject absurdly large totals before creating an order.
    if total > config.MAX_ORDER_TOTAL:
        log.warning("Rejected order over ceiling: total=%s", total)
        notify_admin(f"Order rejected: total {_naira(total)} exceeds the "
                     f"maximum of {_naira(config.MAX_ORDER_TOTAL)}.")
        _reset(session)
        return ("That order total is unusually large and can't be processed "
                "here. Please contact us directly to arrange a large order.")

    # Returning customer: reuse name/email from their last order and skip the
    # name/email prompts entirely. A lookup failure simply falls through to the
    # first-time path so checkout is never blocked.
    prior = None
    try:
        prior = sheets.find_order_by_phone(phone)
    except Exception as exc:
        log.error("Returning-customer lookup failed: %s", exc)
        prior = None
    if prior:
        session["customer_name"] = prior.get("name") or "Customer"
        session["customer_email"] = prior.get("email") or config.BUSINESS_EMAIL
        log.info("Returning customer — reusing stored details")
        return _finalize_order(session, phone)

    # First-time customer: collect name, then email, then finalize.
    session["retries"] = 0
    session["state"] = AWAITING_NAME
    return "What name should we put on your order?"


def _awaiting_name(session, text, phone):
    """Collect the customer's name. Re-prompt once on invalid input; on a second
    invalid reply fall back to 'Customer' and move on — never blocks checkout."""
    name = _valid_name(text)
    if name is None:
        session["retries"] += 1
        if session["retries"] >= 2:
            session["customer_name"] = "Customer"
            session["retries"] = 0
            session["state"] = AWAITING_EMAIL
            return _email_prompt()
        return ("Sorry, I did not catch a valid name. "
                "What name should we put on your order?")
    session["customer_name"] = name
    session["retries"] = 0
    session["state"] = AWAITING_EMAIL
    return _email_prompt()


def _awaiting_email(session, text, phone):
    """Collect the customer's email. SKIP (case-insensitive) or a second invalid
    reply falls back to BUSINESS_EMAIL — never blocks checkout."""
    raw = (text or "").strip()
    if raw.upper() == "SKIP":
        session["customer_email"] = config.BUSINESS_EMAIL
        session["retries"] = 0
        return _finalize_order(session, phone)

    email = _valid_email(raw)
    if email is None:
        session["retries"] += 1
        if session["retries"] >= 2:
            session["customer_email"] = config.BUSINESS_EMAIL
            session["retries"] = 0
            return _finalize_order(session, phone)
        return ("That email does not look right.\n" + _email_prompt())

    session["customer_email"] = email
    session["retries"] = 0
    return _finalize_order(session, phone)


def _finalize_order(session, phone):
    """Write the confirmed order and tell the customer to pay directly.

    The cart and total were already validated in AWAITING_CONFIRM;
    customer_name / customer_email are set on the session before this is called.
    """
    cart = session["cart"]
    total = _cart_total(cart)
    order_ref = _unique_order_ref()

    # Write the PENDING order to Sheets.
    try:
        sheets.append_order(order_ref, phone, session.get("customer_name"),
                            session.get("customer_email"), cart, total)
    except Exception as exc:
        session["state"] = AWAITING_CONFIRM
        log.error("Failed to write order %s: %s", order_ref, exc)
        notify_admin(f"Failed to write order {order_ref} to Sheets: {exc}")
        return ("Sorry, something went wrong placing your order. "
                "Please reply YES again in a moment to retry.")

    session["state"] = AWAITING_PAYMENT
    log.info("Order %s placed for direct payment", order_ref)
    return (
        f"Your order {order_ref} has been received.\n"
        f"Total: {_naira(total)}\n"
        "Please pay directly when your order is delivered or collected.\n"
        f"Pickup address: {config.PICKUP_ADDRESS}"
    )
