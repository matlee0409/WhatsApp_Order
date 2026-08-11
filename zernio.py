"""Zernio WhatsApp connection flow."""

from urllib.parse import urlparse

import hashlib
import hmac
import json
import secrets
import threading

import requests

import redis_store

_REDIS_ERRORS = (redis_store.RedisUnavailableError, OSError)
try:
    import redis
    _REDIS_ERRORS = _REDIS_ERRORS + (redis.RedisError,)
except ImportError:
    pass

import config
from db import session_scope
from logger import get_logger
from models import RestaurantSetting

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


def _saved_profile_id() -> str:
    with session_scope() as db_session:
        setting = db_session.query(RestaurantSetting).filter_by(key="zernio_profile_id").first()
        return setting.value if setting else ""


def save_profile_id(profile_id: str) -> None:
    global _profile_id
    if not profile_id:
        return
    with session_scope() as db_session:
        setting = db_session.query(RestaurantSetting).filter_by(key="zernio_profile_id").first()
        if setting is None:
            db_session.add(RestaurantSetting(key="zernio_profile_id", value=profile_id))
        else:
            setting.value = profile_id
    _profile_id = profile_id


def get_or_create_profile() -> str:
    """Find this deployment's Zernio profile or create it once."""
    global _profile_id
    if _profile_id:
        return _profile_id
    _profile_id = _saved_profile_id()
    if _profile_id:
        return _profile_id

    profile_name = config.ZERNIO_PROFILE_NAME or config.BUSINESS_NAME
    response = requests.get(_api_url("/v1/profiles"), headers=_zernio_headers(), timeout=15)
    response.raise_for_status()
    payload = response.json()
    profiles = payload.get("profiles") or payload.get("data", {}).get("profiles") or []
    for profile in profiles:
        if profile.get("name") == profile_name:
            profile_id = profile.get("_id") or profile.get("id")
            if profile_id:
                save_profile_id(profile_id)
                return profile_id

    response = requests.post(
        _api_url("/v1/profiles"),
        headers={**_zernio_headers(), "Content-Type": "application/json"},
        json={"name": profile_name, "description": "WhatsApp ordering profile"},
        timeout=15,
    )
    response.raise_for_status()
    profile_id = _profile_from_response(response.json())
    if not profile_id:
        raise RuntimeError("Zernio did not return the created profile ID")
    save_profile_id(profile_id)
    return profile_id


def get_catalog_id() -> str:
    """Return the Zernio-managed profile ID used by WhatsApp catalog messages."""
    return get_or_create_profile()


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
    value = {"account_id": account_id, "conversation_id": conversation_id}
    try:
        redis_store.get_redis().set(
            f"whatsapp:conversation:{phone}", json.dumps(value)
        )
    except _REDIS_ERRORS as exc:
        if config.is_production():
            raise
        log.warning("Redis unavailable in development; using in-memory mapping: %s", exc)
    with _conversations_lock:
        _conversations[phone] = (account_id, conversation_id)


def send_message_to_phone(phone: str, message: str) -> bool:
    conversation = None
    try:
        raw = redis_store.get_redis().get(f"whatsapp:conversation:{phone}")
        if raw:
            value = json.loads(raw)
            conversation = (value["account_id"], value["conversation_id"])
    except _REDIS_ERRORS + (TypeError, ValueError, KeyError) as exc:
        if config.is_production():
            raise
        log.warning("Redis unavailable in development; using in-memory mapping: %s", exc)
    if conversation is None and not config.is_production():
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
