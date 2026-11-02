"""Tells the owner (by email to the contact address, info@jhhq.co.uk) when the website sees something that may break
the Acceptable use rules: someone guessing passwords, someone using a stolen or made-up assistant key, an assistant
file being used from lots of different places (shared), bulk automated applications, a used invite link being tried
again, or a person reporting misuse. Every alert is also kept in a log the owner sees on the People page, so nothing is
lost if email isn't set up yet.

Email goes out through the info@ mailbox's own SMTP server. Set on the server (never in the code):
  JOBHUNT_SMTP_HOST      e.g. the outgoing server your email provider gives you
  JOBHUNT_SMTP_PORT      465 (SSL, default) or 587 (STARTTLS)
  JOBHUNT_SMTP_USER      the mailbox, e.g. info@jhhq.co.uk  (defaults to JOBHUNT_CONTACT)
  JOBHUNT_SMTP_PASSWORD  that mailbox's password
  JOBHUNT_ALERT_TO       where alerts go (defaults to JOBHUNT_CONTACT)
"""
from __future__ import annotations

import json
import os
import smtplib
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from email.message import EmailMessage

from .config import DATA_DIR

LOG = DATA_DIR / "security_alerts.jsonl"
_LOCK = threading.Lock()
_EVENTS: dict[str, list[float]] = defaultdict(list)     # recent events, per kind + who
_LAST_SENT: dict[str, float] = {}                        # one email per problem per few hours
_SEEN: dict[str, dict[str, float]] = defaultdict(dict)   # assistant key -> {network: last seen}
QUIET_HOURS = 6
DAILY_EMAIL_CAP = 25

RULES = {   # kind: (how many, in how many minutes)
    "failed_login": (8, 15),
    "bad_token": (10, 60),
    "applied": (40, 60),
    "fill": (80, 60),
}


def _to() -> str:
    return os.environ.get("JOBHUNT_ALERT_TO") or os.environ.get("JOBHUNT_CONTACT", "")


def email_ready() -> bool:
    return bool(os.environ.get("JOBHUNT_SMTP_HOST") and os.environ.get("JOBHUNT_SMTP_PASSWORD") and "@" in _to())


def recent(limit: int = 50) -> list[dict]:
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    except FileNotFoundError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def _send(subject: str, body: str):
    host = os.environ.get("JOBHUNT_SMTP_HOST", "")
    port = int(os.environ.get("JOBHUNT_SMTP_PORT", "465") or 465)
    user = os.environ.get("JOBHUNT_SMTP_USER") or os.environ.get("JOBHUNT_CONTACT", "")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"Job Hunt HQ alerts <{user}>", _to()
    msg.set_content(body)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as s:
                s.login(user, os.environ["JOBHUNT_SMTP_PASSWORD"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls()
                s.login(user, os.environ["JOBHUNT_SMTP_PASSWORD"])
                s.send_message(msg)
    except Exception as ex:                       # never let an alert break the page someone is using
        _write({"at": _now(), "kind": "email_failed", "title": "Couldn't send an alert email", "detail": str(ex)[:300]})


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


KEEP_DAYS = 90


def _prune():
    """Security records are deleted after 90 days (see the Privacy notice)."""
    try:
        cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
        keep = [line for line in LOG.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("at", "") >= cutoff]
        LOG.write_text("".join(line + "\n" for line in keep), encoding="utf-8")
    except (OSError, ValueError):
        pass


def _write(entry: dict):
    _prune()
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def raise_alert(kind: str, title: str, detail: str, key: str = "", email: bool = True) -> bool:
    """Record an alert and email it (at most once per problem every few hours). True if an email was sent."""
    key = f"{kind}:{key}"
    with _LOCK:
        now = time.time()
        if now - _LAST_SENT.get(key, 0) < QUIET_HOURS * 3600:
            return False
        _LAST_SENT[key] = now
        today = [t for k, t in _LAST_SENT.items() if now - t < 86400]
    _write({"at": _now(), "kind": kind, "title": title, "detail": detail})
    if not (email and email_ready()) or len(today) > DAILY_EMAIL_CAP:
        return False
    body = (f"{title}\n\n{detail}\n\nTime: {_now()}\n\n"
            "This is an automatic alert from Job Hunt HQ. Nothing has been blocked beyond the website's usual limits – "
            "check the People page, and switch the account off there if you need to.\n"
            "These alerts may be wrong (for example someone on a train changing networks), so look before acting.")
    threading.Thread(target=_send, args=(f"[Job Hunt HQ] {title}", body), daemon=True).start()
    return True


def note(kind: str, who: str, title: str, detail: str) -> bool:
    """Count an event; alert when it happens too often (see RULES)."""
    many, minutes = RULES[kind]
    k = f"{kind}:{who}"
    with _LOCK:
        now = time.time()
        _EVENTS[k] = [t for t in _EVENTS[k] if now - t < minutes * 60] + [now]
        hits = len(_EVENTS[k])
    if hits >= many:
        return raise_alert(kind, title, detail.format(n=hits, minutes=minutes), key=who)
    return False


def network(ip: str) -> str:
    """Roughly where a request comes from (the first three parts of the address), so a phone hopping between
    nearby addresses isn't counted as lots of places."""
    ip = (ip or "").split(",")[0].strip()
    return ".".join(ip.split(".")[:3]) if "." in ip else ip[:19]


def assistant_used(user_id: int, username: str, ip: str, places: int = 5) -> bool:
    """The assistant file is personal. If one person's file is used from lots of different networks in a day, it may
    have been shared."""
    net = network(ip)
    with _LOCK:
        now = time.time()
        seen = {n: t for n, t in _SEEN[str(user_id)].items() if now - t < 86400}
        seen[net] = now
        _SEEN[str(user_id)] = seen
        count = len(seen)
    if count >= places:
        return raise_alert("shared_assistant", f"{username}'s browser assistant may have been shared",
                           f"The assistant file for {username} was used from {count} different networks in the last "
                           "24 hours. It may have been given to someone else. On the People page you can give them a new assistant key "
                           "(the shared copy stops working) or switch the account off.",
                           key=str(user_id))
    return False
