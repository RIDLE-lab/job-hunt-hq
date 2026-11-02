"""Reads recruitment emails from Gmail and updates applications; adds jobs from LinkedIn/Indeed alerts.

Two ways in:
- your Gmail app password (the same one used for job emails) – simplest, nothing else to set up;
- or a Google Cloud credentials.json (read-only Gmail API, see README).
Either way the app only reads: it never deletes, moves or changes anything, and leaves unread mail unread.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone

from . import db
from .classify import (alert_site, classify, find_application, find_date, is_application_email, parse_alert,
                       parse_application)
from .config import GMAIL_CREDENTIALS, gmail_token

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

KEYWORDS = ('application OR applied OR applying OR interview OR unfortunately OR candidate OR shortlist OR '
            'assessment OR "next steps" OR recruitment OR vacancy OR "your application" OR offer OR role OR position OR '
            '"your cv" OR recruiter OR hiring')
QUERY = ('newer_than:{days}d -in:sent -in:chats ('
         'application OR applied OR applying OR interview OR unfortunately OR candidate OR shortlist OR '
         'assessment OR "next steps" OR recruitment OR vacancy OR "your application" OR offer OR '
         'from:jobalerts-noreply@linkedin.com OR from:jobs-noreply@linkedin.com OR from:indeed.com)')


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    token_file = gmail_token()
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GMAIL_CREDENTIALS.exists():
                raise FileNotFoundError("credentials.json not found – see README, 'Connect Gmail'.")
            flow = InstalledAppFlow.from_client_secrets_file(str(GMAIL_CREDENTIALS), SCOPES)
            creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _body_text(payload: dict) -> str:
    """Plain text of a message, falling back to stripped HTML."""
    plain, html_parts = [], []

    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            html_parts.append(_decode(data))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    if plain:
        return "\n".join(plain)
    from .sources import clean_text
    return clean_text(" ".join(html_parts))


def _header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def api_messages(cfg: dict, seen: set, service=None, query=None, limit=400, oldest_first=False, skip_seen=True,
                 sent=False, total=None):
    """Messages through the Gmail API (credentials.json)."""
    service = service or get_service()
    days = int(cfg.get("gmail", {}).get("lookback_days", 30))
    page_token, ids = None, []
    while True:
        resp = service.users().messages().list(userId="me", q=query or QUERY.format(days=days),
                                               pageToken=page_token, maxResults=100).execute()
        ids += [m["id"] for m in resp.get("messages", [])]
        page_token = resp.get("nextPageToken")
        if not page_token or len(ids) >= limit:
            break
    if oldest_first:
        ids.reverse()
    if total is not None:
        total.append(len(ids))
    for mid in ids:
        if skip_seen and mid in seen:
            continue
        msg = service.users().messages().get(userId="me", id=mid, format="full").execute()
        yield {"id": mid, "subject": _header(msg, "Subject"), "sender": _header(msg, "From"), "sent": sent,
               "to": _header(msg, "To"),
               "body": _body_text(msg.get("payload", {})), "snippet": msg.get("snippet", ""),
               "received": datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, tz=timezone.utc)}


def imap_messages(cfg: dict, seen: set, query=None, limit=400, oldest_first=False, skip_seen=True, sent=False,
                  total=None):
    """Messages over IMAP with your Gmail app password. Uses Gmail's own search, reads without marking as read."""
    import email
    import imaplib
    import re
    from email.policy import default
    from email.utils import parsedate_to_datetime

    from . import mail_providers as mp
    from .notify import settings
    e = settings(cfg)
    days = int(cfg.get("gmail", {}).get("lookback_days", 30))
    prov = mp.provider(cfg)
    if prov != "gmail":
        yield from _plain_imap_messages(cfg, e, prov, seen, query, limit, oldest_first, skip_seen, sent, total, days)
        return
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=40)
    try:
        m.login(e["from"], e["gmail_app_password"])
        box = '"[Gmail]/All Mail"'
        for line in m.list()[1] or []:      # UK accounts may call it "[Google Mail]/All Mail"
            text = line.decode(errors="replace")
            if "\\All" in text:
                box = text[text.rfind(' "') + 1:] if text.rstrip().endswith('"') else text.split()[-1]
                break
        m.select(box, readonly=True)
        query = query or QUERY.format(days=days)
        typ, data = m.search(None, "X-GM-RAW", '"' + query.replace("\\", "\\\\").replace('"', '\\"') + '"')
        nums = (data[0] or b"").split()[-limit:]
        if total is not None:
            total.append(len(nums))
        for num in (nums if oldest_first else reversed(nums)):
            typ, parts = m.fetch(num, "(X-GM-MSGID BODY.PEEK[])")
            head = next((p for p in parts if isinstance(p, tuple)), None)
            if not head:
                continue
            gid = re.search(rb"X-GM-MSGID (\d+)", head[0])
            mid = format(int(gid.group(1)), "x") if gid else "imap-" + num.decode()
            if skip_seen and mid in seen:
                continue
            msg = email.message_from_bytes(head[1], policy=default)
            plain = msg.get_body(preferencelist=("plain",))
            html = msg.get_body(preferencelist=("html",))
            if plain is not None:
                body = plain.get_content()
            else:
                from .sources import clean_text
                body = clean_text(html.get_content()) if html is not None else ""
            try:
                received = parsedate_to_datetime(msg["Date"])
            except Exception:
                received = datetime.now(timezone.utc)
            yield {"id": mid, "subject": str(msg["Subject"] or ""), "sender": str(msg["From"] or ""), "sent": sent,
                   "to": str(msg["To"] or ""),
                   "body": body, "snippet": " ".join(body.split())[:300], "received": received}
    finally:
        try:
            m.logout()
        except Exception:
            pass


