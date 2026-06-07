"""Async client for Suunto's private Sports Tracker backend.

Login (signed /login2 + TOTP) is a one-shot exchange: the caller passes the
password once, gets back a session key, and the password is never stored. The
long-lived client holds only that revocable session key. Faithful to
`tajchert/suuntool`. Unofficial; see auth.py for the ToS caveat.
"""

from __future__ import annotations

import gzip
import json
import logging
import urllib.parse
from typing import Any

import aiohttp
from aiohttp import ClientError

from . import auth
from .const import API_BASE, REQUEST_TIMEOUT, TIMELINE_BASE

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)


class SuuntoAppError(Exception):
    """Base error."""


class SuuntoAppAuthError(SuuntoAppError):
    """Login rejected or session invalid (caller should re-authenticate)."""


async def async_login(
    session: aiohttp.ClientSession, email: str, password: str
) -> dict[str, str]:
    """Exchange email+password for a session key. The password is not retained.

    Returns ``{"session_key", "username", "user_key"}``. Raises
    ``SuuntoAppAuthError`` on bad credentials.
    """
    totp = auth.generate_totp(email, 0)
    signature = auth.sign_params(
        "login2", [("l", email), ("p", password), ("totp", totp)]
    )
    form = {
        "l": email,
        "p": password,
        "totp": totp,
        "timestamp": str(auth.now_ms()),
        "salt": auth.random_salt(),
        "signature": signature,
    }
    headers = {
        "User-Agent": auth.USER_AGENT,
        "Accept-Language": "en",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "x-login-email-verification-enabled": "true",
    }
    try:
        async with session.post(
            f"{API_BASE}login2",
            data=urllib.parse.urlencode(form),
            headers=headers,
            timeout=_TIMEOUT,
        ) as resp:
            body = await resp.read()
            if resp.status in (401, 403):
                raise SuuntoAppAuthError(
                    "Login rejected — check email/password (account 2FA can also "
                    "block this)."
                )
            resp.raise_for_status()
            data = json.loads(body)
    except SuuntoAppAuthError:
        raise
    except (ClientError, TimeoutError) as err:
        raise SuuntoAppError(f"Cannot reach Sports Tracker: {err}") from err
    except (ValueError, json.JSONDecodeError) as err:
        raise SuuntoAppError(f"Bad login response: {err}") from err

    session_key = data.get("sessionkey")
    if not session_key:
        raise SuuntoAppAuthError("Login succeeded but no session key was returned.")
    return {
        "session_key": session_key,
        "username": data.get("username") or "",
        "user_key": data.get("userKey") or "",
    }


class SportsTrackerClient:
    """Reads workouts + wellness using a stored session key (no password)."""

    def __init__(
        self, session: aiohttp.ClientSession, session_key: str
    ) -> None:
        """Initialize with an aiohttp session and a previously obtained key."""
        self._session = session
        self._session_key = session_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": auth.USER_AGENT,
            "Accept-Language": "en",
            "STTAuthorization": self._session_key,
        }

    async def _request(self, base: str, path: str) -> bytes:
        """GET a path under ``base``; map an invalid session to an auth error."""
        url = f"{base}{path.lstrip('/')}"
        try:
            async with self._session.get(
                url, headers=self._headers, timeout=_TIMEOUT
            ) as resp:
                if resp.status in (401, 403):
                    # Session expired/revoked. Without a stored password we
                    # cannot silently re-login; surface for the reauth flow.
                    raise SuuntoAppAuthError(
                        f"Session no longer valid (HTTP {resp.status})."
                    )
                resp.raise_for_status()
                return await resp.read()
        except SuuntoAppAuthError:
            raise
        except (ClientError, TimeoutError) as err:
            raise SuuntoAppError(f"Request to {url} failed: {err}") from err

    # --- Workouts (ASKO envelope) ---

    async def async_get_workouts(
        self, since_ms: int, page_size: int = 100, max_pages: int = 8
    ) -> list[dict[str, Any]]:
        """Return workouts newest-first, paginating to cover the whole window."""
        items: list[dict[str, Any]] = []
        offset = 0
        for _ in range(max_pages):
            path = f"workouts?since={since_ms}&limit={page_size}&offset={offset}"
            body = await self._request(API_BASE, path)
            try:
                envelope = json.loads(body)
            except (ValueError, json.JSONDecodeError) as err:
                raise SuuntoAppError(f"Bad workouts response: {err}") from err
            if isinstance(envelope, dict) and envelope.get("error"):
                raise SuuntoAppError(f"Server error: {envelope['error']}")
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            page = payload if isinstance(payload, list) else []
            items.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        items.sort(key=lambda w: w.get("startTime") or 0, reverse=True)
        return items

    async def async_get_stats(self, username: str) -> dict[str, Any]:
        """Return lifetime aggregate workout stats for ``username``."""
        body = await self._request(API_BASE, f"workouts/{username}/stats")
        try:
            envelope = json.loads(body)
        except (ValueError, json.JSONDecodeError) as err:
            raise SuuntoAppError(f"Bad stats response: {err}") from err
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        return payload if isinstance(payload, dict) else {}

    # --- 24/7 wellness (gzipped NDJSON) ---

    async def async_get_wellness(
        self, stream: str, since_ms: int
    ) -> list[dict[str, Any]]:
        """Return parsed NDJSON records from a timeline wellness stream.

        ``stream`` is one of: sleep, activity, recovery, sleepstages.
        """
        body = await self._request(TIMELINE_BASE, f"v1/{stream}/export?since={since_ms}")
        # The 247 service gzips unconditionally, often without a header.
        if body[:2] == b"\x1f\x8b":
            try:
                body = gzip.decompress(body)
            except OSError as err:
                raise SuuntoAppError(f"Failed to gunzip {stream}: {err}") from err
        records: list[dict[str, Any]] = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                _LOGGER.debug("Skipping unparseable %s NDJSON line", stream)
                continue
            if isinstance(obj, dict):
                records.append(obj)
        return records
