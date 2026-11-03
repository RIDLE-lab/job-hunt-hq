"""Job Hunt HQ – local dashboard. Start with run.bat (Windows) or: python app.py"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import webbrowser
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, abort, flash, has_request_context, redirect, render_template, request, send_file, session, url_for

from jobhunt import db, notify
from jobhunt.config import (DATA_DIR, GMAIL_CREDENTIALS, HOSTED, access_token, as_user, current_user_id, cv_file,
                            gmail_token, load_config, set_user, user_dir)
from jobhunt.fetch_page import canonical_url, fetch_job
from jobhunt.letters import (form_message, letter_pdf, safe_filename, save_docx, short_answers,
                             write_letter)
from jobhunt.matcher import fit_label, score_job
from jobhunt.refresh import cv_text, run_refresh
from jobhunt.seed import seed_if_empty
from jobhunt.sources import manual_job, parse_posted

app = Flask(__name__)
from jobhunt import phone   # noqa: E402  (using the app from your iPhone)
app.secret_key = os.environ.get("JOBHUNT_SECRET") or phone.secret_key()
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True, PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

# ------------------------------------------------------------------ accounts and signing in
from jobhunt import accounts  # noqa: E402
from jobhunt import alerts  # noqa: E402
from jobhunt import occupations  # noqa: E402
from jobhunt import countries, geo, i18n  # noqa: E402

OCCUPATIONS_JSON = occupations.as_json()

# Pages anyone may open without signing in.
OPEN_ENDPOINTS = {"email_stop", "login", "static", "manifest", "favicon", "legal", "first_account", "join", "reset_password", "privacy", "set_language",
                  "cookie_choice",
                  "tour"}
# The browser buttons and the robot's file links carry each person's private token instead of a sign-in.
TOKEN_ENDPOINTS = {"bridge_page", "api_bridge", "file_cv", "file_letter", "api_assistant"}
SETUP_ENDPOINTS = {"welcome", "logout", "static", "manifest", "cv_upload", "cv_builder", "feedback_page", "privacy", "legal",
                   "cookie_choice",
                   "set_language", "api_place",
                   "account_page", "account_export"}
# On the website (not your PC) there's no screen for the robot's browser and no Word to open – those pages are off,
# and "Fill this application" (the browser button) does the filling instead.
PC_ONLY_ENDPOINTS = {"robot_start", "robot_link", "robot_page", "robot_api", "open_saved", "setup_phone"}
if HOSTED:
    app.config.update(SESSION_COOKIE_SECURE=True)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def from_this_pc() -> bool:
    """True only for requests made on the PC itself – not through Tailscale or the local network."""
    proxied = request.headers.get("X-Forwarded-For") or request.headers.get("Tailscale-User-Login") or \
        request.headers.get("Forwarded")
    return request.remote_addr in ("127.0.0.1", "::1") and not proxied and not HOSTED


def safe_next(default="/"):
    nxt = request.args.get("next") or request.form.get("next") or default
    ok = nxt.startswith("/") and not nxt.startswith(("//", "/\\")) and "\\" not in nxt and not any(ord(ch) < 32 for ch in nxt)
    return nxt if ok else default


def client_ip() -> str:
    """The visitor's address. On the website ProxyFix takes it from Render's own proxy hop, so a visitor can't fake it
    with their own X-Forwarded-For header (which would dodge the sign-in limits)."""
    return (request.remote_addr or "").strip()


@app.before_request
def sign_in_required():
    from flask import g, session
    g.user = None
    ep = request.endpoint
    if ep in ("static", "manifest", "favicon"):
        return None
    if HOSTED and ep in PC_ONLY_ENDPOINTS:
        if ep == "robot_page":
            flash("Apply for me runs on your own PC. On the website, use the “Fill this application” button – see Setup.")
            return redirect(url_for("setup"))
        abort(404)
    if ep in TOKEN_ENDPOINTS:
        data = request.get_json(silent=True) if request.is_json else None
        token = str(request.args.get("token") or (data or {}).get("token") or "")
        if not accounts.any_users():            # before accounts: the original single token
            import hmac
            if not token or not hmac.compare_digest(token, access_token()):
                abort(403)
            return None
        uid = accounts.user_for_token(token)
        if not uid:
            if token:
                alerts.note("bad_token", alerts.network(client_ip()), "Someone is trying assistant keys that don't exist",
                            f"{{n}} requests in {{minutes}} minutes from {client_ip()} used a browser-assistant key "
                            "that doesn't belong to anyone. Someone may be guessing keys or testing the website's security.")
            abort(403)
        # the assistant and Fill button talk to us from the browser extension or this site's own pages – never from
        # another website's scripts – and at most a couple of requests a second per person
        origin = request.headers.get("Origin", "")
        if origin and not re.match(r"(chrome|moz|safari-web)-extension://", origin) and \
                origin.rstrip("/") != request.host_url.rstrip("/") and ep in ("api_assistant",):
            abort(403)
        now_min = int(time.time() // 60)
        hits = API_HITS.setdefault(uid, [now_min, 0])
        if hits[0] != now_min:
            hits[:] = [now_min, 0]
        hits[1] += 1
        if hits[1] > 150:
            abort(429)
        g.ctx = set_user(uid)
        g.user = accounts.get(uid)
        if ep == "api_assistant" and g.user:
            alerts.assistant_used(uid, g.user["username"], client_ip())
        return None
    if not accounts.any_users():                # first run: the owner makes their account
        if ep == "first_account":
            return None
        return redirect(url_for("first_account"))
    u = accounts.get(session.get("uid"))
    if u and u["active"] and session.get("sv") == u["session_version"]:
        g.ctx = set_user(u["id"])
        g.user = u
        if not u["setup_done"] and ep not in SETUP_ENDPOINTS:
            return redirect(url_for("welcome"))
        return None
    session.pop("uid", None)
    if ep in OPEN_ENDPOINTS:
        return None
    if request.path.startswith("/api/"):
        abort(401)
    if request.path == "/" and request.method == "GET" and accounts.any_users():
        return redirect(url_for("tour"))        # new visitors see what Job Hunt HQ does first
    return redirect(url_for("login", next=request.full_path.rstrip("?") if request.method == "GET" else "/"))


@app.teardown_request
def forget_user(exc=None):
    from flask import g
    ctx = g.pop("ctx", None)
    if ctx is not None:
        try:
            from jobhunt.config import reset_user
            reset_user(ctx)
        except ValueError:
            pass


def admin_only():
    from flask import g
    if not (g.get("user") and g.user["is_admin"]):
        abort(403)


API_HITS: dict[int, list] = {}      # per person: [minute, requests that minute]


def sign_in_as(u: dict):
    from flask import session
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]
    session["sv"] = (accounts.get(u["id"]) or u)["session_version"]


@app.errorhandler(Exception)
def log_error(e):
    """Keep a note of any crash in data/error.log, so problems can be fixed without reading the black window."""
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/") or e.code in (301, 302, 304):
            return e
        return render_template("error.html", code=e.code), e.code
    import traceback
    from datetime import datetime
    try:
        with open(DATA_DIR / "error.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- {datetime.now():%Y-%m-%d %H:%M:%S} {request.method} {request.path}\n{traceback.format_exc()}")
    except Exception:
        pass
    return render_template("error.html", code=500), 500


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        same_site_only()
        import time
        time.sleep(0.6)                  # slows down anyone guessing
        tried = (request.form.get("username", "") or "").strip().lower()[:60]
        u, error = accounts.check_login(tried, request.form.get("password", ""),
                                        request.headers.get("X-Forwarded-For", request.remote_addr or ""))
        if not u:
            alerts.note("failed_login", alerts.network(client_ip()), "Someone may be guessing passwords",
                        f"{{n}} failed sign-ins in {{minutes}} minutes from {client_ip()} (last username tried: "
                        f"{tried or 'blank'}). The website already makes them wait 15 minutes after a few tries.")
            if tried and accounts.username_exists(tried):
                alerts.note("failed_login", "u:" + tried, f"Repeated failed sign-ins to {tried}'s account",
                            f"{{n}} failed sign-ins to the account {tried} in {{minutes}} minutes "
                            f"(latest from {client_ip()}). Someone may be trying to get into their account.")
        if u:
            sign_in_as(u)
            return redirect(safe_next())
    return render_template("login.html", error=error, mode="login", next=safe_next())


@app.route("/logout")
def logout():
    """Signing out ends this sign-in for good: even a copy of the old cookie no longer works."""
    from flask import session
    uid = session.get("uid")
    if uid and HOSTED:
        import secrets as _secrets
        accounts.update(uid, session_version=_secrets.token_hex(8))
    session.clear()
    return redirect(url_for("login"))


@app.route("/first-account", methods=["GET", "POST"])
def first_account():
    """The very first sign-in: the owner makes their account and takes over the data already here."""
    if accounts.any_users():
        return redirect(url_for("login"))
    setup_code = os.environ.get("JOBHUNT_SETUP_CODE", "")
    if not (from_this_pc() or setup_code):
        return ("<!doctype html><meta name=viewport content='width=device-width'><title>Job Hunt HQ</title>"
                "<body style='font:17px/1.5 system-ui;max-width:34em;margin:3em auto;padding:0 16px'>"
                "<h1>One step on your PC first</h1><p>Job Hunt HQ now has usernames and passwords. Open it on your PC "
                "(the computer running it) to create your owner account – then sign in here with it.</p></body>"), 403
    error = ""
    if request.method == "POST":
        same_site_only()
        f = {k: request.form.get(k, "").strip() for k in ("name", "username", "password", "password2", "code")}
        f["username"] = f["username"].lower()
        if setup_code and not from_this_pc():
            import hmac
            if not hmac.compare_digest(f["code"], setup_code):
                error = "That set-up code isn't right."
        error = error or accounts.username_problem(f["username"]) or \
            accounts.password_problem(f["password"], f["username"]) or \
            ("The two passwords don't match." if f["password"] != f["password2"] else "") or \
            ("Add your name." if not f["name"] else "")
        upload = request.files.get("data")
        blob = upload.read() if upload and upload.filename else b""
        if not error and blob:
            import zipfile
            try:
                if "JOB-HUNT-HQ-EXPORT.txt" not in zipfile.ZipFile(__import__("io").BytesIO(blob)).namelist():
                    error = "That file isn't a Job Hunt HQ export – use Account → Download my data on your PC."
            except zipfile.BadZipFile:
                error = "That file isn't a Job Hunt HQ export – use Account → Download my data on your PC."
        if not error:
            uid = accounts.create(f["username"], f["name"], f["password"], is_admin=True)
            if blob:
                accounts.import_zip(uid, blob)
            else:
                accounts.adopt_existing_data(uid)
            sign_in_as(accounts.get(uid))
            flash("Your account is ready, and everything you had is in it. Invite people from the People page.")
            return redirect(url_for("dashboard"))
    try:
        default_name = load_config().get("profile", {}).get("name", "")
    except Exception:
        default_name = ""
    from jobhunt.config import DATA_ON_DISK
    if not DATA_ON_DISK:
        error = error or ("Warning: this server has no permanent disk, so accounts would be wiped at the next update. "
                          "In Render, add a disk (Settings → Disk) before creating your account.")
    return render_template("login.html", mode="first", error=error, default_name=default_name,
                           need_code=bool(setup_code and not from_this_pc()), hosted=HOSTED)


@app.route("/tour")
def tour():
    """The public page: what Job Hunt HQ does (an interactive tour of every feature) and how to join with an invite code."""
    return render_template("tour.html", contact=contact_email(), n_countries=len(countries.COUNTRIES),
                           n_sectors=len(occupations.SECTORS), n_titles=len(occupations.ALL_TITLES),
                           langs=i18n.LANGS, lang=current_lang(), year=date.today().year)


@app.route("/join/<code>", methods=["GET", "POST"])
@app.route("/join", methods=["GET", "POST"], defaults={"code": ""})
def join(code):
    """Make an account with an invite code from the owner."""
    code = (request.form.get("code") or code or request.args.get("code", "")).strip().upper()
    error = ""
    if request.method == "POST":
        same_site_only()
        f = {k: request.form.get(k, "").strip() for k in ("name", "email", "username", "password", "password2")}
        f["username"] = f["username"].lower()
        if code and not accounts.invite_ok(code) and accounts.invite_used(code):
            alerts.raise_alert("used_invite", "A used invite link was tried again",
                               f"Someone at {client_ip()} tried to make an account with the invite code {code}, which "
                               "has already been used. The person you invited may have shared their link.", key=code)
        error = ("That invite code isn't valid or has been used. Ask for a new one." if not accounts.invite_ok(code) else "") or \
            ("Add your name." if not f["name"] else "") or accounts.username_problem(f["username"]) or \
            accounts.password_problem(f["password"], f["username"]) or \
            ("The two passwords don't match." if f["password"] != f["password2"] else "") or \
            ("Tick the box to confirm you're 16 or over and agree to the terms." if request.form.get("agree") != "yes" else "")
        if not error and not accounts.claim_invite(code):
            error = "That invite code isn't valid or has been used. Ask for a new one."
        if not error:
            try:
                uid = accounts.create(f["username"], f["name"], f["password"], email=f["email"])
            except Exception:
                accounts.release_invite(code)
                raise
            accounts.use_invite(code, uid)
            with as_user(uid):
                accounts.save_settings({"profile": {"name": f["name"], "email": f["email"]}, "search": {},
                                        "gmail": {"enabled": False}, "email": {}, "prefs": {}})
            sign_in_as(accounts.get(uid))
            return redirect(url_for("welcome"))
    return render_template("login.html", mode="join", error=error, code=code,
                           code_ok=accounts.invite_ok(code) if code else True)


@app.route("/reset/<code>", methods=["GET", "POST"])
def reset_password(code):
    """A password-reset link the owner made for someone."""
    uid = accounts.reset_user(code)
    error = "" if uid else "This reset link has expired or been used. Ask the owner for a new one."
    if uid and request.method == "POST":
        same_site_only()
        u = accounts.get(uid)
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        error = accounts.password_problem(pw, u["username"]) or ("The two passwords don't match." if pw != pw2 else "")
        if not error and not accounts.claim_reset(code):
            error = "This reset link has expired or been used. Ask the owner for a new one."
        if not error:
            accounts.update(uid, password=pw)
            sign_in_as(accounts.get(uid))
            flash("Password changed.")
            return redirect(url_for("dashboard"))
    return render_template("login.html", mode="reset", error=error, code=code, valid=bool(uid),
                           who=(accounts.get(uid) or {}).get("username", ""))


@app.route("/account", methods=["GET", "POST"])
def account_page():
    from flask import g
    u = g.user
    if request.method == "POST":
        same_site_only()
        action = request.form.get("action")
        if action == "password":
            if not accounts.check_login(u["username"], request.form.get("current", ""))[0]:
                flash("Your current password isn't right.")
            else:
                pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
                problem = accounts.password_problem(pw, u["username"]) or ("The two passwords don't match." if pw != pw2 else "")
                if problem:
                    flash(problem)
                else:
                    accounts.update(u["id"], password=pw)
                    sign_in_as(accounts.get(u["id"]))      # stay signed in here; other devices are signed out
                    flash("Password changed. Any other devices have been signed out.")
        if action == "delete":
            if u["is_admin"]:
                flash("The owner's account can't be deleted from here.")
            elif not accounts.check_login(u["username"], request.form.get("current", ""))[0] or \
                    request.form.get("confirm", "").strip().upper() != "DELETE":
                flash("To delete your account, type DELETE and your password.")
            else:
                from flask import session
                from flask import g
                ctx = g.pop("ctx", None)
                if ctx is not None:
                    from jobhunt.config import reset_user
                    reset_user(ctx)                 # stop using their (now deleted) folder before anything recreates it
                g.user = None
                accounts.delete_user(u["id"])
                session.clear()
                return render_template("login.html", mode="login", error="",
                                       done="Your account and everything stored for you have been deleted.")
        return redirect(url_for("account_page"))
    return render_template("account.html", u=u)


LEGAL_PAGES = {"terms": "Terms of use", "disclaimer": "Disclaimer", "cookies": "Cookie notice",
               "acceptable-use": "Acceptable use", "contact": "Contact us"}


def contact_email() -> str:
    return os.environ.get("JOBHUNT_CONTACT") or (accounts.owner_contact() if accounts.any_users() else "") or "info@jhhq.co.uk"


@app.route("/legal/<page>")
def legal(page):
    """Terms, disclaimer, cookies, acceptable use and contact – readable without signing in."""
    if page not in LEGAL_PAGES:
        abort(404)
    return render_template("legal.html", page=page, title=LEGAL_PAGES[page], contact=contact_email(),
                           updated="2 November 2026")


@app.route("/privacy")
def privacy():
    """Privacy notice: what's stored, who can see it, and your rights under UK GDPR."""
    return render_template("privacy.html", contact=contact_email())


@app.route("/account/export")
def account_export():
    """Download everything that's yours – to keep a backup, or to move to the Job Hunt HQ website."""
    from flask import g
    import io
    data = accounts.export_zip(g.user["id"])
    return send_file(io.BytesIO(data), mimetype="application/zip", as_attachment=True,
                     download_name=f"Job Hunt HQ data - {g.user['username']} - {date.today().isoformat()}.zip")


@app.route("/favicon.ico")
def favicon():
    return send_file(Path(app.static_folder) / "favicon.ico", mimetype="image/x-icon", max_age=86400)


@app.route("/api/place")
def api_place():
    """What a typed place is – shown under the location box so people can see it's understood."""
    from jobhunt import geo
    return geo.describe((request.args.get("q") or "")[:120])


# ------------------------------------------------------------------ search every job site
@app.route("/everywhere")
def everywhere():
    """Each of your job titles, ready-searched on Indeed, LinkedIn, Reed, CV-Library, Totaljobs and the rest."""
    cfg = load_config()
    search, profile = cfg.get("search", {}), cfg.get("profile", {})
    titles = [t for t in (search.get("keywords") or []) if t][:12]
    places = []
    for l in search.get("locations") or []:
        place, miles = (l, search.get("distance_miles", 15)) if isinstance(l, str) else (l.get("place"), l.get("miles", 15))
        if place:
            places.append((place, int(miles or 15)))
    if not places and profile.get("location"):
        places = [(profile["location"], int(search.get("distance_miles", 15) or 15))]
    place = request.args.get("place") or (places[0][0] if places else "")
    miles = next((m for p, m in places if p == place), 15)
    from jobhunt import countries
    country = countries.code_for(profile.get("country") or "GB")
    rows = [(t, occupations.search_links(t, place, miles, country)) for t in titles]
    sectors = [occupations.SECTORS[k][0] for k in occupations.sectors_for(titles)]
    src = cfg.get("sources", {})
    uk = country == "GB"
    feeds = ([("Reed", bool(src.get("reed_api_key"))), ("Adzuna", bool(src.get("adzuna_app_id"))),
              ("CV-Library", bool(src.get("cvlibrary_key"))), ("The Talent World (HR jobs)", "hr" in occupations.sectors_for(titles))]
             if uk else [(f"Adzuna {countries.name(country)}", bool(src.get("adzuna_app_id") and countries.adzuna(country)))])
    gmail_on = bool(cfg.get("gmail", {}).get("enabled"))
    return render_template("everywhere.html", rows=rows, places=places, place=place, miles=miles, sectors=sectors,
                           feeds=feeds, gmail_on=gmail_on, profile=profile,
                           country=countries.name(country),
                           alerts=[(t, occupations.alert_links(t, place, country)) for t in titles[:6]])


# ------------------------------------------------------------------ feedback
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


@app.route("/feedback", methods=["GET", "POST"])
def feedback_page():
    """Anyone can send feedback; the owner sees everyone's and can mark it planned/done and reply."""
    from flask import g
    u = g.user
    if request.method == "POST":
        same_site_only()
        message = (request.form.get("message") or "").strip()
        back = request.form.get("page") or ""
        if not message:
            flash("Write a few words first.")
            return redirect(back if back.startswith("/") and not back.startswith("//") else url_for("feedback_page"))
        image = None
        f = request.files.get("image")
        if f and f.filename:
            ext = Path(f.filename).suffix.lower()
            data = f.read()
            looks_ok = data.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8")) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
            if ext in IMAGE_TYPES and looks_ok:
                image = (data, ext)
            else:
                flash("The screenshot needs to be a PNG, JPG, WebP or GIF image – your message was still sent.")
        fid = accounts.add_feedback(u["id"], request.form.get("kind", "idea"), message, back, image)
        if request.form.get("kind") == "report":
            alerts.raise_alert("report", f"{u['name']} ({u['username']}) reported misuse or a security problem",
                               f"Page: {back or '-'}\n\n{message[:3000]}", key=str(fid))
        flash("Thanks – your feedback has been sent." if not u["is_admin"] else "Noted.")
        return redirect(back if back.startswith("/") and not back.startswith("//") else url_for("feedback_page"))
    show = request.args.get("show", "open")
    items = accounts.feedback_list(None if u["is_admin"] else u["id"])
    counts = {k: sum(1 for i in items if i["status"] == k) for k, _ in accounts.FEEDBACK_STATUS}
    if show == "open":
        items = [i for i in items if i["status"] in ("new", "planned")]
    elif show in counts:
        items = [i for i in items if i["status"] == show]
    return render_template("feedback.html", items=items, show=show, counts=counts,
                           statuses=accounts.FEEDBACK_STATUS, kinds=dict(accounts.FEEDBACK_KINDS))


@app.post("/feedback/<int:fid>")
def feedback_update(fid):
    same_site_only()
    admin_only()
    if request.form.get("action") == "delete":
        accounts.delete_feedback(fid)
        flash("Deleted.")
    else:
        accounts.update_feedback(fid, request.form.get("status"), request.form.get("reply"))
        flash("Saved.")
    return redirect(request.referrer or url_for("feedback_page"))


@app.route("/feedback/<int:fid>/image")
def feedback_image(fid):
    from flask import g
    f = accounts.get_feedback(fid)
    if not f or not f.get("image") or not (g.user["is_admin"] or f["user_id"] == g.user["id"]):
        abort(404)
    path = accounts.FEEDBACK_DIR / f["image"]
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype=IMAGE_TYPES.get(path.suffix.lower(), "application/octet-stream"))


# ------------------------------------------------------------------ languages
def cfg_profile() -> dict:
    try:
        return load_config().get("profile") or {} if current_user_id() else {}
    except Exception:
        return {}


def current_lang() -> str:
    from flask import g
    if "lang" in g:
        return g.lang
    pref = None
    if current_user_id():
        try:
            pref = (accounts.load_settings(current_user_id()).get("prefs") or {}).get("language")
        except Exception:
            pref = None
    from flask import session
    g.lang = i18n.pick(pref or session.get("lang") or request.cookies.get("jhq_lang"),
                       request.headers.get("Accept-Language", ""))
    return g.lang


# Every link to a style sheet, script or picture carries the file's version, so browsers fetch the new one as soon as it
# changes instead of showing an old saved copy (and can keep unchanged files for a year).
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 365


@app.url_defaults
def static_version(endpoint, values):
    if endpoint == "static" and "filename" in values and "v" not in values:
        try:
            values["v"] = int((Path(app.static_folder) / values["filename"]).stat().st_mtime)
        except OSError:
            pass


# The website only answers to its own names, so a forged Host header can't put someone else's address into invite and
# password-reset links ("reset poisoning"). JOBHUNT_HOSTS can add more, comma-separated.
ALLOWED_HOSTS = {h.strip().lower() for h in os.environ.get("JOBHUNT_HOSTS", "jhhq.co.uk,www.jhhq.co.uk").split(",") if h.strip()}


@app.before_request
def only_our_hostnames():
    if not HOSTED:
        return None
    host = (request.host or "").split(":")[0].lower()
    if host in ALLOWED_HOSTS or host.endswith(".onrender.com"):
        return None
    abort(400)


def site_url() -> str:
    """This website's own address, for links people are sent (never taken from what the visitor's browser claims)."""
    if os.environ.get("JOBHUNT_URL"):
        return os.environ["JOBHUNT_URL"].rstrip("/")
    if HOSTED:
        return "https://www.jhhq.co.uk"
    return request.host_url.rstrip("/")


@app.after_request
def security_headers(resp):
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("X-Frame-Options", "DENY")                                        # no hidden-frame "clickjacking"
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=(), usb=(), microphone=(self)")
    h.setdefault("Content-Security-Policy",
                 "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                 "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; media-src 'self' blob:; "
                 "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
    if HOSTED:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint not in ("static", "favicon", "manifest", None):
        h.setdefault("Cache-Control", "no-store")                                   # private pages aren't cached
    return resp


@app.after_request
def translate_page(resp):
    try:
        if resp.mimetype == "text/html" and resp.status_code in (200, 400, 403, 404, 413, 429, 500) and not resp.direct_passthrough:
            lang = current_lang()
            if lang != "en":
                resp.set_data(i18n.translate(resp.get_data(as_text=True), lang))
    except Exception:
        pass
    return resp


@app.route("/language/<code>")
def set_language(code):
    """Choose the language Job Hunt HQ is shown in (kept for this person, and in this browser)."""
    code = code if code in i18n.CODES else "en"
    if current_user_id():
        s = my_settings()
        s.setdefault("prefs", {})["language"] = code
        accounts.save_settings(s, current_user_id())
    from urllib.parse import urlparse
    ref = urlparse(request.referrer or "")
    back = (ref.path + ("?" + ref.query if ref.query else "")) if ref.netloc == request.host and ref.path.startswith("/") \
        else url_for("dashboard")
    resp = redirect(back)
    from flask import session
    session["lang"] = code                                 # for this visit (part of the sign-in cookie)
    if request.cookies.get("jhq_consent") == "all":        # remembered for a year only if they said yes to cookies
        resp.set_cookie("jhq_lang", code, max_age=60 * 60 * 24 * 365, samesite="Lax", secure=HOSTED)
    return resp


@app.post("/cookies")
def cookie_choice():
    """The cookie banner: "Accept" (also remember the language) or "Only essential". The choice itself is kept so
    the banner doesn't come back; it can be changed on the cookie notice."""
    same_site_only()
    choice = "all" if request.form.get("choice") == "all" else "essential"
    from urllib.parse import urlparse
    ref = urlparse(request.referrer or "")
    back = (ref.path + ("?" + ref.query if ref.query else "")) if ref.netloc == request.host and ref.path.startswith("/") else "/"
    resp = redirect(back)
    resp.set_cookie("jhq_consent", choice, max_age=60 * 60 * 24 * 365, samesite="Lax", secure=HOSTED, httponly=True)
    if choice == "essential":
        resp.delete_cookie("jhq_lang")
    else:
        resp.set_cookie("jhq_lang", current_lang(), max_age=60 * 60 * 24 * 365, samesite="Lax", secure=HOSTED)
    return resp


# ------------------------------------------------------------------ each person's own settings
LEVELS = [("entry", "Starting out / junior"), ("mid", "Experienced"), ("senior", "Senior / lead")]
MILES = [5, 10, 15, 20, 30, 40, 60]


def my_settings() -> dict:
    s = accounts.load_settings(current_user_id())
    for k in ("profile", "search", "gmail", "email", "prefs"):
        s.setdefault(k, {})
    return s


def _lines(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"[\n,;]+", text or "") if x.strip()]


def _places(text: str, default_miles: int) -> list[dict]:
    """'Manchester, 15' per line → [{place: Manchester, miles: 15}]."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.*?)[,\s]+(\d{1,3})\s*(miles?|mi)?$", line)
        out.append({"place": m.group(1).strip(), "miles": int(m.group(2))} if m else {"place": line, "miles": default_miles})
    return out[:6]


def save_settings_form(form, parts=("profile", "search", "prefs", "gmail")) -> list[str]:
    """Update the signed-in person's settings from a form. Returns problems to show."""
    s = my_settings()
    problems = []
    if "profile" in parts:
        if "country" in form:
            from jobhunt import countries as _c
            s["profile"]["country"] = _c.code_for(form.get("country"))
        if form.get("language") in i18n.CODES:
            s.setdefault("prefs", {})["language"] = form.get("language")
        for k in ("name", "email", "phone", "location", "address", "linkedin", "github", "indeed", "current_title",
                  "current_employer", "notice_period", "salary_expectation", "right_to_work"):
            if k in form:
                s["profile"][k] = form.get(k, "").strip()
        if "phone_code" in form:                    # "+44|GB": the dialling code, and which country it's for
            code, _, cc = form.get("phone_code", "").partition("|")
            if re.fullmatch(r"\+\d{1,4}", code):
                s["profile"]["phone_code"], s["profile"]["phone_code_country"] = code, cc[:2].upper()
        if "name" in form and not s["profile"].get("name"):
            problems.append("Add your name.")
    if "search" in parts:
        if "keywords" in form:
            s["search"]["keywords"] = [k for k in (x.strip() for x in form.get("keywords", "").splitlines()) if k][:20]
        if "miles" in form or "places" in form:
            miles = int(form.get("miles") or 15)
            places = _places(form.get("places", ""), miles) if form.get("places", "").strip() else \
                ([{"place": s["profile"].get("location", ""), "miles": miles}] if s["profile"].get("location") else [])
            s["search"]["locations"] = places
            s["search"]["distance_miles"] = miles
        if "min_salary" in form:
            s["search"]["min_salary"] = int(re.sub(r"[^\d]", "", form.get("min_salary", "")) or 0)
        if "keywords" in form:
            s["search"]["include_remote"] = form.get("include_remote") == "yes"
            s["search"]["exclude_title_words"] = _lines(form.get("exclude", ""))[:30]
            s["search"].setdefault("max_age_days", 14)
            s["search"].setdefault("hide_far_jobs", True)
    if "prefs" in parts:
        if "level" in form:
            s["prefs"]["level"] = form.get("level") if form.get("level") in dict(LEVELS) else "mid"
        if "skills" in form:
            s["prefs"]["skills"] = _lines(form.get("skills", ""))[:40]
    if "gmail" in parts and "gmail_address" in form:
        from jobhunt import mail_providers as mp
        addr = form.get("gmail_address", "").strip()
        prov = form.get("mail_provider") if form.get("mail_provider") in mp.PROVIDERS else mp.guess(addr)
        pw = re.sub(r"\s", "", form.get("gmail_app_password", "")) if prov == "gmail" else form.get("gmail_app_password", "").strip()
        if addr != s["email"].get("from") or prov != s["email"].get("provider"):
            s["email"].pop("ms_refresh_token", None)          # a different account: sign in to it again
        s["email"]["from"], s["email"]["provider"] = addr, prov
        s["email"]["to"] = form.get("send_to", "").strip() or addr
        if prov == "other":
            host = form.get("imap_host", "").strip().lower()
            if host and not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host):
                problems.append("The IMAP server should look like imap.example.com.")
            else:
                s["email"]["imap_host"] = host
        if pw:
            if prov == "gmail" and len(pw) != 16:
                problems.append("A Gmail app password is 16 letters – check you copied all of it.")
            elif len(pw) > 200:
                problems.append("That password is too long.")
            else:
                s["email"]["gmail_app_password"] = pw
        connected = bool(s["email"].get("ms_refresh_token")) if prov == "outlook" else bool(s["email"].get("gmail_app_password"))
        s["gmail"]["enabled"] = bool(addr and connected)
        s["gmail"]["read_job_alerts"] = form.get("read_job_alerts") == "yes"
        s["email"]["enabled"] = form.get("job_emails") == "yes" and s["gmail"]["enabled"] and prov != "outlook"
    accounts.save_settings(s, current_user_id())
    return problems


