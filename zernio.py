"""Zernio WhatsApp connection flow."""

from urllib.parse import urlparse

import hashlib
import hmac
import secrets
import threading

import requests

import config
from logger import get_logger

log = get_logger("zernio")
_profile_id = None
_conversations = {}
_conversations_lock = threading.Lock()


def _api_url(path: str) -> str:
    return f"{config.ZERNIO_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"


def _zernio_headers():
    return {
        "Authorization": f"Bearer {config.require('ZERNIO_API_KEY')}",
        "Accept": "application/json",
    }


def _profile_from_response(payload):
    profile = payload.get("profile") or payload.get("data", {}).get("profile") or {}
    return profile.get("_id") or profile.get("id")


def get_or_create_profile() -> str:
    """Find this deployment's Zernio profile or create it once."""
    global _profile_id
    if _profile_id:
        return _profile_id
    if config.ZERNIO_PROFILE_ID:
        _profile_id = config.ZERNIO_PROFILE_ID
        return _profile_id

    profile_name = config.ZERNIO_PROFILE_NAME or config.BUSINESS_NAME
    response = requests.get(_api_url("/v1/profiles"), headers=_zernio_headers(), timeout=15)
    response.raise_for_status()
    payload = response.json()
    profiles = payload.get("profiles") or payload.get("data", {}).get("profiles") or []
    for profile in profiles:
        if profile.get("name") == profile_name:
            _profile_id = profile.get("_id") or profile.get("id")
            if _profile_id:
                return _profile_id

    response = requests.post(
        _api_url("/v1/profiles"),
        headers={**_zernio_headers(), "Content-Type": "application/json"},
        json={"name": profile_name, "description": "WhatsApp ordering profile"},
        timeout=15,
    )
    response.raise_for_status()
    _profile_id = _profile_from_response(response.json())
    if not _profile_id:
        raise RuntimeError("Zernio did not return the created profile ID")
    return _profile_id


def get_whatsapp_auth_url(redirect_uri: str | None = None) -> tuple[str, str]:
    """Request the hosted Meta signup URL from Zernio."""
    api_key = config.require("ZERNIO_API_KEY")
    profile_id = get_or_create_profile()
    redirect_uri = redirect_uri or config.require("ZERNIO_REDIRECT_URI")
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


def remember_conversation(phone: str, account_id: str, conversation_id: str) -> None:
    with _conversations_lock:
        _conversations[phone] = (account_id, conversation_id)


def send_message_to_phone(phone: str, message: str) -> bool:
    with _conversations_lock:
        conversation = _conversations.get(phone)
    if not conversation:
        log.error("No Zernio conversation found for %s", phone)
        return False
    account_id, conversation_id = conversation
    return send_message(account_id, conversation_id, message)


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