JOB_WORDS = re.compile(r"applica|applied|applying|interview|unfortunately|candidate|shortlist|assessment|next steps|"
                       r"recruit|vacanc|offer|role|position|your cv|hiring|job alert|jobs? for you|talent", re.I)
ALERT_SENDERS = re.compile(r"linkedin\.com|indeed\.com|adzuna|totaljobs|reed\.co\.uk|cv-library", re.I)


def _plain_imap_messages(cfg, e, prov, seen, query, limit, oldest_first, skip_seen, sent, total, days):
    """Any other email service over IMAP (Yahoo, iCloud, AOL, Zoho, GMX, Fastmail, your own; Outlook with Microsoft
    sign-in). Read-only: headers first, and only messages that look like job emails are opened."""
    import email
    import hashlib
    import imaplib
    from email.policy import default
    from email.utils import parsedate_to_datetime

    from . import mail_providers as mp
    host = mp.imap_host(cfg)
    if not host:
        raise ValueError("Add your email provider's IMAP server in My settings.")
    m = imaplib.IMAP4_SSL(host, 993, timeout=40)
    try:
        if prov == "outlook":
            token, _ = mp.microsoft_access_token(e)
            m.authenticate("XOAUTH2", lambda _: mp.xoauth2(e["from"], token))
        else:
            m.login(e["from"], e["gmail_app_password"])
        box = "INBOX"
        if sent:
            for line in m.list()[1] or []:
                text = line.decode(errors="replace")
                if "\\Sent" in text:
                    box = text[text.rfind(' "') + 1:] if text.rstrip().endswith('"') else text.split()[-1]
                    break
            else:
                return
        m.select(box, readonly=True)
        start = (datetime(2026, 1, 1) if query and "after:" in query else datetime.now() - timedelta(days=days))
        typ, data = m.search(None, "SINCE", start.strftime("%d-%b-%Y"))
        nums = (data[0] or b"").split()[-limit:]
        if total is not None:
            total.append(len(nums))
        for num in (nums if oldest_first else reversed(nums)):
            typ, parts = m.fetch(num, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID)])")
            head = next((p for p in parts if isinstance(p, tuple)), None)
            if not head:
                continue
            h = email.message_from_bytes(head[1], policy=default)
            mid = "imap-" + hashlib.sha1(str(h["Message-ID"] or (str(h["Date"]) + str(h["Subject"]))).encode()).hexdigest()[:20]
            if skip_seen and mid in seen:
                continue
            subj, frm = str(h["Subject"] or ""), str(h["From"] or "")
            if not sent and not (JOB_WORDS.search(subj) or ALERT_SENDERS.search(frm)):
                continue                       # not a job email: never opened
            typ, parts = m.fetch(num, "(BODY.PEEK[])")
            full = next((p for p in parts if isinstance(p, tuple)), None)
            if not full:
                continue
            msg = email.message_from_bytes(full[1], policy=default)
            plain = msg.get_body(preferencelist=("plain",))
            html = msg.get_body(preferencelist=("html",))
            if plain is not None:
                body = plain.get_content()
            else:
                from .sources import clean_text
                body = clean_text(html.get_content()) if html is not None else ""
            try:
                received = parsedate_to_datetime(msg["Date"])
            except Exception:
                received = datetime.now(timezone.utc)
            yield {"id": mid, "subject": subj, "sender": frm, "sent": sent, "to": str(msg["To"] or ""),
                   "body": body, "snippet": " ".join(body.split())[:300], "received": received}
    finally:
        try:
            m.logout()
        except Exception:
            pass


def method(cfg: dict) -> str | None:
    """Which way the app can read your mail: 'api', 'app_password' or None."""
    from .notify import settings
    if GMAIL_CREDENTIALS.exists():
        return "api"
    from . import mail_providers as mp
    e = settings(cfg)
    prov = mp.provider(cfg)
    if prov == "outlook":
        return "app_password" if e.get("ms_refresh_token") and mp.microsoft_ready() else None
    pw = e["gmail_app_password"]
    if (len(pw) == 16 if prov == "gmail" else len(pw) >= 6) and (prov != "other" or mp.imap_host(cfg)):
        return "app_password"
    return None


HISTORY_START = "2026/01/01"
ALERT_SKIP = ("-from:jobalerts-noreply@linkedin.com -from:jobs-noreply@linkedin.com -from:jobs-listings@linkedin.com "
              "-from:indeed.com -from:jobalert.indeed.com -from:adzuna.co.uk")
INTERVIEWISH = ("interview", "second_stage", "pre_screen", "assessment", "offer")


def _ignored(conn) -> list[dict]:
    import json
    try:
        return json.loads(db.get_meta(conn, "ignored_applications", "[]") or "[]")
    except ValueError:
        return []


def ignore_application(conn, company: str, role: str):
    """You said this wasn't an application: don't add it again from later emails."""
    import json
    items = _ignored(conn)
    items.append({"company": company, "role": role})
    db.set_meta(conn, "ignored_applications", json.dumps(items[-500:]))


_EMPLOYER = {}


def _expand_known(company: str) -> str:
    """Email addresses often use initials: chhca.co.uk → your current employer's full name."""
    if "name" not in _EMPLOYER:
        try:
            from .config import load_config
            _EMPLOYER["name"] = load_config().get("profile", {}).get("current_employer", "") or ""
        except Exception:
            _EMPLOYER["name"] = ""
    emp = _EMPLOYER["name"]
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", emp) if w.lower() not in ("ltd", "limited", "plc", "the", "and", "of"))
    return emp if emp and len(initials) >= 3 and company.replace(" ", "").lower() == initials.lower() else company