@app.route("/welcome", methods=["GET", "POST"])
def welcome():
    """A new person's first-time set-up, in three short steps."""
    from flask import g
    step = int(request.args.get("step", 1))
    if request.method == "POST":
        same_site_only()
        step = int(request.form.get("step", 1))
        if step == 1:
            problems = save_settings_form(request.form, ("profile",))
            if not request.form.get("location", "").strip():
                problems.append("Add the town, city or postcode you'd like to work near.")
            if problems:
                for p in problems:
                    flash(p)
                return redirect(url_for("welcome", step=1))
            return redirect(url_for("welcome", step=2))
        if step == 2:
            problems = save_settings_form(request.form, ("search", "prefs"))
            if not my_settings()["search"].get("keywords"):
                problems.append("Add at least one kind of job you're looking for.")
            if problems:
                for p in problems:
                    flash(p)
                return redirect(url_for("welcome", step=2))
            return redirect(url_for("welcome", step=3))
        if step == 3:
            accounts.update(g.user["id"], setup_done=1)
            flash("You're all set. Press Refresh jobs to find your first matches – it takes about a minute.")
            then = request.form.get("then")
            return redirect(url_for(then if then in ("dashboard", "cv_builder") else "dashboard"))
    from jobhunt import career as career_store
    return render_template("welcome.html", step=step, s=my_settings(), levels=LEVELS, miles=MILES,
                           career=career_store.load())


@app.route("/email/outlook/start")
def outlook_start():
    """Outlook / Hotmail: send the person to Microsoft's sign-in (read-only access to their mail)."""
    from jobhunt import mail_providers as mp
    if not mp.microsoft_ready():
        abort(404)
    import secrets as _secrets
    from flask import session
    session["ms_state"] = _secrets.token_urlsafe(24)
    return redirect(mp.microsoft_sign_in_url(site_url() + url_for("outlook_callback"), session["ms_state"]))


@app.route("/email/outlook/callback")
def outlook_callback():
    from flask import session

    from jobhunt import mail_providers as mp
    if not mp.microsoft_ready() or not request.args.get("code") or \
            request.args.get("state") != session.pop("ms_state", None):
        flash("Outlook wasn't connected. Try again.")
        return redirect(url_for("settings_page") + "#gmail")
    try:
        t = mp.microsoft_exchange(request.args["code"], site_url() + url_for("outlook_callback"))
    except Exception:
        t = {}
    if not t.get("refresh_token"):
        flash("Microsoft didn't allow the connection. Try again.")
        return redirect(url_for("settings_page") + "#gmail")
    s = my_settings()
    s["email"].update(provider="outlook", ms_refresh_token=t["refresh_token"])
    s["gmail"]["enabled"] = bool(s["email"].get("from"))
    accounts.save_settings(s, current_user_id())
    flash("Outlook connected. Your job emails will be read at the next refresh.")
    return redirect(url_for("settings_page") + "#gmail")


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        same_site_only()
        problems = save_settings_form(request.form)
        for p in problems:
            flash(p)
        if not problems:
            flash("Saved. Your next job refresh, scores and letters use these settings.")
        return redirect(url_for("settings_page"))
    from jobhunt import mail_providers as _mp
    s = my_settings()
    places = "\n".join(f"{l['place']}, {l.get('miles', 15)}" if isinstance(l, dict) else str(l)
                        for l in s["search"].get("locations", []))
    return render_template("settings.html", s=s, levels=LEVELS, miles=MILES, places=places,
                           has_password=bool(s["email"].get("gmail_app_password")),
                           mail_providers=_mp.PROVIDERS, mail_provider=_mp.provider(s),
                           mail_domains={k: list(v[4]) for k, v in _mp.PROVIDERS.items()},
                           outlook_ready=_mp.microsoft_ready())


@app.route("/people", methods=["GET", "POST"])
def people_page():
    """The owner's page: invite codes, everyone's accounts, password-reset links."""
    from flask import g
    admin_only()
    made = None
    if request.method == "POST":
        same_site_only()
        action = request.form.get("action")
        if action == "invite":
            made = {"kind": "invite", "code": accounts.create_invite(g.user["id"], request.form.get("note", ""))}
        elif action == "cancel":
            accounts.cancel_invite(request.form.get("code", ""))
            flash("Invite cancelled.")
        elif action in ("off", "on"):
            uid = int(request.form.get("user_id", 0))
            if uid != g.user["id"]:
                accounts.update(uid, active=1 if action == "on" else 0)
                flash("Account switched " + ("on." if action == "on" else "off. They can't sign in any more."))
        elif action == "newkey":
            uid = int(request.form.get("user_id", 0))
            with as_user(uid):
                from jobhunt.config import user_dir
                (user_dir() / "access_token.txt").unlink(missing_ok=True)
                access_token()
            flash("Their old browser assistant has stopped working. They need to download the assistant again.")
        elif action == "reset":
            uid = int(request.form.get("user_id", 0))
            made = {"kind": "reset", "code": accounts.create_reset(uid), "who": (accounts.get(uid) or {}).get("username")}
        if not made:
            return redirect(url_for("people_page"))
    return render_template("people.html", users=accounts.all_users(), invites=accounts.invites(), made=made,
                           alerts=alerts.recent(30), alerts_email=alerts.email_ready(), alert_to=alerts._to(),
                           base=site_url())


@app.route("/manifest.webmanifest")
def manifest():
    from flask import jsonify
    resp = jsonify({"name": "Job Hunt HQ", "short_name": "Job Hunt", "start_url": "/", "display": "standalone",
                    "background_color": "#0b1240", "theme_color": "#0b1240",
                    "icons": [{"src": url_for("static", filename="favicon.svg"), "sizes": "any", "type": "image/svg+xml"},
                              {"src": url_for("static", filename="favicon-192.png"), "sizes": "192x192", "type": "image/png"},
                              {"src": url_for("static", filename="icon-180.png"), "sizes": "180x180", "type": "image/png"},
                              {"src": url_for("static", filename="icon-512.png"), "sizes": "512x512", "type": "image/png"}]})
    resp.mimetype = "application/manifest+json"
    return resp


# Sidebar: (section, [(endpoint, label, icon)]) – the same groups as the GSI HRIS layout.
NAV = [
    ("Overview", [("dashboard", "Home", "home"), ("jobs_page", "Jobs", "briefcase")]),
    ("Applying", [("applications_page", "Applications", "list"), ("interview_page", "Interview prep", "chat"),
                  ("assistant_page", "Assistant", "send"), ("robot_page", "Apply for me", "send"), ("add_job", "Add a job", "plus")]),
    ("You", [("career_page", "My career", "user"), ("cv_builder", "Create CV", "file")]),
]
# Pages that live under a menu item (so the right one is highlighted).
NAV_PARENT = {"job_detail": "jobs_page", "everywhere": "jobs_page", "import_page": "add_job", "settings_page": "",
              "interview_practice": "interview_page", "emails": "applications_page",
              "account_page": "", "job_letter_download": "jobs_page"}
CRUMBS = {"dashboard": ("Overview", "Home"), "jobs_page": ("Overview", "Jobs"),
          "interview_page": ("Applying", "Interview prep"), "interview_practice": ("Applying", "Interview practice"), "job_detail": ("Overview", "Job"), "add_job": ("Applying", "Add a job"),
          "robot_page": ("Applying", "Apply for me"), "career_page": ("You", "My career"), "emails": ("You", "Emails"),
          "setup": ("Settings", "Setup"), "import_page": ("Applying", "Import"),
          "applications_page": ("Applying", "Applications"), "cv_builder": ("You", "Create CV"), "everywhere": ("Applying", "Job sites"), "assistant_page": ("Applying", "Assistant"),
          "settings_page": ("You", "My settings"), "feedback_page": ("You", "Feedback")}


@app.context_processor
def helpers():
    from datetime import datetime

    from flask import g
    try:
        profile = load_config().get("profile", {})
    except Exception:
        profile = {}
    user = g.get("user")
    name = profile.get("name") or (user or {}).get("name") or "You"
    hour = datetime.now().hour
    return {"fit_label": fit_label, "status_labels": db.STATUS_LABELS, "email_labels": db.EMAIL_LABELS, "app_statuses": db.APP_STATUSES,
            "today": date.today().isoformat(), "ago": ago, "crumbs": CRUMBS,
            "me": {"name": name, "first": name.split()[0], "title": profile.get("current_title", ""),
                   "employer": profile.get("current_employer", ""),
                   "initials": "".join(w[0] for w in name.split()[:2]).upper()},
            "greeting": i18n.phrase("Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening",
                                    current_lang()),
            "today_label": i18n.date_label(datetime.now(), current_lang()),
            "t": lambda text, **kw: i18n.phrase(text, current_lang(), **kw),
            "user": user, "is_admin": bool(user and user["is_admin"]), "hosted": HOSTED,
            "feedback_new": accounts.new_feedback_count() if user and user["is_admin"] else 0,
            "feedback_kinds": accounts.FEEDBACK_KINDS,
            "occupations": OCCUPATIONS_JSON, "all_titles": occupations.ALL_TITLES,
            "langs": i18n.LANGS, "lang": current_lang(), "countries": countries.COUNTRIES,
            "dial_codes": countries.DIAL_CODES, "dial_code": countries.dial_code,
            "currency": countries.currency((cfg_profile() or {}).get("country") or "GB"),
            "nav_on": NAV_PARENT.get(request.endpoint, request.endpoint),
            "nav": [(sec, [("assistant_page", "Apply for me", "send") if (HOSTED and i[0] == "assistant_page") else i
                           for i in items if not (HOSTED and i[0] in PC_ONLY_ENDPOINTS)]) for sec, items in NAV]}


@app.template_global()
def gmail_url(gmail_id: str, subject: str = "") -> str:
    """Open the email in Gmail (in the right Google account)."""
    from urllib.parse import quote
    try:
        who = load_config().get("profile", {}).get("email", "")
    except Exception:
        who = ""
    base = "https://mail.google.com/mail/" + (f"?authuser={quote(who)}" if who else "u/0/")
    gid = str(gmail_id or "")
    if re.fullmatch(r"[0-9a-f]{10,20}", gid):
        return f"{base}#all/{gid}"
    return f"{base}#search/{quote('subject:"' + (subject or '')[:80] + '"')}"


def phone_fields(profile: dict) -> dict:
    """The phone number as typed, its country code, and the full international number – forms ask for all three."""
    code = profile.get("phone_code") or countries.dial_code(profile.get("country"))
    cc = (profile.get("country") or "GB").upper()
    name = (countries.COUNTRIES.get(cc) or (None,))[0] or next((n for c, n, _ in countries.DIAL_CODES if c == cc), "")
    return {"phone_code": code, "phone_intl": countries.international(profile.get("phone", ""), code), "country_name": name}


MONTH_NUMBERS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_loose_date(text, near: str = ""):
    """A date written in an email ("Tuesday 29th September 2026", "Wednesday 19 August", "2026-10-22") as a date,
    or None. Without a year, the year is the one that puts it closest to when the email came."""
    t = str(text or "").strip().lower()
    if not t:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+([a-z]{3})[a-z]*\.?(?:,?\s+(\d{4}))?", t) or \
        re.search(r"\b([a-z]{3})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", t)
    if not m:
        return None
    a, b, year = m.groups()
    day, mon = (a, b) if a.isdigit() else (b, a)
    month = MONTH_NUMBERS.get(mon[:3])
    if not month:
        return None
    try:
        base = date.fromisoformat(near[:10]) if near else date.today()
    except ValueError:
        base = date.today()
    try:
        if year:
            return date(int(year), month, int(day))
        options = [date(base.year + k, month, int(day)) for k in (-1, 0, 1)]
        return min(options, key=lambda d: abs((d - base).days))
    except ValueError:
        return None


@app.template_filter("nice_date")
def nice_date(iso) -> str:
    """2026-10-28 → '28 Oct' (this year) or '28 Oct 2025'."""
    try:
        d = date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return str(iso or "")
    lang = current_lang() if has_request_context() else "en"
    month = i18n.MONTHS[lang].split()[d.month - 1] if lang in i18n.MONTHS else f"{d:%b}"
    day = f"{d.day}." if lang == "de" else str(d.day)            # German writes "14. Okt"
    return f"{day} {month}" + ("" if d.year == date.today().year else f" {d.year}")


def ago(iso) -> str:
    """'today', 'yesterday', '3 days ago', '2 weeks ago'… for a YYYY-MM-DD date; '' if unknown."""
    try:
        days = (date.today() - date.fromisoformat(str(iso or "")[:10])).days
    except ValueError:
        return ""
    return ("today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago" if days < 14
            else f"{days // 7} weeks ago" if days < 60 else f"{days // 30} months ago")


def conn():
    c = db.connect()
    seed_if_empty(c)
    c.commit()
    return c


# ------------------------------------------------------------------ dashboard
def _job_list(c, a):
    """The jobs to review, with the filters from the Jobs page (search, fit, posted, source, sort)."""
    q = (a.get("q") or "").strip().lower()
    fit, posted, sort, src = a.get("fit", ""), a.get("posted", ""), a.get("sort", ""), a.get("src", "")
    jobs = [dict(r) for r in c.execute(
        "SELECT * FROM jobs WHERE status IN ('new', 'shortlisted', 'prepared') "
        "AND id NOT IN (SELECT job_id FROM applications WHERE job_id IS NOT NULL) "
        "ORDER BY COALESCE(score, -1) DESC, created_at DESC")]
    if q:
        jobs = [j for j in jobs if q in f"{j['title']} {j['company']} {j['location']}".lower()]
    if fit:
        jobs = [j for j in jobs if fit_label(j["score"]) == fit]
    today = date.today()
    for j in jobs:       # how recently each job was posted (or first seen, when the site doesn't say)
        try:
            j["age"] = (today - date.fromisoformat((j.get("posted") or "")[:10])).days
        except ValueError:
            j["age"] = None
    if posted.isdigit():
        jobs = [j for j in jobs if j["age"] is not None and j["age"] <= int(posted)]
    if sort == "newest":
        jobs.sort(key=lambda j: (j["age"] if j["age"] is not None else 9999, -(j["score"] or 0)))
    sources = {}
    for j in jobs:
        sources[j["source"]] = sources.get(j["source"], 0) + 1
    sources = sorted(sources.items(), key=lambda kv: (kv[0] not in ("LinkedIn", "Indeed"), -kv[1]))
    if src:
        jobs = [j for j in jobs if j["source"] == src]
    return jobs, {"q": q, "fit": fit, "posted": posted, "sort": sort, "src": src, "sources": sources}


def _overview(c) -> dict:
    """Everything the Home page sums up: your figures, what needs you next, best matches, replies, the pipeline."""
    apps = [dict(r) for r in c.execute(
        "SELECT * FROM applications ORDER BY CASE status WHEN 'interview' THEN 0 WHEN 'second_stage' THEN 0 WHEN 'offer' THEN 0 "
        "WHEN 'assessment' THEN 1 WHEN 'pre_screen' THEN 1 WHEN 'ready' THEN 2 ELSE 3 END, "
        "COALESCE(applied_on, '9999') DESC, updated_at DESC")]
    jobs, _ = _job_list(c, {})
    counts = {s: 0 for s, _ in db.APP_STATUSES}
    for a in apps:
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    submitted = sum(v for k, v in counts.items() if k != "ready")
    heard = submitted - counts["applied"]
    today = date.today().isoformat()
    kpis = {"applied": submitted, "waiting": counts["applied"] + counts["acknowledged"],
            "progressing": counts["pre_screen"] + counts["assessment"] + counts["interview"] + counts["second_stage"] + counts["offer"],
            "rejected": counts["rejected"], "matches": len(jobs),
            "new_today": len([j for j in jobs if j["status"] == "new" and (j["created_at"] or "")[:10] == today]),
            "this_week": sum(1 for a in apps if (a.get("applied_on") or "") >= (date.today() - timedelta(days=6)).isoformat()),
            "reply_rate": round(100 * heard / submitted) if submitted else 0,
            "strong": sum(1 for j in jobs if (j["score"] or 0) >= 70)}
    last = {r["application_id"]: r["m"] for r in c.execute(
        "SELECT application_id, MAX(received_at) AS m FROM events WHERE application_id IS NOT NULL GROUP BY application_id")}
    attention = [a for a in apps if a["status"] in ("offer", "interview", "second_stage", "assessment", "pre_screen")]
    for a in attention:
        a["when"] = (last.get(a["id"]) or a.get("applied_on") or a.get("updated_at") or "")[:10]
    attention.sort(key=lambda a: (a.get("next_date") or "9999", "" if a["status"] == "offer" else a["when"]), reverse=False)
    attention.sort(key=lambda a: a["when"], reverse=True)
    letters = [j for j in jobs if j["status"] == "prepared"]
    events = [dict(r) for r in c.execute(
        "SELECT e.*, a.company AS app_company, a.role AS app_role FROM events e "
        "LEFT JOIN applications a ON a.id = e.application_id "
        "WHERE e.category NOT IN ('other', 'job_alert') ORDER BY e.received_at DESC LIMIT 3")]
    pipeline = [(key, label, sum(counts.get(s, 0) for s in sts)) for key, label, sts in APP_GROUPS if sts and key != "withdrawn"]
    meta = {"last_refresh": db.get_meta(c, "last_refresh"), "last_gmail": db.get_meta(c, "last_gmail_sync")}
    return {"apps": apps, "jobs": jobs, "kpis": kpis, "counts": counts, "attention": attention, "letters": letters,
            "events": events, "pipeline": pipeline, "pipeline_max": max([n for _, _, n in pipeline] + [1]), "meta": meta,
            "ready_apps": [a for a in apps if a["status"] == "ready"]}


def _setup_steps() -> list[dict]:
    """The few things that make Job Hunt HQ work well, and whether each is done – shown on Home until they all are."""
    cfg = load_config()
    prof, search = cfg.get("profile") or {}, cfg.get("search") or {}
    try:
        has_cv = cv_file(prof) is not None
    except Exception:
        has_cv = False
    try:
        from jobhunt import career as _career
        has_career = bool((_career.load() or {}).get("experience"))
    except Exception:
        has_career = False
    return [
        {"done": bool(prof.get("name") and prof.get("location")), "label": "Add your name and where you live", "href": "/settings"},
        {"done": bool(search.get("keywords")), "label": "Choose the jobs you're looking for", "href": "/settings"},
        {"done": has_cv, "label": "Upload or create your CV", "href": url_for("cv_builder")},
        {"done": has_career, "label": "Add your work history, for better cover letters", "href": url_for("career_page")},
        {"done": bool((cfg.get("gmail") or {}).get("enabled")), "label": "Connect your email to track replies (optional)",
         "href": "/settings#gmail"},
    ]


@app.route("/")
def dashboard():
    """Home: a short summary of where your job hunt is, and what to do next."""
    if any(request.args.get(k) for k in ("q", "fit", "posted", "sort", "src", "limit")):
        return redirect(url_for("jobs_page", **request.args))        # old links to the job list
    c = conn()
    o = _overview(c)
    o["review_n"] = len(review_candidates(c))
    c.close()
    steps = _setup_steps()
    return render_template("home.html", **o, globe=_globe(o["jobs"]), setup_steps=steps,
                           setup_done=sum(s["done"] for s in steps))


_DOTS: dict = {}


def in_country(cc: str, where) -> bool:
    """Whether a place is in the country, judged by the nearest land dot on that country's map (they know their borders)."""
    if cc not in _DOTS:
        try:
            raw = json.loads((Path(app.static_folder) / "globe" / f"{cc}.json").read_text())
            _DOTS[cc] = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
        except Exception:
            _DOTS[cc] = []
    dots = _DOTS[cc]
    lat, lon = countries.CENTRES.get(cc, countries.CENTRES["GB"])[:2]
    if not dots:
        return geo.miles(where, (lat, lon)) * 1.609 <= countries.CENTRES.get(cc, countries.CENTRES["GB"])[2]
    import math
    squash = math.cos(math.radians(where[0]))
    near = min(dots, key=lambda d: (d[0] - where[0]) ** 2 + ((d[1] - where[1]) * squash) ** 2)
    return bool(near[2]) and geo.miles(where, near[:2]) < 40


def _globe(jobs: list) -> dict:
    """The Home globe: centred on the country you live in, with your best matches at the places they're based."""
    prof = cfg_profile() or {}
    cc = countries.code_for(prof.get("country") or "GB")
    lat, lon, reach = countries.CENTRES.get(cc, countries.CENTRES["GB"])
    home = geo.cached(prof.get("location") or "") if prof.get("location") else None
    shown, missing = [], []
    for j in jobs[:60]:
        where = geo.job_place_cached(j.get("location") or "")
        if where is None:
            missing.append(j.get("location") or "")
        elif in_country(cc, where):                                       # only jobs in your own country
            shown.append({"id": j["id"], "lat": round(where[0], 3), "lon": round(where[1], 3), "score": j.get("score") or 0,
                          "title": j.get("title") or "", "company": j.get("company") or "", "ready": j.get("status") == "prepared"})
    if missing and not app.config.get("TESTING"):
        geo.warm(missing + ([prof.get("location")] if prof.get("location") and not home else []))
    return {"cc": cc, "country": countries.name(cc), "lat": lat, "lon": lon, "reach": reach,
            "home": list(home) if home else None, "jobs": shown[:24], "pending": len(missing)}


@app.route("/jobs")
def jobs_page():
    """Every job found for you, best match first, with filters."""
    c = conn()
    jobs, f = _job_list(c, request.args)
    meta = {"last_refresh": db.get_meta(c, "last_refresh")}
    review_n = len(review_candidates(c))
    c.close()
    total_jobs = len(jobs)
    limit = int(request.args["limit"]) if request.args.get("limit", "").isdigit() else 50
    limit = max(50, limit)
    args = {k: v for k, v in request.args.items() if v and k != "limit"}
    return render_template("jobs.html", jobs=jobs[:limit], total_jobs=total_jobs, limit=limit, args=args, meta=meta, review_n=review_n,
                           strong=sum(1 for j in jobs if (j["score"] or 0) >= 70),
                           letters=sum(1 for j in jobs if j["status"] == "prepared"), **f)


@app.post("/refresh")
def refresh():
    result = run_refresh(log=lambda m: None)
    for m in result["messages"]:
        flash(m)
    try:
        c = conn()
        prepare_queue(c, limit=5)
        c.close()
    except Exception as e:
        print("[review queue] couldn't prepare letters:", e)
    return redirect(url_for("dashboard"))


# ------------------------------------------------------------------ jobs
def get_job(c, job_id):
    row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        abort(404)
    return dict(row)


@app.route("/job/<int:job_id>")
def job_detail(job_id):
    c = conn()
    job = get_job(c, job_id)
    application = c.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    set_active_job(c, job_id)   # the Fill button fills forms for the job you looked at last
    cfg = load_config()
    if not job.get("cover_letter") and job.get("status") != "skipped":
        # Open a job and its cover letter is already written for you – no button to press.
        try:
            job["cover_letter"], _ = write_letter(job, cfg["profile"], cv_text(cfg), cfg.get("ai"))
            db.update_job(c, job_id, cover_letter=job["cover_letter"])
        except Exception:
            pass
    c.commit()
    c.close()
    saved = request.args.get("saved")
    if saved and not (letters_folder(cfg) / saved).exists():
        saved = None
    return render_template("job.html", job=job, application=application, profile=cfg["profile"],
                           answers=short_answers(job, cfg["profile"]), saved=saved,
                           letters_dir=str(letters_folder(cfg)))


@app.post("/job/<int:job_id>/letter")
def job_letter(job_id):
    cfg = load_config()
    c = conn()
    job = get_job(c, job_id)
    letter, method = write_letter(job, cfg["profile"], cv_text(cfg), cfg.get("ai"))
    db.update_job(c, job_id, cover_letter=letter, status="prepared" if job["status"] in ("new", "shortlisted") else job["status"])
    c.commit()
    c.close()
    job["cover_letter"] = letter
    saved = archive_letter(job, cfg)
    flash(f"Cover letter written ({method}) and saved in your Cover Letters folder as “{saved.name}”. Read it through before you use it."
          if saved else f"Cover letter written ({method}). Read it through and edit before you use it.")
    return redirect(url_for("job_detail", job_id=job_id) + "#letter")


@app.post("/job/<int:job_id>/letter/save")
def job_letter_save(job_id):
    c = conn()
    get_job(c, job_id)
    job = get_job(c, job_id)
    db.update_job(c, job_id, cover_letter=request.form.get("cover_letter", ""))
    c.commit()
    c.close()
    job["cover_letter"] = request.form.get("cover_letter", "")
    saved = archive_letter(job, load_config())
    flash(f"Cover letter saved – also in your Cover Letters folder as “{saved.name}”." if saved else "Cover letter saved.")
    return redirect(url_for("job_detail", job_id=job_id) + "#letter")


@app.post("/job/<int:job_id>/advert")
def job_advert(job_id):
    """You pasted the job description (and corrected the company): re-score, write the letter, file it."""
    cfg = load_config()
    c = conn()
    job = get_job(c, job_id)
    text = (request.form.get("description") or "").strip()
    company = (request.form.get("company") or "").strip() or job.get("company")
    if len(text) < 150:
        c.close()
        flash("That looks too short to be the job description – paste the whole advert.")
        return redirect(url_for("job_detail", job_id=job_id))
    job.update(description=text[:20000], company=company)
    score, reasons = score_job(job)
    letter, method = write_letter(job, cfg["profile"], cv_text(cfg), cfg.get("ai"))
    db.update_job(c, job_id, description=job["description"], company=company, score=score,
                  score_reasons=" · ".join(reasons), cover_letter=letter,
                  status="prepared" if job["status"] in ("new", "shortlisted") else job["status"])
    c.commit()
    c.close()
    job["cover_letter"] = letter
    saved = archive_letter(job, cfg)
    flash(f"Read the job description, scored it {score}% and wrote your cover letter"
          + (f" – saved in your Cover Letters folder as “{saved.name}”." if saved else "."))
    return redirect(url_for("job_detail", job_id=job_id) + "#letter")


@app.post("/job/<int:job_id>/docx")
def job_docx(job_id):
    cfg = load_config()
    c = conn()
    job = get_job(c, job_id)
    letter = request.form.get("cover_letter") or job.get("cover_letter")
    if not letter:
        flash("Write the cover letter first.")
        return redirect(url_for("job_detail", job_id=job_id))
    db.update_job(c, job_id, cover_letter=letter)
    c.commit()
    folder = letters_folder(cfg)
    try:
        path = save_docx(letter, job, cfg["profile"], folder)
    except PermissionError:
        c.close()
        flash("Couldn't save the Word file – it's probably open in Word. Close it and try again.")
        return redirect(url_for("job_detail", job_id=job_id))
    except Exception as e:
        c.close()
        flash(f"Couldn't save the Word file: {e}")
        return redirect(url_for("job_detail", job_id=job_id))
    c.close()
    return redirect(url_for("job_detail", job_id=job_id, saved=path.name) + "#letter")


def letter_file(job: dict, letter: str, profile: dict, fmt: str) -> tuple[bytes, str, str]:
    """The cover letter as a ready-to-attach PDF or Word file: (bytes, file name, type)."""
    company = safe_filename(job.get("company") or job.get("title") or "Job")
    base = f"{profile.get('name') or 'My'} Cover Letter - {company}"
    if fmt == "docx":
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = save_docx(letter, job, profile, td, base + ".docx")
            data = path.read_bytes()
        return data, base + ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return letter_pdf(letter, profile), base + ".pdf", "application/pdf"


@app.route("/job/<int:job_id>/letter.<fmt>", methods=["GET", "POST"])
def job_letter_download(job_id, fmt):
    """Download the cover letter as PDF or Word – any edits in the box are saved first."""
    if fmt not in ("pdf", "docx"):
        abort(404)
    cfg, c = load_config(), conn()
    job = get_job(c, job_id)
    if request.method == "POST" and request.form.get("cover_letter", "").strip():
        same_site_only()
        job["cover_letter"] = request.form["cover_letter"]
        db.update_job(c, job_id, cover_letter=job["cover_letter"])
        c.commit()
    if not job.get("cover_letter"):
        job["cover_letter"], _ = write_letter(job, cfg["profile"], cv_text(cfg), cfg.get("ai"))
        db.update_job(c, job_id, cover_letter=job["cover_letter"])
        c.commit()
    c.close()
    import io
    data, name, mime = letter_file(job, job["cover_letter"], cfg["profile"], fmt)
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=name)


def letters_folder(cfg) -> Path:
    folder = cfg["profile"].get("cover_letter_folder") or ""
    if not folder or not Path(folder).anchor and os.name == "nt":
        folder = Path.home() / "Documents" / "Cover Letters"
    return Path(folder)


def archive_letter(job: dict, cfg: dict) -> Path | None:
    """Keep a copy of the letter used for this job in your Cover Letters folder: PDF (what employers get) + Word."""
    letter = job.get("cover_letter")
    if not letter:
        return None
    profile = cfg["profile"]
    folder = letters_folder(cfg)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        base = f"{profile.get('name', 'Cover')} Cover Letter - {safe_filename(job.get('company') or 'Job')}"
        role = safe_filename(job.get("title") or "")
        if role:
            base += f" - {role[:60]}"
        pdf = folder / f"{base}.pdf"
        pdf.write_bytes(letter_pdf(letter, profile))
        try:
            save_docx(letter, job, profile, folder, f"{base}.docx")
        except Exception:
            pass   # e.g. the Word copy is open in Word – the PDF is what matters
        return pdf
    except Exception:
        return None


@app.post("/open")
def open_saved():
    """Opens a saved cover letter (or its folder) on this PC. Only files in the cover-letter folder."""
    folder = letters_folder(load_config()).resolve()
    name = request.form.get("name", "")
    target = (folder / name).resolve() if name else folder
    if folder not in [target, *target.parents] or not target.exists():
        abort(404)
    if hasattr(os, "startfile"):
        os.startfile(str(target))  # Windows: opens in Word / File Explorer
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/job/<int:job_id>/applied")
def job_applied(job_id):
    c = conn()
    job = get_job(c, job_id)
    existing = c.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    if existing:
        db.update_application(c, existing["id"], status="applied", applied_on=date.today().isoformat())
    else:
        db.add_application(c, job_id=job_id, company=job["company"] or "Unknown", role=job["title"],
                           location=job["location"], salary_text=job["salary_text"], url=job["url"],
                           applied_on=date.today().isoformat(), status="applied")
    db.update_job(c, job_id, status="applied")
    c.commit()
    c.close()
    flash(f"Marked as applied: {job['title']} at {job['company']}.")
    return redirect(url_for("jobs_page"))


@app.post("/job/<int:job_id>/skip")
def job_skip(job_id):
    c = conn()
    get_job(c, job_id)
    db.update_job(c, job_id, status="skipped")
    c.commit()
    c.close()
    flash("Job hidden.")
    return redirect(url_for("jobs_page"))


# ------------------------------------------------------------------ stop the job emails (one click, no sign-in)
def _stop_signer():
    from itsdangerous import URLSafeSerializer
    return URLSafeSerializer(app.secret_key, salt="email-stop")


def email_stop_link(uid) -> str:
    base = os.environ.get("JOBHUNT_URL", "").rstrip("/") or ("https://www.jhhq.co.uk" if HOSTED else "")
    return f"{base}/email/stop/{_stop_signer().dumps(str(uid))}" if base else ""


notify.STOP_LINK = email_stop_link


@app.route("/email/stop/<token>", methods=["GET", "POST"])
def email_stop(token):
    """The link at the bottom of every job email: turns the emails off. The link only works for the person it was sent to."""
    try:
        uid = _stop_signer().loads(token)
    except Exception:
        abort(404)
    done = False
    if request.method == "POST":
        from jobhunt.config import as_user
        with as_user(int(uid) if str(uid).isdigit() else uid):
            s = accounts.load_settings(current_user_id())
            s.setdefault("email", {})["enabled"] = False
            accounts.save_settings(s, current_user_id())
        done = True
    return render_template("email_stop.html", token=token, done=done)


# ------------------------------------------------------------------ review queue
# Strong matches get their cover letter written ahead of time; you go through them one by one on /review, check
# the letter, open the employer's form (the browser assistant fills it) and press Submit there yourself. Job Hunt
# HQ never sends an application on its own.
REVIEW_MIN = 70


def review_candidates(c) -> list[dict]:
    return [dict(r) for r in c.execute(
        "SELECT * FROM jobs WHERE status IN ('new', 'shortlisted', 'prepared') AND score >= ? "
        "AND id NOT IN (SELECT job_id FROM applications WHERE job_id IS NOT NULL) ORDER BY score DESC, id DESC",
        (REVIEW_MIN,))]


def prepare_queue(c, limit: int = 10) -> int:
    """Write cover letters for the best strong matches that don't have one yet."""
    cfg = load_config()
    done = 0
    for job in review_candidates(c):
        if done >= limit:
            break
        if job.get("cover_letter"):
            continue
        try:
            letter, _ = write_letter(job, cfg["profile"], cv_text(cfg), cfg.get("ai"))
        except Exception:
            continue
        db.update_job(c, job["id"], cover_letter=letter, status="prepared")
        done += 1
    c.commit()
    return done


def _review_order(jobs: list[dict]) -> list[dict]:
    later = session.get("review_later") or []
    return sorted(jobs, key=lambda j: (j["id"] in later, later.index(j["id"]) if j["id"] in later else 0))


@app.route("/review")
def review_page():
    c = conn()
    prepare_queue(c, limit=3)                   # the next few are always ready, even before the overnight run
    queue = _review_order(review_candidates(c))
    waiting = [dict(r) for r in c.execute(
        "SELECT a.id, a.role, a.company, a.job_id, j.apply_url, j.url FROM applications a LEFT JOIN jobs j ON j.id = a.job_id "
        "WHERE a.status = 'ready' ORDER BY a.updated_at DESC LIMIT 20")]
    c.close()
    job = queue[0] if queue else None
    cfg = load_config()
    return render_template("review.html", job=job, queue=queue, waiting=waiting, profile=cfg["profile"],
                           answers=short_answers(job, cfg["profile"]) if job else [], nav_on="jobs_page")


@app.post("/review/<int:job_id>/approve")
def review_approve(job_id):
    """You've checked it: it goes on your list as 'not sent yet' (the page opens the employer's form in a new tab)."""
    c = conn()
    job = get_job(c, job_id)
    if not c.execute("SELECT 1 FROM applications WHERE job_id = ?", (job_id,)).fetchone():
        db.add_application(c, job_id=job_id, company=job["company"] or "Unknown", role=job["title"],
                           location=job["location"], salary_text=job["salary_text"], url=job["url"], status="ready")
    db.update_job(c, job_id, status="prepared")
    set_active_job(c, job_id)                   # so the assistant and Fill button fill this job's form
    c.commit()
    c.close()
    return ("", 204)


@app.post("/review/<int:job_id>/sent")
def review_sent(job_id):
    c = conn()
    job = get_job(c, job_id)
    row = c.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    if row:
        db.update_application(c, row["id"], status="applied", applied_on=date.today().isoformat())
    else:
        db.add_application(c, job_id=job_id, company=job["company"] or "Unknown", role=job["title"],
                           location=job["location"], salary_text=job["salary_text"], url=job["url"],
                           applied_on=date.today().isoformat(), status="applied")
    db.update_job(c, job_id, status="applied")
    c.commit()
    c.close()
    flash(f"Marked as sent: {job['title']} at {job['company']}.")
    return redirect(url_for("review_page"))


@app.post("/review/<int:job_id>/skip")
def review_skip(job_id):
    c = conn()
    get_job(c, job_id)
    db.update_job(c, job_id, status="skipped")
    c.commit()
    c.close()
    return redirect(url_for("review_page"))


@app.post("/review/<int:job_id>/later")
def review_later(job_id):
    later = [i for i in (session.get("review_later") or []) if i != job_id][-200:]
    session["review_later"] = later + [job_id]
    return redirect(url_for("review_page"))


def save_and_prepare(data: dict, prepare: bool = True) -> tuple[int, bool]:
    """Store a job from a link or the browser button, score it and (unless prepare=False, used for a whole
    page of search results) write its cover letter."""
    cfg = load_config()
    job = manual_job(data.get("title", ""), data.get("company", ""), canonical_url(data.get("url", "")),
                     data.get("location", ""), data.get("salary", ""), data.get("description", ""),
                     (data.get("closes") or "")[:10] or None)
    job["posted"] = parse_posted(data.get("posted"))   # None when the page didn't say
    job["score"], reasons = score_job(job)
    job["score_reasons"] = " · ".join(reasons)
    job["status"] = "shortlisted" if prepare else "new"
    c = conn()
    job_id, created = db.upsert_job(c, job)
    existing = get_job(c, job_id)
    updates = {}
    if not created and len(job["description"]) > len(existing.get("description") or ""):
        updates.update(description=job["description"], score=job["score"], score_reasons=job["score_reasons"])
        existing.update(updates)
    if job["posted"] and not existing.get("posted"):
        updates["posted"] = job["posted"]
    apply_url = (data.get("apply_url") or "").strip()
    if apply_url.startswith("http") and not existing.get("apply_url"):
        updates["apply_url"] = apply_url
    if prepare and not existing.get("cover_letter"):
        letter, _ = write_letter(existing, cfg["profile"], cv_text(cfg), cfg.get("ai"))
        updates["cover_letter"] = letter
        if existing["status"] in ("new", "shortlisted"):
            updates["status"] = "prepared"
    if updates:
        db.update_job(c, job_id, **updates)
    if prepare:
        set_active_job(c, job_id)
    c.commit()
    c.close()
    return job_id, created


@app.route("/add", methods=["GET", "POST"])
def add_job():
    if request.method == "POST":
        f = request.form.to_dict()
        if f.get("url") and not (f.get("title") and f.get("company")):
            try:
                fetched = fetch_job(f["url"])
                f = {**fetched, **{k: v for k, v in f.items() if v}}
            except Exception as e:
                flash(str(e))
                return render_template("add.html", form=f)
        if not f.get("title") or not f.get("company"):
            flash("Add at least the job title and company.")
            return render_template("add.html", form=f)
        job_id, created = save_and_prepare(f)
        flash("Job added and your application pack is ready." if created else "You already had this job – it's updated.")
        return redirect(url_for("job_detail", job_id=job_id))
    return render_template("add.html", form={})


@app.route("/import")
def import_page():
    """Opened by the 'Send to Job Hunt HQ' button; the job arrives in the page address after '#'."""
    return render_template("import.html")


@app.post("/api/import")
def api_import():
    data = request.get_json(silent=True) or {}
    if isinstance(data.get("jobs"), list):   # a whole page of LinkedIn / Indeed search results
        added = updated = 0
        for item in data["jobs"][:100]:
            item = {k: str(v or "").strip() for k, v in item.items()} if isinstance(item, dict) else {}
            if not item.get("title") or not item.get("company"):
                continue
            _, created = save_and_prepare(item, prepare=False)   # letters are written when you open a job
            added += created
            updated += not created
        return {"job_url": url_for("jobs_page", posted="1" if data.get("recent") else None, sort="newest"),
                "added": added, "updated": updated}
    data = {k: str(v or "").strip() for k, v in data.items()}
    if not data.get("title"):
        return {"error": "Couldn't find the job title on that page."}, 400
    if not data.get("company"):
        data["company"] = "Unknown company"
    job_id, created = save_and_prepare(data)
    return {"job_url": url_for("job_detail", job_id=job_id), "created": created}


def bookmarklet_href(filename: str = "bookmarklet.js", base: str | None = None) -> str:
    from urllib.parse import quote
    with open(os.path.join(app.static_folder, filename), encoding="utf-8") as f:
        src = f.read()
    if filename == "fill.js":   # the form logic is shared with the Apply-for-me robot
        with open(os.path.join(app.static_folder, "fill_core.js"), encoding="utf-8") as f:
            src = f.read() + "\n" + src
    port = str(load_config().get("app", {}).get("port", 5055))
    if not base and HOSTED:
        base = site_url()
    src = src.replace("__BASE__", base or f"http://127.0.0.1:{port}")
    src = src.replace("__PORT__", port)
    src = src.replace("__TOKEN__", access_token())
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = " ".join(line.strip() for line in src.splitlines() if line.strip())
    return "javascript:" + quote(src, safe="(){}[];,.=:'!?<>+-*/&|_$")


# ------------------------------------------------------------------ "Fill this application" button
# The button (running on the employer's site) opens /bridge in a small window. The bridge page asks this
# app for the details – checking the private token – passes them back to the form and closes.

def check_token(token=None):
    import hmac
    if not hmac.compare_digest(str(token if token is not None else request.args.get("token", "")), access_token()):
        abort(403)


def set_active_job(c, job_id):
    db.set_meta(c, "active_job", job_id)


def split_address(profile: dict) -> dict:
    parts = [p.strip() for p in (profile.get("address") or "").split(",") if p.strip()]
    postcode = next((p for p in parts if re.fullmatch(r"[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}", p.upper())), "")
    return {
        "address_line": profile.get("address_line") or (parts[0] if parts else ""),
        "city": profile.get("city") or (parts[1] if len(parts) > 1 else ""),
        "postcode": profile.get("postcode") or postcode,
    }


@app.route("/bridge")
def bridge_page():
    return render_template("bridge.html")


@app.post("/api/bridge")
def api_bridge():
    data = request.get_json(silent=True) or {}
    check_token(data.get("token", ""))
    if data.get("action") == "applied":
        mark_applied(int(data.get("job_id") or 0), str(data.get("page") or ""))
        return {"ok": True}
    return build_pack(int(data.get("job_id") or 0) or None, str(data.get("page") or ""))


# ------------------------------------------------------------------ the browser assistant (extension)
def _find_job(c, url: str, title: str, company: str):
    url = canonical_url(url) if url.startswith("http") else url
    row = None
    if url:
        row = c.execute("SELECT * FROM jobs WHERE url = ? OR apply_url = ? ORDER BY updated_at DESC LIMIT 1",
                        (url, url)).fetchone()
    if not row and title and company:          # never guess the employer from the job title alone
        row = c.execute("SELECT * FROM jobs WHERE lower(title) = lower(?) AND lower(company) = lower(?) "
                        "ORDER BY updated_at DESC LIMIT 1", (title, company)).fetchone()
    return dict(row) if row else None


def _ask_ai(question: str, job: dict, cfg: dict) -> str:
    """A free question for the assistant ("how should I answer this?", "what should I stress?") – answered from
    the person's own CV and career details and the advert. Needs an Anthropic key on the server."""
    ai = cfg.get("ai") or {}
    if not ai.get("anthropic_api_key"):
        return ""
    import json as _json

    import requests as _rq
    from jobhunt import career as _career
    prompt = ("You are a friendly, honest job-application assistant helping the candidate below. Answer their question "
              "in UK English, briefly and practically. Use only facts from their details – never invent experience. "
              "If you suggest wording for a form, keep it in their voice.\n\n"
              f"QUESTION: {question}\n\nJOB: {job.get('title')} at {job.get('company')}\nADVERT:\n"
              f"{(job.get('description') or '')[:5000]}\n\nTHEIR DETAILS:\n"
              f"{_json.dumps(_career.load(), ensure_ascii=False)[:8000]}\n\nCV:\n{cv_text(cfg)[:6000]}")
    try:
        r = _rq.post("https://api.anthropic.com/v1/messages",
                     headers={"x-api-key": ai["anthropic_api_key"], "anthropic-version": "2023-06-01",
                              "content-type": "application/json"},
                     json={"model": ai.get("model", "claude-haiku-5-5"), "max_tokens": 700,
                           "messages": [{"role": "user", "content": prompt}]}, timeout=45)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
    except Exception:
        return ""


def _closest_facts(text: str, limit: int = 3) -> list[str]:
    from jobhunt.advert import _facts, _words
    from jobhunt.generic import facts as history_facts
    want = set(re.findall(r"[a-z]{4,}", (text or "").lower())) - {"with", "will", "your", "that", "this", "have", "from",
                                                                   "they", "their", "what", "about", "were", "work"}
    scored, seen = [], set()
    for i, (keys, fact) in enumerate(list(_facts()) + list(history_facts())):
        if fact in seen:
            continue
        seen.add(fact)
        w = _words(fact + " " + " ".join(keys))
        hits = sum(1 for k in want if f" {k} " in w)
        if hits >= 2:
            scored.append((hits, -i, fact))
    scored.sort(reverse=True)
    return [f for _, _, f in scored[:limit]]


def _ask_offline(question: str, job: dict, cfg: dict) -> str:
    """The assistant's answer without AI: drafts form answers, picks the experience that fits the advert,
    and answers the usual questions from the person's own details."""
    from jobhunt.advert import matches
    from jobhunt.answers import BEHAVIOURAL, suggest
    from jobhunt.generic import qualifications_line
    q = question.strip()
    ql = q.lower()
    profile = cfg["profile"]
    desc = job.get("description") or ""
    if re.search(r"cover letter|covering letter|supporting statement", ql):
        return job.get("cover_letter") or write_letter(job, profile, cv_text(cfg), cfg.get("ai"))[0]
    if re.search(r"salary|pay|money", ql):
        mine = profile.get("salary_expectation") or "not set yet (add it in My settings)"
        theirs = job.get("salary_text") or (re.search(r"£[\d,]+(?:\.\d+)?(?:\s*[-–]\s*£[\d,]+(?:\.\d+)?)?(?:\s*(?:per|a)\s*\w+)?", desc) or [""])[0]
        return f"Your salary expectation: {mine}." + (f" This advert offers {theirs}." if theirs else "")
    if re.search(r"(fit|match|stress|highlight|mention|strength|best|focus|which (of my )?experience|why (am i|would i|should))", ql):
        pairs = matches(desc, 4) if desc else []
        if pairs:
            lines = [f"• They want: {b}\n  You can point to: {f}" for _, b, f in pairs]
            return "What to stress for this role:\n" + "\n".join(lines)
        best = _closest_facts(desc + " " + (job.get("title") or ""), 4)
        if best:
            return "What to stress for this role:\n" + "\n".join(f"• {f}" for f in best)
    if BEHAVIOURAL.search(ql) or q.endswith("?") or re.search(r"how (do|should) i answer", ql):
        target = re.sub(r"^(how (do|should|would) i answer|help me answer|answer)\s*[:\-]?\s*", "", q, flags=re.I).strip(' "“”')
        c = conn()
        remembered = db.remembered_answers(c)
        c.close()
        fields = {**phone_fields(profile), **{k: profile.get(k, "") for k in ("name", "email", "phone", "current_employer", "current_title",
                                                       "notice_period", "salary_expectation", "right_to_work")}, **split_address(profile)}
        ans, _ = suggest({"label": target, "kind": "textarea", "options": []}, remembered, profile, fields, job,
                         cv_text(cfg), cfg.get("ai"))
        if ans:
            return ans
    pairs = matches(desc, 3) if desc else []
    if pairs:
        return "From the advert, the parts of your experience that fit best:\n" + "\n".join(f"• {f}" for _, _, f in pairs)
    best = _closest_facts(desc + " " + (job.get("title") or ""), 3)
    if best:
        return "From the advert, the parts of your experience that fit best:\n" + "\n".join(f"• {f}" for f in best)
    quals = qualifications_line()
    return ("I couldn't match that to your details yet. Try asking “Which of my experiences fits this role?”, “What should "
            "I stress?”, or paste a question from the form." + (f" Your qualifications: {quals}." if quals else ""))


