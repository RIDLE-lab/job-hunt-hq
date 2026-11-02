"""Which email service someone uses, and how to reach it. Job Hunt HQ reads job emails over IMAP (read-only) with an
app password the person makes in their own email account; Outlook.com/Hotmail need Microsoft's own sign-in instead
(Microsoft switched off app passwords for personal accounts in 2024)."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request

# key: (name, IMAP server, SMTP server, where to make an app password, the domains it covers)
PROVIDERS = {
    "gmail": ("Gmail", "imap.gmail.com", "smtp.gmail.com", "https://myaccount.google.com/apppasswords",
              ("gmail.com", "googlemail.com")),
    "outlook": ("Outlook / Hotmail", "outlook.office365.com", "smtp-mail.outlook.com", "",
                ("outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "live.co.uk", "msn.com")),
    "yahoo": ("Yahoo Mail", "imap.mail.yahoo.com", "smtp.mail.yahoo.com",
              "https://login.yahoo.com/myaccount/security/app-password", ("yahoo.com", "yahoo.co.uk", "ymail.com")),
    "icloud": ("iCloud Mail", "imap.mail.me.com", "smtp.mail.me.com", "https://account.apple.com/account/manage",
               ("icloud.com", "me.com", "mac.com")),
    "aol": ("AOL Mail", "imap.aol.com", "smtp.aol.com", "https://login.aol.com/account/security", ("aol.com", "aol.co.uk")),
    "zoho": ("Zoho Mail", "imap.zoho.eu", "smtp.zoho.eu", "https://accounts.zoho.eu/home#security/app_password",
             ("zoho.com", "zohomail.eu", "zohomail.com")),
    "gmx": ("GMX", "imap.gmx.com", "mail.gmx.com", "", ("gmx.com", "gmx.co.uk", "gmx.de", "gmx.net")),
    "fastmail": ("Fastmail", "imap.fastmail.com", "smtp.fastmail.com", "https://app.fastmail.com/settings/security/apps",
                 ("fastmail.com", "fastmail.fm")),
    "other": ("Another provider", "", "", "", ()),
}


def guess(address: str) -> str:
    domain = (address or "").rsplit("@", 1)[-1].lower().strip()
    return next((k for k, p in PROVIDERS.items() if domain in p[4]), "gmail" if not domain else "other")


def provider(cfg: dict) -> str:
    p = (cfg.get("email") or {}).get("provider")      # people connected before other services existed use Gmail
    return p if p in PROVIDERS else "gmail"


def name(key: str) -> str:
    return PROVIDERS.get(key, PROVIDERS["gmail"])[0]


def imap_host(cfg: dict) -> str:
    p = provider(cfg)
    return ((cfg.get("email") or {}).get("imap_host") or "").strip() if p == "other" else PROVIDERS[p][1]


def smtp_host(cfg: dict) -> str:
    p = provider(cfg)
    return ((cfg.get("email") or {}).get("smtp_host") or "").strip() if p == "other" else PROVIDERS[p][2]


# ------------------------------------------------------------------ Outlook / Hotmail: Microsoft sign-in (OAuth)
MS_AUTH = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
MS_SCOPE = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All"


def microsoft_ready() -> bool:
    """Outlook needs an app registered with Microsoft (free); its ID and secret go in the server's settings."""
    return bool(os.environ.get("JOBHUNT_MS_CLIENT_ID") and os.environ.get("JOBHUNT_MS_CLIENT_SECRET"))


def microsoft_sign_in_url(redirect_uri: str, state: str) -> str:
    q = {"client_id": os.environ["JOBHUNT_MS_CLIENT_ID"], "response_type": "code", "redirect_uri": redirect_uri,
         "response_mode": "query", "scope": MS_SCOPE, "state": state, "prompt": "select_account"}
    return f"{MS_AUTH}/authorize?" + urllib.parse.urlencode(q)


def _token_request(data: dict) -> dict:
    data = {**data, "client_id": os.environ["JOBHUNT_MS_CLIENT_ID"],
            "client_secret": os.environ["JOBHUNT_MS_CLIENT_SECRET"], "scope": MS_SCOPE}
    req = urllib.request.Request(f"{MS_AUTH}/token", data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def microsoft_exchange(code: str, redirect_uri: str) -> dict:
    t = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})
    return {"refresh_token": t.get("refresh_token", ""), "access_token": t.get("access_token", ""),
            "expires_at": time.time() + int(t.get("expires_in", 0)) - 60}


def microsoft_access_token(e: dict) -> tuple[str, str]:
    """A fresh access token from the saved refresh token (and the refresh token to keep, which Microsoft may renew)."""
    t = _token_request({"grant_type": "refresh_token", "refresh_token": e.get("ms_refresh_token", "")})
    return t.get("access_token", ""), t.get("refresh_token") or e.get("ms_refresh_token", "")


def xoauth2(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def b64(s: bytes) -> str:
    return base64.b64encode(s).decode()
