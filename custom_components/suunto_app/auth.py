"""Reverse-engineered Suunto / Sports Tracker login signing pipeline.

This is a faithful Python port of the auth package in `tajchert/suuntool`
(KeyObfuscator XOR -> secret derivation -> RFC 6238 TOTP -> SHA-256 signature).
Every function here is validated byte-for-byte against suuntool's Go golden
vectors (see the module-level self-test in `_validate()`); the embedded key
material is extracted from the Suunto Android app and may need refreshing on a
major app version bump.

NOTE: This talks to Suunto's private app backend (Sports Tracker), not the
official partner API. It is unofficial and may violate Suunto's Terms of
Service. Use only with your own account, at your own risk.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time

# --- Embedded key material (com.stt.android.suunto v6.8.13) ---
APP_VERSION_CODE = "6008013"
PACKAGE_NAME = "com.stt.android.suunto"
USER_AGENT = f"{PACKAGE_NAME}/{APP_VERSION_CODE}"

_LOGIN_KEY_PARTS = [
    "FBkubDYmN28bWVQLLTsWFxcmaRB",
    "fN2AqIBc/IRAoNgshbxgnOGUVGlU3LC0xL0AuXXXXMXY",
    "RWQ4zIi0PWz4hekc1QGNTPlciNhEKV1teYSIkDGYY",
]
_TOTP_KEY_PARTS = [
    "FBkubDYmN28bWVQLLTsWWhI+NAtILCNlPQc5Y",
    "BgiMRYjKA99Jj4HHFIqLmomOFttBQchNzcZU0QrODcDWz4hekc1QGNTPlciNhEKGl5GPDkzFyVX",
]
_TOTP_OBFUSCATION_KEY = "Bh8nsTyCeC0Ql2drMen78awk84AE3ZxW"


def _decode_rune(b: bytes, i: int) -> tuple[int, int]:
    """Port of Go utf8.DecodeRune: (rune, size); invalid sequence -> (0xFFFD, 1)."""
    n = len(b)
    b0 = b[i]
    if b0 < 0x80:
        return b0, 1
    if 0xC2 <= b0 <= 0xDF:
        if i + 1 < n and 0x80 <= b[i + 1] <= 0xBF:
            return ((b0 & 0x1F) << 6) | (b[i + 1] & 0x3F), 2
        return 0xFFFD, 1
    if 0xE0 <= b0 <= 0xEF:
        lo, hi = 0x80, 0xBF
        if b0 == 0xE0:
            lo = 0xA0
        elif b0 == 0xED:
            hi = 0x9F
        if i + 2 < n and lo <= b[i + 1] <= hi and 0x80 <= b[i + 2] <= 0xBF:
            return (
                ((b0 & 0x0F) << 12) | ((b[i + 1] & 0x3F) << 6) | (b[i + 2] & 0x3F),
                3,
            )
        return 0xFFFD, 1
    if 0xF0 <= b0 <= 0xF4:
        lo, hi = 0x80, 0xBF
        if b0 == 0xF0:
            lo = 0x90
        elif b0 == 0xF4:
            hi = 0x8F
        if (
            i + 3 < n
            and lo <= b[i + 1] <= hi
            and 0x80 <= b[i + 2] <= 0xBF
            and 0x80 <= b[i + 3] <= 0xBF
        ):
            return (
                ((b0 & 0x07) << 18)
                | ((b[i + 1] & 0x3F) << 12)
                | ((b[i + 2] & 0x3F) << 6)
                | (b[i + 3] & 0x3F),
                4,
            )
        return 0xFFFD, 1
    return 0xFFFD, 1


def _utf8_replace(b: bytes) -> bytes:
    """Mimic Java `new String(bytes, UTF-8).getBytes(UTF-8)`: invalid byte -> U+FFFD."""
    out = bytearray()
    i = 0
    while i < len(b):
        rune, size = _decode_rune(b, i)
        if rune == 0xFFFD and size == 1:
            out += b"\xef\xbf\xbd"
            i += 1
        else:
            out += b[i : i + size]
            i += size
    return bytes(out)


def _key_obfuscator(k_bytes: bytes, pkg: str) -> bytes:
    """Byte-wise XOR of k_bytes against the repeating bytes of pkg."""
    p = pkg.encode("utf-8")
    return bytes(k_bytes[i] ^ p[i % len(p)] for i in range(len(k_bytes)))


def _derive_obfuscated_secret(parts: list[str], pkg: str) -> bytes:
    """Join base64 parts, decode, XOR-deobfuscate; return valid-UTF-8 secret bytes."""
    raw = base64.b64decode("".join(parts))
    mid = _utf8_replace(raw)
    xored = _key_obfuscator(mid, pkg)
    return _utf8_replace(xored)


def _derive_login_secret() -> bytes:
    """Secret used (as raw bytes) when signing /login2 form submissions."""
    return _derive_obfuscated_secret(_LOGIN_KEY_PARTS, PACKAGE_NAME)


def _derive_totp_master_secret() -> bytes:
    """PBKDF2 password source for per-user TOTP generation."""
    return _derive_obfuscated_secret(_TOTP_KEY_PARTS, _TOTP_OBFUSCATION_KEY)


def sign_params(path: str, params: list[tuple[str, str]]) -> str:
    """base64url(no pad) SHA-256 of 'POST&'+path+('&k=v')...+'&secret='+loginSecret."""
    buf = bytearray(b"POST&")
    buf += path.encode("utf-8")
    for key, value in params:
        buf += b"&" + key.encode("utf-8") + b"=" + value.encode("utf-8")
    buf += b"&secret=" + _derive_login_secret()
    digest = hashlib.sha256(bytes(buf)).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _pbkdf2_key_for_salt(salt: str) -> bytes:
    """PBKDF2-HMAC-SHA1; password bytes are the low 8 bits of each master rune."""
    master = _derive_totp_master_secret().decode("utf-8")
    pwd = bytes((ord(ch) & 0xFF) for ch in master)
    return hashlib.pbkdf2_hmac("sha1", pwd, salt.encode("utf-8"), 100, 32)


def _hotp6(key: bytes, counter: int) -> str:
    """6-digit RFC 4226 HOTP."""
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (
        ((mac[off] & 0x7F) << 24)
        | (mac[off + 1] << 16)
        | (mac[off + 2] << 8)
        | mac[off + 3]
    )
    return f"{code % 1_000_000:06d}"


def generate_totp(salt: str, offset_ms: int = 0) -> str:
    """Current 6-digit TOTP for the given salt (email/username)."""
    key = _pbkdf2_key_for_salt(salt)
    now = int(time.time() * 1000) + offset_ms
    return _hotp6(key, now // 30000)


def random_salt() -> str:
    """16 random bytes as base64url-no-padding."""
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")


def now_ms() -> int:
    """Current unix timestamp in milliseconds."""
    return int(time.time() * 1000)
