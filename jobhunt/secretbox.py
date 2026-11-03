"""Saved email passwords and sign-in tokens are kept encrypted on disk (AES, via Fernet), so a copy of the data
folder alone doesn't reveal them. The key comes from the server's secret (JOBHUNT_SECRET, or data/secret_key)."""
from __future__ import annotations

import base64
import hashlib
import os

PREFIX = "enc:v1:"
FIELDS = (("email", "gmail_app_password"), ("email", "ms_refresh_token"))
_FERNET = None


def _fernet():
    global _FERNET
    if _FERNET is None:
        from cryptography.fernet import Fernet
        secret = os.environ.get("JOBHUNT_SECRET")
        if not secret:
            from .phone import secret_key
            secret = secret_key()
        _FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(("jobhunt-secretbox:" + secret).encode()).digest()))
    return _FERNET


def seal(value: str) -> str:
    if not value or str(value).startswith(PREFIX):
        return value
    return PREFIX + _fernet().encrypt(str(value).encode()).decode()


def unseal(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except Exception:
        return ""                     # the server's secret changed: the person connects their email again


def seal_settings(data: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (data or {}).items()}
    for section, key in FIELDS:
        if isinstance(out.get(section), dict) and out[section].get(key):
            out[section][key] = seal(out[section][key])
    return out


def open_settings(data: dict) -> dict:
    for section, key in FIELDS:
        if isinstance((data or {}).get(section), dict) and data[section].get(key):
            data[section][key] = unseal(data[section][key])
    return data
