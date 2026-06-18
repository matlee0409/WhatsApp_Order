"""Google Sheets access layer — Menu reads + Orders CRUD (Section 5).

The Sheets client is created lazily on first use so this module imports cleanly
even with no credentials present. Credentials path comes from
config.GOOGLE_CREDENTIALS_FILE and the spreadsheet id from
config.GOOGLE_SPREADSHEET_ID (Section 12.8).

APOSTROPHE STRIPPING (Section 11, MANDATORY from day one): Google Sheets
prepends an apostrophe to values starting with + or = to stop formula parsing,
and gspread returns it as part of the string. Every string value read from a
sheet passes through `_clean()` before it is compared or returned. Numeric
columns (Price, Total Amount) are parsed separately and never carry an
apostrophe, so _clean is not applied to them.

Write safety (Section 12.6): Orders is append-only for new orders; status and
field updates target a single row matched by exact Order Reference; the Menu
sheet is never written by the bot.
"""

from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

import config
from logger import get_logger

log = get_logger("sheets")

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Orders columns (Section 5), 1-indexed for gspread cell updates.
COL_ORDER_REF = 1       # A
COL_PHONE = 2           # B
COL_NAME = 3            # C
COL_ITEMS = 4           # D
COL_TOTAL = 5           # E
COL_STATUS = 6          # F
COL_PAYMENT_REF = 7     # G
COL_CREATED_AT = 8      # H
COL_PAID_AT = 9         # I
COL_READY_AT = 10       # J
COL_READY_NOTIFIED = 11  # K
COL_EMAIL = 12          # L

ORDERS_HEADER = [
    "Order Reference", "Customer Phone", "Customer Name", "Items",
    "Total Amount", "Status", "Payment Reference", "Created At",
    "Paid At", "Ready At", "Ready Notified", "Email",
]

_client = None
_spreadsheet = None


# ─── Helpers ────────────────────────────────────────────────────────────────

def _clean(value):
    """Strip whitespace and a leading Sheets-inserted apostrophe (Section 11).

    Applied to every string value read from a sheet. Non-strings pass through
    unchanged.
    """
    if not isinstance(value, str):
        return value
    return value.strip().lstrip("'")


def _to_number(value):
    """Parse a Naira amount from a sheet cell into a float. Tolerates commas
    and currency symbols. Returns 0.0 on empty/unparseable input."""
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().lstrip("'").replace(",", "").replace("₦", "")
    cleaned = cleaned.replace("N", "").strip()
    try:
        parsed = float(cleaned)
    except ValueError:
        return 0.0
    # L-4: clamp negatives to 0 so a negative menu price/total cannot flow through.
    return parsed if parsed > 0 else 0.0


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ─── Connection (lazy) ──────────────────────────────────────────────────────

def _get_spreadsheet():
    """Open the configured spreadsheet, connecting on first call.

    Raises a clear error if credentials or the spreadsheet id are missing —
    only when Sheets is actually used, never at import.
    """
    global _client, _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet

    creds_file = config.require("GOOGLE_CREDENTIALS_FILE")
    spreadsheet_id = config.require("GOOGLE_SPREADSHEET_ID")

    creds = Credentials.from_service_account_file(creds_file, scopes=_SCOPES)
    _client = gspread.authorize(creds)
    _spreadsheet = _client.open_by_key(spreadsheet_id)
    return _spreadsheet


def _menu_ws():
    return _get_spreadsheet().worksheet(config.MENU_SHEET)


def _orders_ws():
    return _get_spreadsheet().worksheet(config.ORDERS_SHEET)


# ─── Menu reads ─────────────────────────────────────────────────────────────

def get_menu():
    """Return all menu rows as dicts. Reads live each call so owner edits take
    effect with no restart (Section 5).

    Each item: {category, name, description, price (float), available (bool)}.
    Apostrophe stripping is applied to all string fields.
    """
    ws = _menu_ws()
    rows = ws.get_all_values()
    items = []
    # Row 0 is the header.
    for row in rows[1:]:
        # Pad short rows so indexing is safe.
        row = (row + [""] * 5)[:5]
        category = _clean(row[0])
        name = _clean(row[1])
        if not name:
            continue
        items.append({
            "category": category,
            "name": name,
            "description": _clean(row[2]),
            "price": _to_number(row[3]),
            "available": _clean(row[4]).lower() == "yes",
        })
    return items


def get_available_menu():
    """Menu items with Available == Yes only — what the bot ever offers/parses."""
    return [item for item in get_menu() if item["available"]]


def get_categories():
    """Ordered, de-duplicated list of categories that have available items."""
    seen = []
    for item in get_available_menu():
        if item["category"] and item["category"] not in seen:
            seen.append(item["category"])
    return seen


def get_items_in_category(category):
    """Available items in a category, matched case-insensitively."""
    target = (category or "").strip().lower()
    return [
        item for item in get_available_menu()
        if item["category"].lower() == target
    ]


# ─── Orders CRUD ────────────────────────────────────────────────────────────

