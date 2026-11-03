"""Emails you the new jobs each refresh finds, best match first, with your match percentage.

Sends through your own email account (with the app password you gave it), only to your own inbox. Every email
says why you're getting it and has a one-click link to stop them.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from html import escape

from .matcher import fit_label

STOP_LINK = None          # set by the app: user id → the one-click "stop these emails" link

FIT_COLOURS = {"Strong fit": "#1e7e46", "Good fit": "#2f6fb0", "Stretch": "#a86a00", "Weak fit": "#8a8f98"}


def settings(cfg: dict) -> dict:
    e = dict(cfg.get("email") or {})
    me = (cfg.get("profile") or {}).get("email", "")
    e.setdefault("enabled", False)
    e["to"] = e.get("to") or me
    e["from"] = e.get("from") or me
    e["gmail_app_password"] = str(e.get("gmail_app_password") or "").replace(" ", "")
    e["min_score"] = int(e.get("min_score", 50) or 0)
    e["max_jobs"] = int(e.get("max_jobs", 20) or 20)
    return e


def ready(cfg: dict) -> tuple[bool, str]:
    e = settings(cfg)
    if not e["enabled"]:
        return False, "Email alerts are off (email: enabled: false in config.yaml)."
    if len(e["gmail_app_password"]) != 16:
        return False, "Add your 16-letter Gmail app password to config.yaml (email: gmail_app_password)."
    if "@" not in e["to"] or "@" not in e["from"]:
        return False, "Add your email address to config.yaml (email: to / from)."
    return True, ""


def send(cfg: dict, subject: str, html: str, text: str, stop: str = ""):
    e = settings(cfg)
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, f"Job Hunt HQ <{e['from']}>", e["to"]
    if stop:                                     # mail apps show their own "Unsubscribe" button for this
        msg["List-Unsubscribe"] = f"<{stop}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    from . import mail_providers as mp
    if mp.provider(cfg) == "outlook":
        raise RuntimeError("Sending job emails through Outlook isn't available yet.")
    host = mp.smtp_host(cfg) or "smtp.gmail.com"
    with smtplib.SMTP_SSL(host, 465, timeout=30) as s:
        s.login(e["from"], e["gmail_app_password"])
        s.send_message(msg)


def base_url(port: int = 5055) -> str:
    import os
    from .config import HOSTED
    return os.environ.get("JOBHUNT_URL", "").rstrip("/") or ("https://www.jhhq.co.uk" if HOSTED else f"http://127.0.0.1:{port}")


def build(jobs: list[dict], port: int = 5055, stop: str = "") -> tuple[str, str, str]:
    """(subject, html, text) for a list of jobs, best first."""
    top = jobs[0]
    subject = (f"{len(jobs)} new job{'s' if len(jobs) != 1 else ''} for you – top match {top['score']}% "
               f"({top['title']}, {top['company']})")
    rows, lines = [], []
    for j in jobs:
        fit = fit_label(j["score"])
        colour = FIT_COLOURS.get(fit, "#8a8f98")
        details = " · ".join(x for x in (j.get("company"), j.get("location"), j.get("salary_text"), j.get("source")) if x)
        why = (j.get("score_reasons") or "").split(" · ")[:3]
        app_link = f"{base_url(port)}/job/{j['id']}"
        rows.append(
            f'<tr><td style="padding:12px 10px;vertical-align:top;width:64px">'
            f'<div style="font:700 20px/1 Segoe UI,Arial,sans-serif;color:{colour}">{j["score"]}%</div>'
            f'<div style="font:11px Segoe UI,Arial,sans-serif;color:{colour};margin-top:3px">{escape(fit)}</div></td>'
            f'<td style="padding:12px 10px;border-bottom:1px solid #e6e8ec;font:14px/1.45 Segoe UI,Arial,sans-serif;color:#18202e">'
            f'<a href="{escape(j.get("url") or app_link)}" style="color:#1f3a5f;font-weight:700;text-decoration:none">{escape(j["title"])}</a><br>'
            f'<span style="color:#5b6577">{escape(details)}</span><br>'
            f'<span style="color:#5b6577;font-size:12.5px">{escape(" · ".join(why))}</span><br>'
            f'<a href="{app_link}" style="font-size:12.5px;color:#a86a00">Open in Job Hunt HQ</a></td></tr>')
        lines.append(f"{j['score']}% {fit} – {j['title']}, {details}\n  {j.get('url') or app_link}")
    why = ('You get this email because "Email me the best new jobs after each refresh" is on in your Job Hunt HQ settings.')
    foot_html = (f'<p style="color:#5b6577;font-size:12px;margin:18px 0 0;border-top:1px solid #e6e8ec;padding-top:12px">{escape(why)} '
                 + (f'<a href="{escape(stop)}" style="color:#5b6577">Stop these emails</a>' if stop else
                    'To stop them, untick it in My settings.') + '</p>')
    html = (f'<div style="max-width:640px;margin:0 auto;font-family:Segoe UI,Arial,sans-serif">'
            f'<h2 style="font:600 20px Segoe UI,Arial,sans-serif;color:#1f3a5f;margin:0 0 4px">New jobs matching your CV</h2>'
            f'<p style="color:#5b6577;font-size:13px;margin:0 0 12px">Best match first.</p>'
            f'<table style="border-collapse:collapse;width:100%">{"".join(rows)}</table>{foot_html}</div>')
    text = ("New jobs matching your CV (best first):\n\n" + "\n\n".join(lines) + "\n\n" + why +
            (f"\nStop these emails: {stop}" if stop else " To stop them, untick it in My settings."))
    return subject, html, text


def send_new_jobs(conn, cfg: dict, since: str, log=print) -> int:
    """Email the jobs a refresh added (created at or after `since`) that score at least min_score."""
    ok, why = ready(cfg)
    if not ok:
        return 0
    e = settings(cfg)
    jobs = [dict(r) for r in conn.execute(
        "SELECT * FROM jobs WHERE created_at >= ? AND status IN ('new', 'shortlisted', 'prepared') AND score >= ? "
        "ORDER BY score DESC, created_at DESC LIMIT ?", (since, e["min_score"], e["max_jobs"]))]
    if not jobs:
        return 0
    port = int((cfg.get("app") or {}).get("port", 5055))
    stop = ""
    try:
        from .config import current_user_id
        stop = STOP_LINK(current_user_id()) if STOP_LINK and current_user_id() is not None else ""
    except Exception:
        stop = ""
    try:
        send(cfg, *build(jobs, port, stop), stop=stop)
        log(f"Emailed you {len(jobs)} new job{'s' if len(jobs) != 1 else ''}")
        return len(jobs)
    except Exception as ex:
        log(f"Couldn't send the job email: {ex}")
        return 0
