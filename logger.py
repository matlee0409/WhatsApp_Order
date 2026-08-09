"""Rotating file logger with PII redaction (Section 12.7).

Logs are written to logs/order_bot.log with rotation. Phone numbers are
redacted to the form +234***890 and customer names are never logged — trace
orders by Order Reference instead. Use `redact_phone()` before putting any
phone number into a log line.
"""

import logging
import os
import re
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "order_bot.log")

# Matches a run of 7+ digits (optionally prefixed with +), i.e. a phone number.
_PHONE_RE = re.compile(r"\+?\d{7,}")


def redact_phone(phone) -> str:
    """Redact a phone number for safe logging: +2348012345890 -> +234***890.

    Keeps a short prefix and suffix for traceability, masks the middle. Returns
    a placeholder for empty input. Never returns the full number.
    """
    if not phone:
        return "<no-phone>"
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) < 7:
        return "***"
    prefix = digits[:3]
    suffix = digits[-3:]
    return f"+{prefix}***{suffix}"


class _RedactionFilter(logging.Filter):
    """Defensive: mask any raw phone-like number that slips into a message."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _PHONE_RE.sub(
                lambda m: redact_phone(m.group(0)), record.msg
            )
        return True


def get_logger(name: str = "order_bot") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )

    # Vercel functions run from a read-only deployment filesystem. Runtime
    # logs belong on stdout/stderr there, where Vercel captures them. Keep the
    # rotating file handler only for traditional/local deployments.
    if not os.environ.get("VERCEL"):
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(_RedactionFilter())
        logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    stream_handler.addFilter(_RedactionFilter())

    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger
