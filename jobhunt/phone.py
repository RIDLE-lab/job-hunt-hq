"""Using Job Hunt HQ from your iPhone (or any of your own devices), safely.

How it works: Tailscale (free) joins your PC and your iPhone into a private network that only your devices
can reach. "tailscale serve" then gives the app a private https address such as
https://rashi-pc.tail1234.ts.net – nothing is opened to the internet. On top of that, anyone opening the
app from another device has to enter your PIN.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import subprocess

from .config import DATA_DIR

STATE = DATA_DIR / "phone.json"


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ PIN
def has_pin() -> bool:
    return bool(_load().get("pin_hash"))


def set_pin(pin: str):
    salt = secrets.token_hex(16)
    data = _load()
    data["pin_salt"] = salt
    data["pin_hash"] = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 200_000).hex()
    data["session_version"] = secrets.token_hex(8)       # signs out every phone that used the old PIN
    _save(data)


def check_pin(pin: str) -> bool:
    data = _load()
    if not data.get("pin_hash"):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", (pin or "").encode(), bytes.fromhex(data["pin_salt"]), 200_000).hex()
    return hmac.compare_digest(digest, data["pin_hash"])


def session_version() -> str:
    return _load().get("session_version", "")


def secret_key() -> str:
    """A random key for signing your phone's sign-in cookie, made once and kept in data/."""
    path = DATA_DIR / "secret_key"
    try:
        key = path.read_text(encoding="utf-8").strip()
        if len(key) >= 32:
            return key
    except Exception:
        pass
    key = secrets.token_hex(32)
    path.parent.mkdir(exist_ok=True)
    path.write_text(key, encoding="utf-8")
    return key


# ------------------------------------------------------------------ Tailscale
def _tailscale_exe() -> str | None:
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for p in (r"C:\Program Files\Tailscale\tailscale.exe", r"C:\Program Files (x86)\Tailscale\tailscale.exe"):
        if os.path.isfile(p):
            return p
    return None


def _run(args, timeout=20):
    exe = _tailscale_exe()
    if not exe:
        return None, "Tailscale isn't installed on this PC yet."
    try:
        flags = 0x08000000 if os.name == "nt" else 0          # don't flash a console window on Windows
        out = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, creationflags=flags)
        return out, ""
    except Exception as e:
        return None, str(e)


def status() -> dict:
    """{'installed', 'running', 'name', 'url', 'serving', 'message'}"""
    info = {"installed": bool(_tailscale_exe()), "running": False, "name": "", "url": "", "serving": False,
            "message": ""}
    if not info["installed"]:
        info["message"] = "Tailscale isn't installed on this PC yet."
        return info
    out, err = _run(["status", "--json"])
    if out is None or out.returncode != 0:
        info["message"] = err or (out.stderr.strip() if out else "") or "Tailscale isn't signed in yet."
        return info
    try:
        data = json.loads(out.stdout)
    except ValueError:
        info["message"] = "Couldn't read Tailscale's status."
        return info
    me = data.get("Self") or {}
    info["running"] = data.get("BackendState") == "Running"
    info["name"] = (me.get("DNSName") or "").rstrip(".")
    if info["name"]:
        info["url"] = "https://" + info["name"]
    if not info["running"]:
        info["message"] = "Open Tailscale on this PC and sign in."
    serve, _ = _run(["serve", "status", "--json"])
    if serve is not None and serve.returncode == 0 and serve.stdout.strip() not in ("", "{}", "null"):
        info["serving"] = True
    return info


def start_serving(port: int) -> tuple[bool, str, str]:
    """Publish the app to your own devices only: https://<this-pc>.<your-tailnet>.ts.net → 127.0.0.1:port.
    Returns (ok, message, approval_link). The first time, Tailscale waits for you to switch on "Serve"/HTTPS
    for your account and prints a link: that link is returned (and opened in your browser)."""
    import re
    exe = _tailscale_exe()
    if not exe:
        return False, "Tailscale isn't installed on this PC yet.", ""
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        out = subprocess.run([exe, "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"], capture_output=True,
                             text=True, timeout=15, creationflags=flags)
        text = (out.stdout + "\n" + out.stderr).strip()
        ok = out.returncode == 0
    except subprocess.TimeoutExpired as e:      # waiting for you to approve it on Tailscale's website
        def s(x):
            return x.decode(errors="replace") if isinstance(x, bytes) else (x or "")
        text, ok = (s(e.stdout) + "\n" + s(e.stderr)).strip(), False
    except Exception as e:
        return False, str(e), ""
    link = (re.search(r"https://login\.tailscale\.com/\S+", text) or [""])[0]
    if ok:
        return True, text[-400:], ""
    if link:
        try:
            import webbrowser
            webbrowser.open(link)
        except Exception:
            pass
        return False, "Tailscale needs you to allow sharing once.", link
    return False, text[-400:] or "Tailscale couldn't start sharing the app.", ""


def stop_serving() -> tuple[bool, str]:
    out, err = _run(["serve", "reset"])
    if out is None:
        return False, err
    return out.returncode == 0, (out.stdout + out.stderr).strip()[-300:]