@app.post("/api/assistant")
def api_assistant():
    """Everything the Job Hunt HQ browser assistant does, for the signed-in person whose token it carries:
    recognise the job on the page, score it, fill the form, suggest answers, and mark it applied.
    It never presses Submit – that's always the person."""
    from jobhunt.answers import suggest
    from jobhunt.matcher import fit_label as _fit
    d = request.get_json(silent=True) or {}
    action = d.get("action")
    cfg = load_config()
    profile = cfg["profile"]
    if action == "hello":
        name = profile.get("name") or (getattr(__import__("flask").g, "user", None) or {}).get("name", "")
        return {"ok": True, "name": name, "first": name.split(" ")[0] if name else "",
                "ai": bool((cfg.get("ai") or {}).get("anthropic_api_key")), "site": request.host_url.rstrip("/")}
    if action == "job":
        title, company = (d.get("title") or "").strip()[:200], (d.get("company") or "").strip()[:200]
        url, desc = (d.get("url") or "").strip(), (d.get("description") or "").strip()[:20000]
        c = conn()
        job = _find_job(c, url, title, company)
        c.close()
        if not job and not (title and len(desc) > 200):
            return {"ok": True, "job": None}
        if not job and not d.get("save"):       # just looking: score it without adding it to their jobs
            from jobhunt.sources import manual_job as _mj
            probe = _mj(title, company, url, d.get("location", ""), d.get("salary", ""), desc)
            sc, why = score_job(probe)
            return {"ok": True, "job": {"id": None, "title": title, "company": company, "score": sc, "fit": _fit(sc),
                                        "reasons": why[:5], "status": None, "has_letter": False, "link": ""}}
        if not job or (desc and len(desc) > len(job.get("description") or "") + 200):
            job_id, _ = save_and_prepare({"title": title or (job or {}).get("title", ""),
                                          "company": company or (job or {}).get("company", ""), "url": url,
                                          "location": d.get("location", ""), "salary": d.get("salary", ""),
                                          "description": desc, "apply_url": d.get("apply_url", "")})
            c = conn()
            job = get_job(c, job_id)
            c.close()
        reasons = [r for r in (job.get("score_reasons") or "").split(" · ") if r]
        return {"ok": True, "job": {"id": job["id"], "title": job["title"], "company": job["company"],
                                    "score": job.get("score"), "fit": _fit(job.get("score") or 0), "reasons": reasons[:5],
                                    "status": job.get("status"), "has_letter": bool(job.get("cover_letter")),
                                    "link": url_for("job_detail", job_id=job["id"], _external=True)}}
    if action in ("pack", "applied"):
        from flask import g as _g
        who = (_g.user or {}).get("username", "?") if _g.get("user") else "?"
        if action == "applied":
            alerts.note("applied", who, f"{who} may be sending bulk automated applications",
                        f"{who} marked {{n}} applications as sent through the assistant in {{minutes}} minutes. That's "
                        "faster than a person normally applies, so it may break the job sites' terms.")
        else:
            alerts.note("fill", who, f"{who} is filling a very large number of forms",
                        f"{who}'s assistant filled {{n}} application forms in {{minutes}} minutes. "
                        "This may be automated or bulk applying.")
    if action == "pack":
        return build_pack(int(d.get("job_id") or 0) or None, str(d.get("page") or ""))
    if action == "answer":
        q = {"label": (d.get("question") or "")[:600], "kind": d.get("kind") or "textarea",
             "options": [str(o)[:200] for o in (d.get("options") or [])][:40], "hint": d.get("hint") or ""}
        c = conn()
        job = get_job(c, int(d["job_id"])) if d.get("job_id") else {"title": "", "company": "", "description": d.get("page_text", "")}
        remembered = db.remembered_answers(c)
        c.close()
        pack_fields = {**phone_fields(profile), **{k: profile.get(k, "") for k in ("name", "email", "phone", "linkedin", "github", "address",
                                                           "current_employer", "current_title", "notice_period",
                                                           "salary_expectation", "right_to_work")}, **split_address(profile)}
        ans, src = suggest(q, remembered, profile, pack_fields, job, cv_text(cfg), cfg.get("ai"))
        note = {"remembered": "An answer you saved before.", "rule": "From your details.",
                "experience": "From your work history – check it reads right.",
                "story": "Built from one of your own examples – make it specific to this employer.",
                "example": "Built from your own work history – fill in the [bracketed] moment so it's a real example.",
                "competency": "From your saved competency answers.", "draft": "A starting draft – personalise it.",
                "ai": "Written with AI from your CV – check every word is true.",
                "own_words": "The employer wants this in your own words, so it's left for you.",
                "": ""}.get(src, "")
        if not ans and not note:
            from jobhunt.answers import PERSONAL
            note = ("This one's personal, so it's left for you to answer." if PERSONAL.search(q["label"]) else
                    "Nothing in your details answers this yet – add your experience on My career (or an example under "
                    "My examples) and ask again.")
        return {"ok": True, "answer": ans or "", "source": src, "note": note}
    if action == "ask":
        c = conn()
        job = get_job(c, int(d["job_id"])) if d.get("job_id") else {"title": "", "company": "", "description": ""}
        c.close()
        question = (d.get("question") or "")[:1000]
        text = _ask_ai(question, job, cfg)
        if text:
            return {"ok": True, "answer": text, "note": "Written with AI from your details – check it before using it."}
        return {"ok": True, "answer": _ask_offline(question, job, cfg),
                "note": "Answered from your own details and the advert."}
    if action in ("letter", "letter_save", "letter_file"):
        c = conn()
        job = get_job(c, int(d.get("job_id") or 0))
        if action == "letter_save" or (action == "letter_file" and (d.get("text") or "").strip()):
            job["cover_letter"] = (d.get("text") or "")[:20000]
            db.update_job(c, job["id"], cover_letter=job["cover_letter"])
        if d.get("rewrite") or not job.get("cover_letter"):
            job["cover_letter"], _ = write_letter(job, profile, cv_text(cfg), cfg.get("ai"))
            db.update_job(c, job["id"], cover_letter=job["cover_letter"])
        c.commit()
        c.close()
        if action == "letter_file":
            import base64
            data, name, mime = letter_file(job, job["cover_letter"], profile, d.get("fmt", "pdf"))
            return {"ok": True, "b64": base64.b64encode(data).decode(), "name": name, "type": mime}
        return {"ok": True, "text": job["cover_letter"]}
    if action == "applied":
        mark_applied(int(d.get("job_id") or 0), str(d.get("page") or ""))
        return {"ok": True}
    abort(400)


@app.route("/assistant")
def assistant_page():
    return render_template("assistant.html", base=(os.environ.get("JOBHUNT_URL") or request.host_url).rstrip("/"),
                           ai=bool((load_config().get("ai") or {}).get("anthropic_api_key")))


@app.route("/assistant/extension.zip")
def assistant_download():
    """The browser extension, already connected to this person's account (their own private key is inside)."""
    import io
    import json
    import zipfile
    here = request.host_url.rstrip("/")                    # the address you downloaded it from always works
    other = (os.environ.get("JOBHUNT_URL") or "").rstrip("/")
    base, alt = here, (other if other and other != here else "")
    folder = Path(app.root_path) / "extension"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, f"Job Hunt HQ Assistant/{p.relative_to(folder).as_posix()}")
        z.write(Path(app.static_folder) / "fill_core.js", "Job Hunt HQ Assistant/fill_core.js")
        z.write(Path(app.static_folder) / "favicon-192.png", "Job Hunt HQ Assistant/icon.png")
        z.writestr("Job Hunt HQ Assistant/config.js",
                   "/* Your connection to Job Hunt HQ – keep this private. */\nvar JHQ_CONFIG = " +
                   json.dumps({"base": base, "alt": alt, "token": access_token()}) + ";\n")
    return send_file(io.BytesIO(buf.getvalue()), mimetype="application/zip", as_attachment=True,
                     download_name="Job Hunt HQ Assistant.zip")


JOB_BOARDS = ("linkedin.com", "indeed.", "thetalentworld.co.uk", "reed.co.uk/jobs", "adzuna.", "charityjob.")


def application_link(page: str) -> str | None:
    """The employer's real application page (Workday, Greenhouse, Morgan Law…), not a job board."""
    if not page.startswith("http") or any(b in page for b in JOB_BOARDS) or "127.0.0.1" in page:
        return None
    page = page.split("#")[0]
    # Workday: keep the job page rather than a step deep inside the application
    page = re.sub(r"(/job/[^/]+/[^/?]+)/apply.*$", r"\1/apply", page)
    return page


def build_pack(job_id=None, page: str = "") -> dict:
    cfg, c = load_config(), conn()
    profile = cfg["profile"]
    job_id = job_id or int(db.get_meta(c, "active_job", 0) or 0)
    job = None
    if job_id:
        row = c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        job = dict(row) if row else None
    if not job:
        row = c.execute("SELECT * FROM jobs WHERE status IN ('prepared', 'shortlisted', 'new') "
                        "ORDER BY updated_at DESC LIMIT 1").fetchone()
        job = dict(row) if row else {"id": 0, "title": "", "company": "", "description": ""}
    if job["id"] and not job.get("cover_letter"):
        job["cover_letter"], _ = write_letter(job, profile, cv_text(cfg), cfg.get("ai"))
        db.update_job(c, job["id"], cover_letter=job["cover_letter"])
    if job["id"]:
        set_active_job(c, job["id"])
        link = application_link(page)
        if link and job.get("apply_url") != link:
            db.update_job(c, job["id"], apply_url=link)
            job["apply_url"] = link
    recent = [dict(r) for r in c.execute(
        "SELECT id, title, company FROM jobs WHERE status != 'skipped' ORDER BY updated_at DESC LIMIT 15")]
    if job["id"] and job["id"] not in [r["id"] for r in recent]:
        recent.insert(0, {"id": job["id"], "title": job["title"], "company": job["company"]})
    c.commit()
    c.close()
    name = profile.get("name", "")
    first, _, last = name.partition(" ")
    answers = short_answers(job, profile)
    has_cv = cv_file(profile) is not None
    return {
        "job": {"id": job["id"], "title": job["title"], "company": job["company"],
                "apply_url": job.get("apply_url") or ""},
        "recent": recent,
        "fields": {**phone_fields(profile), **{k: profile.get(k, "") for k in ("name", "email", "phone", "linkedin", "github", "address",
                                                         "current_employer", "current_title", "notice_period",
                                                         "salary_expectation", "right_to_work")},
                   "first_name": first, "last_name": last, **split_address(profile)},
        "message": form_message(job, profile),
        "cover_letter": job.get("cover_letter") or "",
        "why_role": answers[0][1], "why_company": answers[1][1], "summary": answers[2][1],
        "answers": answers,
        "files": {"cv": "/files/cv" if has_cv else None,
                  "letter": f"/files/letter/{job['id']}" if job.get("cover_letter") else None},
    }


@app.route("/files/cv")
def file_cv():
    check_token()
    path = cv_file(load_config()["profile"])
    if not path:
        abort(404)
    resp = send_file(path, mimetype="application/pdf" if path.suffix.lower() == ".pdf" else None)
    resp.headers["X-Filename"] = quote_name(path.name)
    return resp


@app.route("/files/letter/<int:job_id>")
def file_letter(job_id):
    check_token()
    cfg, c = load_config(), conn()
    job = get_job(c, job_id)
    c.close()
    if not job.get("cover_letter"):
        abort(404)
    pdf = letter_pdf(job["cover_letter"], cfg["profile"])
    archive_letter(job, cfg)
    from flask import Response
    company = safe_filename(job.get("company") or job.get("title") or "Job")
    resp = Response(pdf, mimetype="application/pdf")
    resp.headers["X-Filename"] = quote_name(f"{cfg['profile'].get('name', 'Cover')} Cover Letter - {company}.pdf")
    return resp


def quote_name(name: str) -> str:
    from urllib.parse import quote
    return quote(name)