def record_application_email(conn, apps: list[dict], *, category: str, subject: str, body: str, sender: str,
                             received: datetime, stats: dict, ignored: list[dict] | None = None) -> int | None:
    """Link an application email to its application – adding the application if it's one the app didn't know
    about – and move its status on. Returns the application id, or None if it isn't about an application."""
    from .classify import same_role
    if not is_application_email(category, subject, body, sender):
        return None
    role, company = parse_application(subject, body, sender)
    company = _expand_known(company)
    app = find_application(subject, body, sender, apps, role, company)
    day = received.astimezone().date().isoformat()
    status = category if category in db.STATUS_LABELS else "applied"
    if not app:
        if not company and role:
            company = "Employer not named in the email"
        if not company:
            return None
        if any(i["company"].lower() == company.lower() and same_role(role, i.get("role", "")) for i in (ignored or [])):
            return None
        fields = {"company": company, "role": role or "Role not named in the emails", "applied_on": day,
                  "status": status, "source": "gmail", "notes": f"Found in Gmail: {subject[:150]}"}
        if status in INTERVIEWISH:
            fields["next_step"] = db.STATUS_LABELS[status] + ": " + subject[:120]
            fields["next_date"] = find_date(body) or find_date(subject)
        fields["id"] = db.add_application(conn, **fields)
        apps.append(fields)
        stats["created"] = stats.get("created", 0) + 1
        return fields["id"]
    updates = {}
    if app.get("source") == "gmail" and (not app.get("applied_on") or day < app["applied_on"]):
        updates["applied_on"] = day                       # the earliest email about it
    if role and (not app.get("role") or app["role"].startswith("Role not named")):
        updates["role"] = role
    # moves forward only – except your own withdrawal, which always stands when it comes later
    if status == "withdrawn" and app.get("status") != "withdrawn" or \
            db.STATUS_RANK.get(status, 0) > db.STATUS_RANK.get(app.get("status"), 0) and app.get("status") != "withdrawn":
        updates["status"] = status
        if status in ("rejected", "withdrawn"):
            updates.update(next_step=None, next_date=None)
        if status in INTERVIEWISH:
            updates["next_step"] = db.STATUS_LABELS[status] + ": " + subject[:120]
            updates["next_date"] = find_date(body) or find_date(subject)
    if updates:
        db.update_application(conn, app["id"], **updates)
        app.update(updates)
        stats["updated"] = stats.get("updated", 0) + 1
    return app["id"]


def tidy_roles(conn):
    """Fix role names saved by older rules: dates read as roles, "Specialistposition"."""
    from .classify import _BAD_ROLE, _clean_role
    for a in conn.execute("SELECT id, role FROM applications WHERE source = 'gmail'").fetchall():
        role = a["role"] or ""
        if role.startswith("Role not named"):
            continue
        new = _clean_role(role)
        if not new or _BAD_ROLE.search(new):
            new = "Role not named in the emails"
        if new != role:
            conn.execute("UPDATE applications SET role = ? WHERE id = ?", (new, a["id"]))


def link_existing(conn, log=print) -> dict:
    """Go back over emails already in the app: re-sort any marked "other" with the newer rules, then link every
    application email to an application (adding any the app didn't know about)."""
    tidy_roles(conn)
    apps = [dict(r) for r in conn.execute("SELECT * FROM applications")]
    ignored = _ignored(conn)
    stats = {"created": 0, "updated": 0}
    rows = conn.execute("SELECT id, received_at, sender, subject, snippet, category FROM events "
                        "WHERE application_id IS NULL AND category NOT IN ('job_alert', 'sent') "
                        "ORDER BY received_at").fetchall()
    for r in rows:
        category = r["category"]
        if category == "other":
            category = classify(r["subject"] or "", r["snippet"] or "", r["sender"] or "")
            if category != "other":
                conn.execute("UPDATE events SET category = ? WHERE id = ?", (category, r["id"]))
        try:
            received = datetime.fromisoformat(r["received_at"])
        except (TypeError, ValueError):
            received = datetime.now(timezone.utc)
        app_id = record_application_email(conn, apps, category=category, subject=r["subject"] or "",
                                          body=r["snippet"] or "", sender=r["sender"] or "", received=received,
                                          stats=stats, ignored=ignored)
        if app_id:
            conn.execute("UPDATE events SET application_id = ? WHERE id = ?", (app_id, r["id"]))
    if stats["created"] or stats["updated"]:
        log(f"Emails: {stats['created']} applications added, {stats['updated']} updated")
    return stats


REBUILD_VERSION = "3"


def needs_rebuild(conn) -> bool:
    return db.get_meta(conn, "email_rebuild") != REBUILD_VERSION


