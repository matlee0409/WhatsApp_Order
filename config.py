"""Central configuration for the WhatsApp Order Bot.

All credentials and business-specific values come from environment variables
(loaded from a local .env file in development). This module NEVER raises on
import when values are missing — modules read what they need and validate at
call time, so the bot can be imported and unit-checked without a populated
.env. Use `require(name)` at the point of use to fail loud when a credential
is actually needed.

Security: no secrets are hard-coded here. Section 12.8 — the credentials.json
path is taken from GOOGLE_CREDENTIALS_FILE, never embedded.
"""

import os

from dotenv import load_dotenv

from logger import get_logger

log = get_logger("config")

# Load .env if present. Silent no-op when the file does not exist yet.
load_dotenv()


def _get(name: str, default=None):
    """Read an environment variable, treating empty strings as unset."""
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


# ─── Paystack ──────────────────────────────────────────────────────────────
PAYSTACK_SECRET_KEY = _get("PAYSTACK_SECRET_KEY")
PAYSTACK_WEBHOOK_SECRET = _get("PAYSTACK_WEBHOOK_SECRET")

# ─── Google Sheets ─────────────────────────────────────────────────────────
GOOGLE_SPREADSHEET_ID = _get("GOOGLE_SPREADSHEET_ID")
GOOGLE_CREDENTIALS_FILE = _get("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# ─── Zernio WhatsApp connection ────────────────────────────────────────────
ZERNIO_API_BASE_URL = _get("ZERNIO_API_BASE_URL", "https://zernio.com/api")
ZERNIO_API_KEY = _get("ZERNIO_API_KEY")
ZERNIO_PROFILE_ID = _get("ZERNIO_PROFILE_ID")
ZERNIO_PROFILE_NAME = _get("ZERNIO_PROFILE_NAME")
ZERNIO_REDIRECT_URI = _get("ZERNIO_REDIRECT_URI")
ZERNIO_WEBHOOK_SECRET = _get("ZERNIO_WEBHOOK_SECRET")

# ─── Telegram (OUTBOUND owner notifications only) ──────────────────────────
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_CHAT_ID = _get("TELEGRAM_ADMIN_CHAT_ID")

# ─── Anthropic (Claude — order parsing only) ───────────────────────────────
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# ─── Brevo (optional email receipts) ───────────────────────────────────────
BREVO_API_KEY = _get("BREVO_API_KEY")
BREVO_SENDER_EMAIL = _get("BREVO_SENDER_EMAIL")
BREVO_SENDER_NAME = _get("BREVO_SENDER_NAME")

# ─── App ───────────────────────────────────────────────────────────────────
FLASK_ENV = _get("FLASK_ENV", "production")
PORT = int(_get("PORT", "5003"))
PICKUP_ADDRESS = _get("PICKUP_ADDRESS", "")
BUSINESS_NAME = _get("BUSINESS_NAME", "Your Business")
# Fallback email used when a customer skips the email step at checkout.
BUSINESS_EMAIL = _get("BUSINESS_EMAIL", "")

# Dashboard access. Production requires explicit secrets; development uses a
# preview-only fallback so the UI can be evaluated without local setup.
DASHBOARD_PASSWORD = _get("DASHBOARD_PASSWORD")
FLASK_SECRET_KEY = _get("FLASK_SECRET_KEY")

# Sanity ceiling on a single order total in Naira (H-4). Orders above this are
# rejected before a payment link is generated. Configurable via env.
MAX_ORDER_TOTAL = float(_get("MAX_ORDER_TOTAL", "1000000"))

# Brevo email receipts are optional — enabled only when fully configured.
EMAIL_ENABLED = bool(BREVO_API_KEY and BREVO_SENDER_EMAIL)

# Sheet tab names (Section 5).
MENU_SHEET = "Menu"
ORDERS_SHEET = "Orders"


def is_production() -> bool:
    return FLASK_ENV == "production"


def check_production_safety() -> None:
    """Fail loud at startup (C-3): a Paystack TEST key (sk_test_) accepts test
    cards, so running one in production would let fake payments fulfil orders.
    Log a fatal error and exit rather than start in that state.
    """
    if is_production() and (PAYSTACK_SECRET_KEY or "").startswith("sk_test_"):
        log.critical(
            "FATAL: PAYSTACK_SECRET_KEY is a TEST key (sk_test_) while "
            "FLASK_ENV=production. Refusing to start — use a live key."
        )
        raise SystemExit(1)


def require(name: str):
    """Return the named config value or raise if it is unset.

    Call this at the point a credential is actually used so the failure is
    loud and specific (Section 0.7 — fail safe, fail loud).
    """
    value = globals().get(name)
    if value is None or value == "":
        raise RuntimeError(
            f"Missing required configuration: {name}. "
            f"Set it in your .env file (see .env.example)."
        )
    return value