def mark_applied(job_id: int, page: str = ""):
    c = conn()
    job = get_job(c, job_id)
    archive_letter(job, load_config())
    existing = c.execute("SELECT id FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    if existing:
        db.update_application(c, existing["id"], status="applied", applied_on=date.today().isoformat())
    else:
        db.add_application(c, job_id=job_id, company=job["company"] or "Unknown", role=job["title"],
                           location=job["location"], salary_text=job["salary_text"], url=job["url"],
                           applied_on=date.today().isoformat(), status="applied",
                           notes=f"Applied via {page[:200]}" if page else None)
    db.update_job(c, job_id, status="applied")
    c.commit()
    c.close()


# ------------------------------------------------------------------ applications
APP_GROUPS = [
    ("all", "All", None),
    ("waiting", "Waiting to hear back", ("applied", "acknowledged")),
    ("forward", "Moving forward", ("pre_screen", "assessment", "interview", "second_stage")),
    ("offer", "Job offers", ("offer",)),
    ("rejected", "Rejected", ("rejected",)),
    ("ready", "Not sent yet", ("ready",)),
    ("withdrawn", "Withdrawn", ("withdrawn",)),
]
HISTORIES: dict = {}


def history_state(uid=None) -> dict:
    """Progress of this person's 2026 email import."""
    uid = uid if uid is not None else current_user_id()
    return HISTORIES.setdefault(uid, {"running": False, "done": 0, "totals": [], "created": 0, "updated": 0,
                                      "emails": 0, "message": ""})


# ------------------------------------------------------------------ interview prep
INTERVIEW_STATUSES = ("pre_screen", "assessment", "interview", "second_stage", "offer")


def _interview_target(c, target: str) -> tuple[dict, dict | None, str]:
    """The job to practise for: app:<id> (an application), job:<id> (a saved job) or general (your kind of work)."""
    cfg = load_config()
    kind, _, ident = (target or "general").partition(":")
    app_row = None
    if kind == "app" and ident.isdigit():
        r = c.execute("SELECT * FROM applications WHERE id = ?", (int(ident),)).fetchone()
        if r:
            app_row = dict(r)
            jr = c.execute("SELECT * FROM jobs WHERE id = ?", (app_row["job_id"],)).fetchone() if app_row.get("job_id") else None
            job = dict(jr) if jr else {}
            job.update({"title": app_row["role"], "company": app_row["company"]})
            return job, app_row, f"{app_row['role']} at {app_row['company']}"
    if kind == "job" and ident.isdigit():
        jr = c.execute("SELECT * FROM jobs WHERE id = ?", (int(ident),)).fetchone()
        if jr:
            job = dict(jr)
            return job, None, f"{job['title']} at {job['company']}"
    prof, search = cfg.get("profile") or {}, cfg.get("search") or {}
    title = (search.get("keywords") or [prof.get("current_title") or "your next job"])[0]
    return {"title": title, "company": "", "description": ""}, None, f"{title} (any employer)"


def _interview_sectors(job: dict) -> list[str]:
    cfg = load_config()
    titles = [job.get("title") or ""] + list((cfg.get("search") or {}).get("keywords") or [])[:3]
    return occupations.sectors_for([t for t in titles if t])


@app.route("/interview")
def interview_page():
    """Interview prep: practise for the interviews you've been invited to (or any job), with feedback on each answer."""
    c = conn()
    marks = ",".join("?" * len(INTERVIEW_STATUSES))
    rows = [dict(r) for r in c.execute(f"SELECT * FROM applications WHERE status IN ({marks})", INTERVIEW_STATUSES)]
    # Coming up first (soonest at the top); interviews whose date has passed, or that went quiet long ago, go under
    # "Past interviews" so the list shows what you need to prepare for now.
    today = date.today()
    upcoming, past = [], []
    for a in rows:
        a["when"] = parse_loose_date(a.get("next_date"), (a.get("updated_at") or "")[:10])
        changed = (a.get("updated_at") or "")[:10]
        try:
            quiet = (today - date.fromisoformat(changed)).days > 45 if changed else False
        except ValueError:
            quiet = False
        (past if (a["when"] and a["when"] < today) or (not a["when"] and quiet) else upcoming).append(a)
    upcoming.sort(key=lambda a: (a["when"] is None, a["when"] or date.max, a.get("updated_at") or ""))
    past.sort(key=lambda a: a["when"] or date.min, reverse=True)
    waiting = [dict(r) for r in c.execute(
        "SELECT * FROM applications WHERE status IN ('applied', 'acknowledged') ORDER BY COALESCE(applied_on, updated_at) DESC LIMIT 6")]
    history = {r["target"]: dict(r) for r in c.execute(
        "SELECT target, COUNT(*) AS n, ROUND(AVG(score), 1) AS avg, MAX(score) AS best, MAX(created_at) AS last "
        "FROM interview_answers GROUP BY target")}
    recent = [dict(r) for r in c.execute(
        "SELECT target, question, score, created_at FROM interview_answers ORDER BY created_at DESC LIMIT 8")]
    labels = {}
    for r in recent:
        if r["target"] not in labels:
            labels[r["target"]] = _interview_target(c, r["target"])[2]
    c.close()
    return render_template("interview.html", upcoming=upcoming, past=past, waiting=waiting, history=history, recent=recent,
                           labels=labels, ai=bool((load_config().get("ai") or {}).get("anthropic_api_key")))


@app.route("/interview/practice")
def interview_practice():
    from jobhunt import career as _career
    from jobhunt import interview as _iv
    target = request.args.get("t", "general")
    if not re.fullmatch(r"general|app:\d+|job:\d+", target):
        target = "general"
    seed = int(request.args["seed"]) if request.args.get("seed", "").isdigit() else 0
    c = conn()
    job, app_row, label = _interview_target(c, target)
    key = f"iq:{target}:{seed}"
    cached = db.get_meta(c, key)
    questions = json.loads(cached) if cached else None
    if not questions:
        sectors = _interview_sectors(job)
        questions = _iv.ai_questions(job, _career.load(), sectors, load_config().get("ai") or {}) or \
            _iv.offline_questions(job, sectors, 8, seed)
        db.set_meta(c, key, json.dumps(questions))
        c.commit()
    done = {}
    for r in c.execute("SELECT question, score, answer, feedback FROM interview_answers WHERE target = ? ORDER BY created_at",
                       (target,)):
        done[r["question"]] = {"score": r["score"], "answer": r["answer"]}
    c.close()
    return render_template("interview_practice.html", questions=questions, done=done, target=target, seed=seed,
                           label=label, job=job, application=app_row)


@app.post("/api/interview/rate")
def api_interview_rate():
    from jobhunt import career as _career
    from jobhunt import interview as _iv
    from jobhunt.answers import example_answer
    same_site_only()
    d = request.get_json(silent=True) or {}
    target = str(d.get("target") or "general")
    question, kind = str(d.get("question") or "")[:500], str(d.get("kind") or "competency")[:20]
    answer = str(d.get("answer") or "").strip()[:8000]
    if not question or not answer:
        return {"error": "Write or say your answer first."}, 400
    cfg = load_config()
    c = conn()
    job, _, _ = _interview_target(c, target)
    result = _iv.rate(question, kind, answer, job, _career.load(), cfg.get("ai") or {})
    if kind not in ("closing",):
        result["examples"] = _closest_facts(question + " " + (job.get("description") or "")[:1500], 3)
    if kind == "competency" and not result.get("improved"):
        try:
            result["draft"] = example_answer(question, job, cfg.get("profile") or {})
        except Exception:
            result["draft"] = ""
    c.execute("INSERT INTO interview_answers (target, question, kind, answer, score, feedback, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (target, question, kind, answer, result["score"], json.dumps(result), db.now()))
    c.commit()
    c.close()
    return result


@app.route("/applications")
def applications_page():
    c = conn()
    group = request.args.get("show", "all")
    q = request.args.get("q", "").strip().lower()
    # One pass over the emails (indexed), not one sub-query per application – this page has to stay quick with
    # thousands of applications.
    apps = [dict(r) for r in c.execute(
        "SELECT a.*, COALESCE(e.n, 0) AS n_emails, e.last AS last_email FROM applications a "
        "LEFT JOIN (SELECT application_id, COUNT(*) AS n, MAX(received_at) AS last FROM events "
        "WHERE application_id IS NOT NULL GROUP BY application_id) e ON e.application_id = a.id")]
    today = date.today()
    for a in apps:
        a["last"] = (a.get("last_email") or "")[:10] or a.get("applied_on") or (a.get("updated_at") or "")[:10]
        try:
            a["days"] = (today - date.fromisoformat(a["applied_on"])).days if a.get("applied_on") else None
        except ValueError:
            a["days"] = None
    counts = {key: sum(1 for a in apps if not sts or a["status"] in sts) for key, _, sts in APP_GROUPS}
    sts = dict((k, v) for k, _, v in APP_GROUPS).get(group)
    shown = [a for a in apps if (not sts or a["status"] in sts) and
             (not q or q in f"{a['role']} {a['company']} {a.get('location') or ''}".lower())]
    shown.sort(key=lambda a: (a["applied_on"] or a["last"] or ""), reverse=True)
    try:
        limit = max(50, min(2000, int(request.args.get("n", 50))))
    except ValueError:
        limit = 50
    more = max(0, len(shown) - limit)
    shown = shown[:limit]
    events = {}
    ids = [a["id"] for a in shown]
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        for e in c.execute("SELECT application_id, gmail_id, received_at, sender, subject, snippet, category FROM events "
                           f"WHERE application_id IN ({','.join('?' * len(part))}) ORDER BY received_at", part):
            events.setdefault(e["application_id"], []).append(dict(e))
    c.close()
    return render_template("applications.html", apps=shown, groups=APP_GROUPS, counts=counts, group=group, q=q,
                           more=more, limit=limit,
                           events=events, history=history_state(), total=len(apps))


@app.post("/applications/import")
def applications_import():
    same_site_only()
    cfg = load_config()
    if history_state()["running"]:
        return redirect(url_for("applications_page"))
    if not gmail_method(cfg):
        flash("Connect Gmail on the Setup page first, then import your history.")
        return redirect(url_for("applications_page"))

    start_history_import(cfg, rebuild=request.form.get("rebuild") == "1")
    return redirect(url_for("applications_page"))


def start_history_import(cfg, rebuild=False):
    """Read every job email since 1 January in the background (optionally starting the email side afresh)."""
    uid = current_user_id()
    HISTORY = history_state(uid)
    if HISTORY["running"]:
        return

    def run():
        from jobhunt.gmail_sync import link_existing, reset_for_rebuild, sync
        HISTORY.update(running=True, done=0, totals=[], created=0, updated=0, emails=0,
                       message="Looking through your emails since 1 January…")
        token = set_user(uid)
        c = db.connect()
        try:
            if rebuild:
                reset_for_rebuild(c)
                c.commit()
            st = sync(c, cfg, history=True, progress=HISTORY, log=lambda m: None)
            st2 = link_existing(c, log=lambda m: None)
            c.commit()
            HISTORY["message"] = (f"Done: read {st['emails']} emails, added {st['created'] + st2['created']} applications "
                                  f"and updated {st['updated'] + st2['updated']}.")
            db.set_meta(c, "history_imported", db.now())
            c.commit()
        except Exception as e:
            HISTORY["message"] = f"The import stopped: {e}"
        finally:
            c.close()
            HISTORY["running"] = False
            from jobhunt.config import reset_user
            reset_user(token)
    HISTORY["running"] = True
    threading.Thread(target=run, daemon=True).start()


@app.get("/api/history")
def history_api():
    h = history_state()
    return {k: h[k] for k in ("running", "done", "created", "updated", "emails", "message")} | \
           {"total": sum(h.get("totals") or [])}


@app.post("/applications/add")
def application_add():
    """An application with no email trail (e.g. a college or council portal)."""
    same_site_only()
    f = {k: request.form.get(k, "").strip() for k in ("role", "company", "applied_on", "status", "location")}
    if not f["role"] or not f["company"]:
        flash("Add at least the role and the employer.")
        return redirect(url_for("applications_page"))
    c = conn()
    db.add_application(c, role=f["role"], company=f["company"], location=f["location"] or None,
                       applied_on=f["applied_on"] or date.today().isoformat(),
                       status=f["status"] if f["status"] in db.STATUS_LABELS else "applied", source="manual")
    c.commit()
    c.close()
    flash(f"Added {f['role']} at {f['company']}.")
    return redirect(url_for("applications_page"))


@app.post("/application/<int:app_id>/edit")
def application_edit(app_id):
    same_site_only()
    c = conn()
    fields = {k: request.form[k].strip() for k in ("role", "company") if request.form.get(k, "").strip()}
    if fields:
        db.update_application(c, app_id, **fields)
        c.commit()
    c.close()
    flash("Saved.")
    return redirect(request.referrer or url_for("applications_page"))


@app.post("/application/<int:app_id>/remove")
def application_remove(app_id):
    """'This isn't an application': take it off the list and don't add it again from later emails."""
    same_site_only()
    from jobhunt.gmail_sync import ignore_application
    c = conn()
    row = c.execute("SELECT company, role FROM applications WHERE id = ?", (app_id,)).fetchone()
    if row:
        ignore_application(c, row["company"], row["role"])
        c.execute("UPDATE events SET application_id = NULL WHERE application_id = ?", (app_id,))
        c.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        c.commit()
        flash(f"Removed {row['role']} at {row['company']}.")
    c.close()
    return redirect(url_for("applications_page", show=request.form.get("show", "all")))


@app.post("/application/<int:app_id>")
def application_update(app_id):
    c = conn()
    if not c.execute("SELECT 1 FROM applications WHERE id = ?", (app_id,)).fetchone():
        abort(404)
    fields = {k: request.form[k] for k in ("status", "next_step", "next_date", "notes") if k in request.form}
    if fields.get("status") == "applied":
        row = c.execute("SELECT applied_on FROM applications WHERE id = ?", (app_id,)).fetchone()
        if not row["applied_on"]:
            fields["applied_on"] = date.today().isoformat()
    db.update_application(c, app_id, **fields)
    c.commit()
    c.close()
    flash("Application updated.")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/emails")
def emails():
    c = conn()
    rows = [dict(r) for r in c.execute(
        "SELECT e.*, a.company AS app_company, a.role AS app_role FROM events e "
        "LEFT JOIN applications a ON a.id = e.application_id WHERE e.category != 'other' "
        "ORDER BY e.received_at DESC LIMIT 300")]
    c.close()
    return render_template("emails.html", events=rows)


@app.route("/setup")
def setup():
    cfg = load_config()
    status = {
        "config_file": cfg["_config_file"],
        "reed": bool(cfg["sources"].get("reed_api_key")),
        "adzuna": bool(cfg["sources"].get("adzuna_app_id") and cfg["sources"].get("adzuna_app_key")),
        "gmail_enabled": bool(cfg["gmail"].get("enabled")),
        "gmail_method": gmail_method(cfg),
        "gmail_credentials": GMAIL_CREDENTIALS.exists(),
        "gmail_signed_in": gmail_token().exists(),
        "ai": bool(cfg["ai"].get("anthropic_api_key")),
        "cv": bool(cv_text(cfg)),
        "cv_file": str(cv_file(cfg["profile"]) or ""),
        "email": notify.ready(cfg),
        "email_to": notify.settings(cfg)["to"],
        "email_min": notify.settings(cfg)["min_score"],
        "auto_hours": auto_refresh_hours(cfg),
    }
    ts = phone.status() if from_this_pc() and not HOSTED else {"installed": True, "running": True, "url": request.host_url.rstrip("/")}
    phone_url = ts.get("url") or ""
    from jobhunt import persona
    status["cv_name"] = Path(status["cv_file"]).name if status["cv_file"] else ""
    return render_template("setup.html", status=status, cfg=cfg, bookmarklet=bookmarklet_href(), builtin=persona.builtin(),
                           fill_bookmarklet=bookmarklet_href("fill.js"), ts=ts, has_pin=phone.has_pin(),
                           phone_url=phone_url, on_pc=from_this_pc(),
                           phone_fill=bookmarklet_href("fill.js", phone_url) if phone_url else "",
                           phone_send=bookmarklet_href("bookmarklet.js", phone_url) if phone_url else "")


@app.post("/setup/phone")
def setup_phone():
    same_site_only()
    if not from_this_pc():
        abort(403)                       # phone access is switched on from the PC only
    action = request.form.get("action")
    if action == "pin":
        pin = (request.form.get("pin") or "").strip()
        if not re.fullmatch(r"\d{6,12}", pin):
            flash("Use 6 to 12 digits for your PIN.")
        else:
            phone.set_pin(pin)
            flash("PIN saved. Any phone signed in with an old PIN has been signed out.")
    elif action == "share":
        if not phone.has_pin():
            flash("Set your PIN first.")
        else:
            ok, text, link = phone.start_serving(int(load_config().get("app", {}).get("port", 5055)))
            if ok:
                flash("Your iPhone can now open Job Hunt HQ at " + phone.status().get("url", "your Tailscale address") + ".")
            elif link:
                from markupsafe import Markup, escape
                flash(Markup("Tailscale needs you to allow sharing once. I've opened its page in your browser – click "
                             "<b>Enable</b> there (or <a href='{0}' target='_blank' rel='noopener'>open it here</a>), then press "
                             "<b>Turn on iPhone access</b> again.").format(escape(link)))
            else:
                flash("Tailscale said: " + text)
    elif action == "stop":
        ok, text = phone.stop_serving()
        flash("Stopped sharing with your phone." if ok else "Tailscale said: " + text)
    elif action == "email":
        cfg = load_config()
        url = phone.status().get("url")
        ok, why = notify.ready(cfg)
        if not url:
            flash("Tailscale isn't set up yet, so there's no address to send.")
        elif not ok:
            flash(why)
        else:
            try:
                notify.send(cfg, "Job Hunt HQ on your iPhone",
                            f"<p>Open this on your iPhone (with Tailscale switched on):</p><p><a href='{url}'>{url}</a></p>"
                            "<p>Then tap <b>Share → Add to Home Screen</b> to keep it as an app.</p>",
                            f"Open this on your iPhone (with Tailscale switched on):\n\n{url}\n\n"
                            "Then tap Share → Add to Home Screen to keep it as an app.")
                flash("Emailed you the link – open it on your iPhone.")
            except Exception as e:
                flash(f"Couldn't send the email: {e}")
    return redirect(url_for("setup") + "#phone")


@app.post("/setup/test-email")
def test_email():
    same_site_only()
    cfg = load_config()
    ok, why = notify.ready(cfg)
    if not ok:
        flash(why)
        return redirect(url_for("setup") + "#email")
    c = conn()
    jobs = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE status IN ('new', 'shortlisted', 'prepared') "
                                        "AND score IS NOT NULL ORDER BY score DESC LIMIT 3")]
    c.close()
    if not jobs:
        jobs = [{"id": 0, "title": "Test job", "company": "Job Hunt HQ", "score": 80, "url": ""}]
    subject, html, text = notify.build(jobs, int(cfg.get("app", {}).get("port", 5055)))
    try:
        notify.send(cfg, "Test: " + subject, html, text)
        flash(f"Test email sent to {notify.settings(cfg)['to']} with your top 3 jobs. Check your inbox (and spam).")
    except Exception as e:
        flash(f"Couldn't send the test email: {e}. Check the app password in config.yaml.")
    return redirect(url_for("setup") + "#email")


def gmail_method(cfg):
    from jobhunt.gmail_sync import method
    return method(cfg)


def auto_refresh_hours(cfg) -> float:
    try:
        return float((cfg.get("app") or {}).get("auto_refresh_hours", 3) or 0)
    except (TypeError, ValueError):
        return 3.0


def auto_refresh_loop():
    """While the app is open, refresh every few hours (app: auto_refresh_hours in config.yaml; 0 = off)."""
    import time
    from datetime import datetime
    time.sleep(90)
    def one_person():
        cfg = load_config()
        hours = auto_refresh_hours(cfg)
        if hours > 0 and (cfg.get("search", {}).get("keywords") or cfg.get("builtin")):
            with db.session() as c:
                last = db.get_meta(c, "last_refresh")
            due = not last or (datetime.now() - datetime.fromisoformat(last)).total_seconds() >= hours * 3600
            if due:
                run_refresh(log=lambda m: print(f"[auto refresh {current_user_id()}]", m))
                with db.session() as c:
                    prepare_queue(c, limit=10)

    while True:
        try:
            if accounts.any_users():
                accounts.run_as_each_user(one_person)    # everyone's own search, one after another
            else:
                one_person()
        except Exception as e:
            print("[auto refresh] problem:", e)
        if HOSTED:
            try:
                from jobhunt import backups
                backups.snapshot()                       # once a day; old copies go after 7 days
            except Exception as e:
                print("[backup] problem:", e)
        time.sleep(600)


