"""
Firebase Cloud Messaging (FCM) HTTP v1 sender.

Used by Phase 3 mobile push notifications:
  - new important email (Gmail poller)
  - upcoming calendar event (10-min lead time)
  - Claude Code task completion

Config (config.yaml):

    apis:
      fcm:
        service_account_path: "data/fcm-service-account.json"
        project_id: "your-firebase-project-id"

If the file or project_id is missing, push() logs a single warning and returns
False — the rest of Jarvis keeps working untouched.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Iterable

import requests
from loguru import logger

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_FCM_URL_TMPL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

_warned_no_config = False
_token_cache: dict = {"token": "", "expires_at": 0.0}
_token_lock = threading.Lock()


def _config() -> dict:
    """Pull FCM config from the dashboard's loaded config singleton."""
    from ui.dashboard import _config as dash_config
    return dash_config.get("apis", {}).get("fcm", {})


def is_configured() -> bool:
    cfg = _config()
    path = cfg.get("service_account_path", "")
    project_id = cfg.get("project_id", "")
    if not path or not project_id:
        return False
    return Path(path).is_file()


def _get_access_token() -> str | None:
    """Mint (or reuse cached) OAuth2 access token from the service-account JWT."""
    global _token_cache
    with _token_lock:
        if _token_cache["token"] and _token_cache["expires_at"] > time.time() + 60:
            return _token_cache["token"]

        cfg = _config()
        sa_path = Path(cfg.get("service_account_path", ""))
        if not sa_path.is_file():
            return None

        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as GoogleRequest
        except ImportError:
            logger.error(
                "FCM push: google-auth not installed. "
                "Run: pip install google-auth requests"
            )
            return None

        try:
            creds = service_account.Credentials.from_service_account_file(
                str(sa_path), scopes=[_FCM_SCOPE]
            )
            creds.refresh(GoogleRequest())
            _token_cache["token"] = creds.token
            _token_cache["expires_at"] = (
                creds.expiry.timestamp() if creds.expiry else time.time() + 3000
            )
            return creds.token
        except Exception as exc:
            logger.error(f"FCM token refresh failed: {exc}")
            return None


def push(title: str, body: str, *, data: dict | None = None,
         tokens: Iterable[str] | None = None,
         actions: list[dict] | None = None) -> int:
    """Send a notification to one or many device tokens. Returns number sent.

    `actions` is an optional list of {id, label} dicts. They'll be embedded
    in the data payload as a JSON-encoded string under the key 'actions',
    which the Flutter side decodes and renders as Android action buttons.
    """
    global _warned_no_config

    if not is_configured():
        if not _warned_no_config:
            logger.info(
                "FCM not configured (apis.fcm.service_account_path / project_id). "
                "Mobile push notifications disabled."
            )
            _warned_no_config = True
        return 0

    if tokens is None:
        from ui.db_managers import device_db
        tokens = [d["token"] for d in device_db.list_active()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return 0

    access = _get_access_token()
    if not access:
        return 0

    project_id = _config()["project_id"]
    url = _FCM_URL_TMPL.format(project_id=project_id)
    headers = {
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    payload_data = {k: str(v) for k, v in (data or {}).items()}
    if actions:
        # FCM data values must be strings — encode the action list as JSON
        clean_actions = [
            {"id": str(a.get("id", "")), "label": str(a.get("label", ""))}
            for a in actions if a.get("id") and a.get("label")
        ]
        if clean_actions:
            payload_data["actions"] = json.dumps(clean_actions)

    sent = 0
    invalid: list[str] = []
    for token in tokens:
        message = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": payload_data,
                "android": {"priority": "high"},
                "apns": {"headers": {"apns-priority": "10"}},
            }
        }
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(message), timeout=10)
            if resp.status_code == 200:
                sent += 1
            elif resp.status_code in (400, 404):
                # UNREGISTERED / INVALID_ARGUMENT — drop the token
                invalid.append(token)
                logger.warning(f"FCM push rejected token (will drop): {resp.text[:120]}")
            else:
                logger.warning(f"FCM push HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            logger.error(f"FCM push to {token[:12]}…: {exc}")

    if invalid:
        try:
            from ui.db_managers import device_db
            for t in invalid:
                device_db.unregister(t)
        except Exception:
            pass

    if sent:
        logger.info(f"FCM push '{title}' → {sent}/{len(tokens)} devices")
    return sent


def push_async(*args, **kwargs) -> None:
    """Fire-and-forget wrapper — never blocks the caller's thread."""
    threading.Thread(target=push, args=args, kwargs=kwargs, daemon=True).start()