def reset_for_rebuild(conn):
    """Start the email side again with the current rules: forget the emails (not job alerts), remove the
    applications that were only found in emails, and put applications you made in Job Hunt HQ back to
    "Submitted" so the emails can move them on again. Manual entries and "Not an application" choices are kept."""
    conn.execute("UPDATE events SET application_id = NULL")
    conn.execute("DELETE FROM applications WHERE source = 'gmail'")
    conn.execute("UPDATE applications SET status = 'applied' WHERE COALESCE(source, '') != 'manual' AND status IN "
                 "('acknowledged', 'pre_screen', 'assessment', 'interview', 'second_stage', 'offer', 'rejected')")
    conn.execute("DELETE FROM events WHERE category != 'job_alert'")
    db.set_meta(conn, "email_rebuild", REBUILD_VERSION)


def sync(conn, cfg: dict, service=None, log=print, messages=None, history=False, progress=None) -> dict:
    """Fetch new emails, record events, link them to applications (adding new ones), import LinkedIn/Indeed alerts.
    history=True reads everything since 1 January (received and sent), oldest first, and skips old job alerts."""
    from .refresh import add_jobs  # local import to avoid a cycle

    seen = {r["gmail_id"] for r in conn.execute("SELECT gmail_id FROM events")}
    apps = [dict(r) for r in conn.execute("SELECT * FROM applications")]
    ignored = _ignored(conn)
    stats = {"emails": 0, "updated": 0, "created": 0, "alert_jobs": 0}
    progress = progress if progress is not None else {}
    if messages is None:
        how = "api" if service else method(cfg)
        if not how:
            raise FileNotFoundError("Add your Gmail app password (email: gmail_app_password) or credentials.json.")
        fetch = (lambda **kw: api_messages(cfg, seen, service, **kw)) if how == "api" else \
                (lambda **kw: imap_messages(cfg, seen, **kw))
        if history:
            totals = []
            inbox_q = f"after:{HISTORY_START} -in:sent -in:chats {ALERT_SKIP} ({KEYWORDS})"
            sent_q = f"in:sent after:{HISTORY_START} ({KEYWORDS})"

            def both():
                yield from fetch(query=inbox_q, limit=8000, oldest_first=True, total=totals)
                yield from fetch(query=sent_q, limit=4000, oldest_first=True, sent=True, total=totals)
            messages = both()
            progress["totals"] = totals
        else:
            messages = fetch()

    for item in messages:
        mid, subject, sender, body, received = item["id"], item["subject"], item["sender"], item["body"], item["received"]
        progress["done"] = progress.get("done", 0) + 1
        if mid in seen:
            continue
        seen.add(mid)
        stats["emails"] += 1
        app_id = None
        if item.get("sent"):
            category = "sent"
            to = item.get("to", "")
            role, company = parse_application(subject, body, to)
            app = find_application(subject, body, to, apps, role, company)
            app_id = app["id"] if app else None
            sender = "You → " + (to or "")
        else:
            category = classify(subject, body, sender)
            if category == "job_alert":
                site = alert_site(sender)
                if not history and site and cfg.get("gmail", {}).get("read_job_alerts", True):
                    found = parse_alert(body, site)
                    jobs = [dict(j, source=site, description="", salary_min=None, salary_max=None,
                                 salary_text="", posted=received.date().isoformat(), closes=None, remote=0)
                            for j in found]
                    stats["alert_jobs"] += add_jobs(conn, cfg, jobs)
            elif category != "other":
                app_id = record_application_email(conn, apps, category=category, subject=subject, body=body,
                                                  sender=sender, received=received, stats=stats, ignored=ignored)
        keep = category != "other"     # emails that aren't about your job hunt: remember only that they were checked
        conn.execute("INSERT OR IGNORE INTO events (gmail_id, application_id, received_at, sender, subject, "
                     "snippet, category, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (mid, app_id, received.astimezone().isoformat(timespec="minutes"), sender if keep else "",
                      subject if keep else "", db.tidy_snippet(item.get("snippet") or "")[:300] if keep else "",
                      category, db.now()))
        if stats["emails"] % 25 == 0:
            conn.commit()
        progress.update(created=stats["created"], updated=stats["updated"], emails=stats["emails"])
    if not history:
        db.set_meta(conn, "last_gmail_sync", db.now())
    log(f"Gmail: {stats['emails']} new emails, {stats['created']} applications added, {stats['updated']} updated, "
        f"{stats['alert_jobs']} jobs from LinkedIn/Indeed alerts")
    return stats