def _order_records():
    """All order rows as (row_number, dict). Row numbers are 1-indexed sheet
    rows (header is row 1, first data row is 2)."""
    ws = _orders_ws()
    rows = ws.get_all_values()
    records = []
    for idx, row in enumerate(rows[1:], start=2):
        row = (row + [""] * 12)[:12]
        records.append((idx, {
            "order_ref": _clean(row[0]),
            "phone": _clean(row[1]),
            "name": _clean(row[2]),
            "items": _clean(row[3]),
            "total": _to_number(row[4]),
            "status": _clean(row[5]),
            "payment_ref": _clean(row[6]),
            "created_at": _clean(row[7]),
            "paid_at": _clean(row[8]),
            "ready_at": _clean(row[9]),
            "ready_notified": _clean(row[10]),
            "email": _clean(row[11]),
        }))
    return records


def order_ref_exists(order_ref):
    """True if an order with this reference already exists (collision check,
    Section 10)."""
    target = _clean(order_ref)
    return any(rec["order_ref"] == target for _, rec in _order_records())


def find_order_by_ref(order_ref):
    """Return (row_number, record) for the order, or (None, None)."""
    target = _clean(order_ref)
    for row_num, rec in _order_records():
        if rec["order_ref"] == target:
            return row_num, rec
    return None, None


def find_order_by_phone(phone):
    """Return the most recent order record for this phone number, or None.

    Used for returning-customer recognition at checkout. Orders are append-only,
    so the most recent match is the one with the latest Created At (the ISO
    timestamps sort chronologically as strings). Apostrophe stripping is applied
    via `_clean()` on both the stored phone (in `_order_records`) and the target.
    """
    target = _clean(phone)
    if not target:
        return None
    best = None
    for _, rec in _order_records():
        if rec["phone"] == target:
            if best is None or rec["created_at"] >= best["created_at"]:
                best = rec
    return best


def find_order_by_payment_ref(payment_ref):
    """Return (row_number, record) matched by Paystack payment reference."""
    target = _clean(payment_ref)
    if not target:
        return None, None
    for row_num, rec in _order_records():
        if rec["payment_ref"] == target:
            return row_num, rec
    return None, None


def payment_ref_processed(payment_ref):
    """Idempotency (Section 7.3/12.3): True if this payment reference is already
    recorded against a non-Pending order."""
    _, rec = find_order_by_payment_ref(payment_ref)
    if rec is None:
        return False
    return rec["status"].lower() in ("paid", "ready", "collected")


def append_order(order_ref, phone, name, email, cart, total):
    """Append a new PENDING order (Section 6 checkout / 12.6 append-only).

    The Items column holds a human-readable summary (one line per item,
    "{qty}x {name} — ₦{line_total}"). Ready Notified = No; Email goes in
    column L.
    """
    ws = _orders_ws()
    items_text = "\n".join(
        f"{item['quantity']}x {item['name']} — ₦{item['line_total']:,.0f}"
        for item in cart
    )
    new_row = [
        order_ref,
        phone,
        name or "",
        items_text,
        total,
        "Pending",
        "",            # Payment Reference
        _now_iso(),    # Created At
        "",            # Paid At
        "",            # Ready At
        "No",          # Ready Notified
        email or "",   # Email (L)
    ]
    ws.append_row(new_row, value_input_option="RAW")
    log.info("Appended PENDING order %s", order_ref)
    return order_ref


def mark_order_paid(order_ref, payment_ref):
    """Set Status -> Paid, record Payment Reference and Paid At. Targets the
    single row matched by exact Order Reference (Section 12.6)."""
    row_num, rec = find_order_by_ref(order_ref)
    if row_num is None:
        log.warning("mark_order_paid: order %s not found", order_ref)
        return False
    ws = _orders_ws()
    ws.update_cell(row_num, COL_STATUS, "Paid")
    ws.update_cell(row_num, COL_PAYMENT_REF, payment_ref)
    ws.update_cell(row_num, COL_PAID_AT, _now_iso())
    log.info("Order %s marked Paid", order_ref)
    return True


def get_ready_orders():
    """Orders with Status == Ready AND Ready Notified != Yes (Section 8)."""
    out = []
    for row_num, rec in _order_records():
        if (rec["status"].lower() == "ready"
                and rec["ready_notified"].lower() != "yes"):
            out.append((row_num, rec))
    return out


def set_ready_notified(order_ref, ready_at=None):
    """Set Ready Notified = Yes for the order. Called by reminders.py only after
    a successful pickup notification (Section 12.6).

    When `ready_at` is provided it is also written to the Ready At column (J).
    Ready At is written first and Ready Notified last, so a partial failure
    leaves the order un-notified and it safely retries on the next run.
    """
    row_num, rec = find_order_by_ref(order_ref)
    if row_num is None:
        log.warning("set_ready_notified: order %s not found", order_ref)
        return False
    ws = _orders_ws()
    if ready_at:
        ws.update_cell(row_num, COL_READY_AT, ready_at)
    ws.update_cell(row_num, COL_READY_NOTIFIED, "Yes")
    log.info("Order %s Ready Notified set to Yes", order_ref)
    return True


def get_order_status(order_ref):
    """Return the status string for an order, or None if not found
    (ORDER ORD-REF self-serve, Section 1C)."""
    _, rec = find_order_by_ref(order_ref)
    return rec["status"] if rec else None