# ------------------------------------------------------------------ My career (used to fill application forms)
from jobhunt import career as career_store  # noqa: E402


@app.route("/career", methods=["GET", "POST"])
def career_page():
    if request.method == "POST":
        same_site_only()
        career_store.save(career_store.from_form(request.form))
        flash("Saved. Every application from now on uses these details.")
        return redirect(url_for("career_page"))
    c = conn()
    answers = [dict(r) for r in c.execute("SELECT key, question, answer, updated_at FROM answers ORDER BY updated_at DESC")]
    c.close()
    return render_template("career.html", career=career_store.load(), answers=answers)


@app.post("/career/answers")
def career_answers():
    same_site_only()
    with db.session() as c:
        for key in request.form.getlist("key"):
            if request.form.get(f"delete-{key}"):
                c.execute("DELETE FROM answers WHERE key = ?", (key,))
            else:
                value = (request.form.get(f"answer-{key}") or "").strip()
                if value:
                    c.execute("UPDATE answers SET answer = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ? AND answer != ?",
                              (value, key, value))
    flash("Saved answers updated.")
    return redirect(url_for("career_page") + "#answers")


# ------------------------------------------------------------------ Create CV
from jobhunt import cv as cvmod, cv_render  # noqa: E402

CV_STEPS = [("profile", "Headline and profile"), ("experience", "Experience"), ("education", "Education"),
            ("skills", "Skills and languages"), ("design", "Design and download")]
CV_SECTIONS = {"profile": ("headline", "summary"), "experience": ("experience",), "education": ("education",),
               "skills": ("skills", "languages", "certifications")}
app.config.setdefault("MAX_CONTENT_LENGTH", 12 * 1024 * 1024)


def cv_prefs() -> dict:
    p = (my_settings().get("cv") or {}) if current_user_id() else {}
    design = request.args.get("design") or p.get("design") or "classic"
    accent = request.args.get("accent") or p.get("accent") or "navy"
    return {"design": design if design in {d for d, _, _ in cvmod.DESIGNS} else "classic",
            "accent": accent if accent in cvmod.ACCENTS else "navy"}


def cv_job(job_id):
    if not job_id:
        return None
    c = conn()
    try:
        return get_job(c, int(job_id))
    finally:
        c.close()


@app.route("/cv", methods=["GET", "POST"])
def cv_builder():
    from jobhunt import persona
    step = request.values.get("step", "profile")
    if step not in dict(CV_STEPS):
        step = "profile"
    if request.method == "POST":
        same_site_only()
        if step in CV_SECTIONS:
            new, cur = career_store.from_form(request.form), career_store.load()
            for k in CV_SECTIONS[step]:
                cur[k] = new.get(k, cur.get(k))
            career_store.save(cur)
        elif step == "design":
            s = my_settings()
            s["cv"] = {"design": request.form.get("design", "classic"), "accent": request.form.get("accent", "navy")}
            accounts.save_settings(s, current_user_id())
        go = request.form.get("go") or step
        flash("Saved.")
        return redirect(url_for("cv_builder", step=go if go in dict(CV_STEPS) else step))
    cfg = load_config()
    career = career_store.load()
    c = conn()
    jobs = [dict(r) for r in c.execute(
        "SELECT id, title, company FROM jobs WHERE status IN ('shortlisted', 'prepared', 'applied') "
        "OR (status = 'new' AND score >= 60) ORDER BY updated_at DESC LIMIT 60")]
    c.close()
    current = cv_file(cfg["profile"])
    return render_template("cv_builder.html", step=step, steps=CV_STEPS, career=career, profile=cfg["profile"],
                           cv=cvmod.build(career, cfg["profile"]), tips=cvmod.suggestions(career, cfg["profile"]),
                           designs=cvmod.DESIGNS, accents=cvmod.ACCENTS, prefs=cv_prefs(), jobs=jobs,
                           builtin=persona.builtin(), current_cv=current.name if current else "")


@app.route("/cv/file")
def cv_download():
    cfg = load_config()
    job = cv_job(request.args.get("job"))
    cv = cvmod.build(career_store.load(), cfg["profile"], job)
    prefs, fmt = cv_prefs(), request.args.get("fmt", "pdf")
    if fmt == "docx":
        data, mime, ext = cv_render.docx(cv, prefs["accent"]), \
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
    else:
        data, mime, ext = cv_render.pdf(cv, prefs["design"], prefs["accent"]), "application/pdf", "pdf"
    import io
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=not request.args.get("view"),
                     download_name=cvmod.filename(cv, ext, job), max_age=0)


@app.post("/cv/use")
def cv_use():
    """Save the built CV as the one attached to applications."""
    same_site_only()
    from jobhunt import persona
    if persona.builtin() and not HOSTED:
        flash("Your applications keep using “Rashid Idle CV” in Documents – download this one if you'd like to swap it in.")
        return redirect(url_for("cv_builder", step="design"))
    cfg, prefs = load_config(), cv_prefs()
    cv = cvmod.build(career_store.load(), cfg["profile"])
    folder = user_dir() / "cv"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / cvmod.filename(cv, "pdf")
    out.write_bytes(cv_render.pdf(cv, prefs["design"], prefs["accent"]))
    s = my_settings()
    s.setdefault("profile", {})["cv_path"] = str(out)
    accounts.save_settings(s, current_user_id())
    flash(f"Done – “{out.name}” is now attached to your applications.")
    return redirect(url_for("cv_builder", step="design"))


@app.post("/cv/upload")
def cv_upload():
    """Upload an existing CV: keep it for applications, and read it into My career."""
    same_site_only()
    from werkzeug.utils import secure_filename

    from jobhunt import persona
    nxt = request.form.get("next") or url_for("cv_builder")
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = url_for("cv_builder")
    f = request.files.get("cv")
    ext = Path(f.filename or "").suffix.lower() if f else ""
    if not f or ext not in (".pdf", ".docx", ".doc"):
        flash("Choose a PDF or Word file.")
        return redirect(nxt)
    folder = user_dir() / "cv"
    folder.mkdir(parents=True, exist_ok=True)
    name = secure_filename(f.filename) or f"cv{ext}"
    saved = folder / name
    f.save(saved)
    if not persona.builtin() or HOSTED:          # on your PC, your own CV stays “Rashid Idle CV” in Documents
        s = my_settings()
        s.setdefault("profile", {})["cv_path"] = str(saved)
        accounts.save_settings(s, current_user_id())
    if ext == ".doc":
        flash("Saved – it'll be attached to applications. Old .doc files can't be read, so add your history on My career "
              "(or save it as .docx or PDF and upload again).")
        return redirect(nxt)
    try:
        text = cvmod.text_of(str(saved))
    except Exception:
        text = ""
    if len(text.strip()) < 80:
        flash("Saved – but no text could be read from it (it may be a scanned image). Add your details on the next steps.")
        return redirect(nxt)
    found = cvmod.ai_parse(text, load_config().get("ai")) or cvmod.parse(text)
    career = cvmod.merge_into(career_store.load(), found)
    career_store.save(career)
    flash(f"Read your CV: {len(found.get('experience', []))} jobs, {len(found.get('education', []))} qualifications and "
          f"{len(found.get('skills', []))} skills. Please check each step – reading CVs is never perfect.")
    return redirect(nxt)


# ------------------------------------------------------------------ Apply for me (the robot)
from jobhunt.agent import AGENT, start_url as robot_start_url  # noqa: E402


def same_site_only():
    """Only this app's own pages may control the robot – not other websites."""
    origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
    own = request.host_url.rstrip("/")
    # Your phone, through Tailscale: https://<your-pc>.<your-tailnet>.ts.net (only your own devices can reach it)
    tailnet = re.match(r"https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net(/|$)", origin)
    if origin and not re.match(r"https?://(127\.0\.0\.1|localhost)(:\d+)?(/|$)", origin) and \
            not (origin == own or origin.startswith(own + "/")) and not tailnet:
        abort(403)


@app.post("/job/<int:job_id>/robot")
def robot_start(job_id):
    same_site_only()
    return start_robot(job_id)


@app.post("/robot/link")
def robot_link():
    """Paste a job or application link: add the job, write its letter, and start Apply for me on it."""
    same_site_only()
    url = (request.form.get("url") or "").strip()
    if not url.startswith("http"):
        flash("Paste a full link starting with https://")
        return redirect(request.referrer or url_for("robot_page"))
    url = canonical_url(url)
    try:
        data = fetch_job(url)
    except Exception:
        from jobhunt.fetch_page import company_from_url
        data = {"url": url, "title": "", "company": company_from_url(url), "description": ""}
    data["title"] = data.get("title") or "Job at " + (data.get("company") or url.split("/")[2])
    data["company"] = data.get("company") or url.split("/")[2]
    if not data.get("apply_url") and not any(b in url for b in JOB_BOARDS):
        data["apply_url"] = url
    job_id, _ = save_and_prepare(data)
    c = conn()
    if data.get("apply_url"):          # the link you pasted is where to apply, even for a job already saved
        db.update_job(c, job_id, apply_url=data["apply_url"])
        c.commit()
    job = get_job(c, job_id)
    c.close()
    if not robot_start_url(job):
        flash("That's a LinkedIn Easy Apply job (or a job-board page with no employer link), so the robot can't apply "
              "there – apply on the site and use your Fill this application button. The job and its cover letter are "
              "saved here.")
        return redirect(url_for("job_detail", job_id=job_id))
    return start_robot(job_id)


def start_robot(job_id):
    cfg, c = load_config(), conn()
    job = get_job(c, job_id)
    c.close()
    url = robot_start_url(job)
    if not url:
        flash("I don't have the employer's application link for this job yet – only a job-board link, and the robot "
              "doesn't work on LinkedIn, Indeed or other job boards (their rules ban it). Open the advert, click its "
              "Apply button, and click your Fill this application button once on the employer's page: the app then "
              "saves the link and Apply for me works. For LinkedIn Easy Apply jobs, apply on LinkedIn and use "
              "Copy answers.")
        return redirect(url_for("job_detail", job_id=job_id))
    if AGENT.running():
        flash("The robot is already working on an application. Finish or stop it first.")
        return redirect(url_for("robot_page"))
    pack = build_pack(job_id)
    profile = cfg["profile"]
    cv = cv_file(profile)
    files = {"cv": str(cv) if cv else None, "letter": None}
    c = conn()
    job = get_job(c, job_id)
    c.close()
    if job.get("cover_letter"):
        letter = archive_letter(job, cfg)
        if letter is None:   # couldn't write to the Cover Letters folder: keep a copy in the app's own folder
            folder = user_dir() / "letters"
            folder.mkdir(parents=True, exist_ok=True)
            letter = folder / f"{profile.get('name', 'Cover')} Cover Letter - {safe_filename(job.get('company') or 'Job')}.pdf"
            letter.write_bytes(letter_pdf(job["cover_letter"], profile))
        files["letter"] = str(letter)

    def remembered():
        with db.session() as cc:
            return db.remembered_answers(cc)

    def remember(question, answer):
        with db.session() as cc:
            db.remember_answer(cc, question, answer)

    def learn_advert(text, pasted=False, force=False):
        """The robot read the advert (from the page, or you pasted it): store it, re-score, rewrite the letter,
        save it in Cover Letters, rebuild the answers."""
        cc = conn()
        j = get_job(cc, job_id)
        if (len(j.get("description") or "") >= 400 and not force) or len(text or "") < (150 if pasted else 600):
            cc.close()
            return None
        j["description"] = text[:20000]
        # A careers-site placeholder title ("Job at Birdeye Inc") → the real one from the page.
        if re.match(r"(?i)^(jobs?|careers?|vacanc\w*|opportunit\w*)\s+(at|with)\b", j.get("title") or ""):
            m = re.search(r"(?im)^\s*application:\s*(.{4,100})$", text)
            if m:
                j["title"] = m.group(1).strip()
                db.update_job(cc, job_id, title=j["title"])
        letter, _ = write_letter(j, profile, cv_text(cfg), cfg.get("ai"))
        db.update_job(cc, job_id, description=j["description"], score=score, score_reasons=" · ".join(reasons),
                      cover_letter=letter)
        cc.commit()
        cc.close()
        j["cover_letter"] = letter
        saved = archive_letter(j, cfg)
        if saved:
            files["letter"] = str(saved)     # the robot uploads this new version
        return build_pack(job_id)

    def make_letter(fresh=False):
        """Your cover letter for this job as a PDF in Cover Letters (written now if there isn't one yet)."""
        cc = conn()
        j = get_job(cc, job_id)
        if fresh or not j.get("cover_letter"):
            j["cover_letter"], _ = write_letter(j, profile, cv_text(cfg), cfg.get("ai"))
            db.update_job(cc, job_id, cover_letter=j["cover_letter"])
            cc.commit()
        cc.close()
        saved = archive_letter(j, cfg)
        return str(saved) if saved else files.get("letter")

    hooks = {"remembered": remembered, "remember": remember, "applied": lambda page: mark_applied(job_id, page),
             "make_letter": make_letter,
             "profile": profile, "cv": cv_text(cfg), "ai": cfg.get("ai") or {}, "learn_advert": learn_advert}
    try:
        AGENT.start(job, pack, files, url, hooks)
    except RuntimeError as e:
        flash(str(e))
    return redirect(url_for("robot_page"))


@app.route("/robot")
def robot_page():
    c = conn()
    rows = [dict(r) for r in c.execute(
        "SELECT id, title, company, location, score, url, apply_url, description FROM jobs "
        "WHERE status NOT IN ('applied', 'skipped') ORDER BY score IS NULL, score DESC, updated_at DESC")]
    c.close()
    ready = [r for r in rows if robot_start_url(r)][:15]
    return render_template("robot.html", state=AGENT.status(), ready=ready, waiting=len(rows) - len(ready))


@app.route("/api/robot", methods=["GET", "POST"])
def robot_api():
    if request.method == "POST":
        same_site_only()
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        if action not in ("continue", "stop", "answers", "done", "pause", "attach", "clear"):
            abort(400)
        AGENT.send(action, data.get("answers"))
    return AGENT.status()


def main():
    cfg = load_config()
    port = int(cfg.get("app", {}).get("port", 5055))
    if cfg.get("app", {}).get("open_browser", True) and not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    # Keep the black window readable: don't print the Apply for me page's status checks every 1.5 seconds.
    import logging

    class QuietStatus(logging.Filter):
        def filter(self, record):
            return "/api/robot" not in record.getMessage() or "POST" in record.getMessage()
    logging.getLogger("werkzeug").addFilter(QuietStatus())
    # The app restarts itself when its files are updated, so new features work without closing the black
    # window. (The watcher runs in the first process; the app itself runs in a second one.)
    serving = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if serving:
        try:
            from jobhunt.refresh import tidy_far_jobs
            with db.session() as c:
                tidy_far_jobs(c, cfg)
        except Exception:
            pass
        try:                              # emails already in the app → applications (adds any it didn't know about)
            from jobhunt.gmail_sync import link_existing, needs_rebuild
            with db.session() as c:
                rebuild = needs_rebuild(c) and bool(gmail_method(cfg))
                if not rebuild:
                    link_existing(c, log=lambda m: None)
            if rebuild:                   # the email rules improved: read 2026 again, properly, in the background
                start_history_import(cfg, rebuild=True)
        except Exception:
            pass
        threading.Thread(target=auto_refresh_loop, daemon=True).start()
    else:
        print("Job Hunt HQ restarts itself automatically when it's updated.")
    root = Path(__file__).resolve().parent
    watch = [str(p) for pattern in ("templates/*.html", "static/*.js", "static/*.css", "jobhunt/*.json")
             for p in root.glob(pattern)]
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=True, reloader_type="stat", extra_files=watch)


if __name__ == "__main__":
    main()
