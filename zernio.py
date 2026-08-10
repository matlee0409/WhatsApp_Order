"""Zernio WhatsApp connection flow."""

from urllib.parse import urlparse

import hashlib
import hmac
import secrets

import requests

import config
from logger import get_logger

log = get_logger("zernio")


def _api_url(path: str) -> str:
    return f"{config.ZERNIO_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def get_whatsapp_auth_url() -> tuple[str, str]:
    """Request the hosted Meta signup URL and state from Zernio."""
    api_key = config.require("ZERNIO_API_KEY")
    profile_id = config.require("ZERNIO_PROFILE_ID")
    redirect_uri = config.require("ZERNIO_REDIRECT_URI")
    response = requests.get(
        _api_url("/v1/connect/whatsapp"),
        params={"profileId": profile_id, "redirect_url": redirect_uri},
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload)
    auth_url = data.get("authUrl")
    parsed = urlparse(auth_url or "")
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("Zernio returned an invalid authorization URL")
    return auth_url, data.get("state") or secrets.token_urlsafe(32)


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    if not config.ZERNIO_WEBHOOK_SECRET or not signature:
        return False
    digest = hmac.new(
        config.ZERNIO_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    supplied = signature.removeprefix("sha256=")
    return hmac.compare_digest(digest, supplied)


def send_message(account_id: str, conversation_id: str, message: str = "", interactive: dict | None = None) -> bool:
    """Send a text or interactive message through a Zernio conversation."""
    payload = {"accountId": account_id}
    if message:
        payload["message"] = message
    if interactive:
        payload["interactive"] = interactive
    response = requests.post(
        _api_url(f"/v1/inbox/conversations/{conversation_id}/messages"),
        headers={
            "Authorization": f"Bearer {config.require('ZERNIO_API_KEY')}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return True


def callback_connection(args: dict) -> dict:
    """Extract the non-sensitive connection details returned by Zernio."""
    if args.get("connected") != "whatsapp":
        raise ValueError("WhatsApp connection was not completed")
    account_id = (args.get("accountId") or "").strip()
    if not account_id:
        raise ValueError("Zernio did not return a connected account")
    return {
        "account_id": account_id,
        "profile_id": (args.get("profileId") or "").strip(),
        "phone": (args.get("username") or "").strip(),
    }
