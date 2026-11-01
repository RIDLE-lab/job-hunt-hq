"""Apply for me – a browser window that Job Hunt HQ controls.

It opens the employer's application page, clicks Apply, fills each step, uploads your CV and cover
letter and presses Next. It stops and asks you whenever it needs you: signing in, "I'm not a robot"
checks, and questions it can't answer from your details. It never presses Submit – it stops on the
last page so you can check everything and submit yourself, then notices the "thank you" page.

The window has its own browser profile (data/browser), so you sign in to each site once.
It is never used on LinkedIn, Indeed or other job boards, whose rules ban automated applying.
"""
from __future__ import annotations

import os
import queue
import re
import threading
import time
from pathlib import Path

from .answers import match_option, suggest
from .config import user_dir

STATIC = Path(__file__).resolve().parent.parent / "static"

NEXT = re.compile(r"^\s*(next|next step|continue|save (and|&) continue|save (and|&) next|proceed|"
                  r"continue to next step|review|review application)\s*[›>→]?\s*$", re.I)
SUBMIT = re.compile(r"^\s*(submit|submit (my |your |the )?application|send (my |your )?application|"
                    r"complete (my |your )?application|finish|apply|submit (and|&) finish|confirm (and|&) submit)\s*$", re.I)
SUBMIT_FORM = re.compile(SUBMIT.pattern.replace("|finish|apply|", "|finish|"), re.I)   # not a bare "Apply" button
# Ways to start an application (Workday and similar). When more than one is offered, you choose.
START_CHOICES = re.compile(r"^\s*(use my last application|autofill with (resume|cv)|apply manually|"
                           r"(apply|autofill) with linkedin|apply with indeed|apply with seek)\s*$", re.I)
START_QUESTION = "How would you like to start applications on Workday and similar sites?"
APPLY_CHOICES = [re.compile(x, re.I) for x in (
    r"^\s*autofill with (resume|cv)\s*$",
    r"^\s*apply manually\s*$",
    r"^\s*(apply|apply now|apply for (this|the) (job|role|position|vacancy)|apply online|apply here|"
    r"start (your |my )?application|begin (your )?application|i'?m interested)\s*$",
)]
COOKIE_REJECT = re.compile(r"^\s*(reject all|reject|decline|decline all|necessary only|only necessary|"
                           r"reject (all )?non-essential( cookies)?|use necessary cookies only|"
                           r"accept (only )?necessary( cookies)?( only)?|essential only|reject optional cookies)\s*$", re.I)
THANKS = re.compile(r"thank(s| you) for (applying|your application|submitting)|application (has been |was )?"
                    r"(successfully )?(submitted|received|sent|complete)|we('ve| have) received your application|"
                    r"successfully (submitted|applied)", re.I)
JOB_BOARDS = ("linkedin.com", "indeed.", "thetalentworld.co.uk", "reed.co.uk", "adzuna.", "charityjob.",
              "totaljobs.", "cv-library.", "glassdoor.")


class Stop(Exception):
    pass


class Closed(Exception):
    pass


def start_url(job: dict) -> str | None:
    """Where the robot starts: the employer's own application link, never a job board."""
    desc = job.get("description") or ""
    m = re.search(r"Apply directly: (https?://\S+)", desc)
    for url in (job.get("apply_url"), m.group(1) if m else None, job.get("url")):
        if url and url.startswith("http") and not any(b in url for b in JOB_BOARDS):
            return url
    return None


class Agent:
    def __init__(self):
        self.lock = threading.Lock()
        self.inbox: queue.Queue = queue.Queue()
        self.thread: threading.Thread | None = None
        self.version = 0
        self.state = {"status": "idle", "message": "", "questions": [], "log": [], "job": None}

    # ---------------------------------------------------------------- shared with the web page
    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)
            self.version += 1
            self.state["version"] = self.version

    def log(self, text: str):
        with self.lock:
            self.state["log"] = (self.state["log"] + [time.strftime("%H:%M:%S ") + text])[-80:]
            self.version += 1
            self.state["version"] = self.version

    def status(self) -> dict:
        with self.lock:
            s = dict(self.state)
            s["running"] = bool(self.thread and self.thread.is_alive())
            return s

    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def send(self, kind: str, data=None):
        if kind == "clear":
            self.clear()
            return
        self.inbox.put((kind, data))

    def clear(self):
        """Back to the start page once a run has finished (the robot isn't running)."""
        if self.running():
            return
        self._set(status="idle", message="", questions=[], log=[], job=None)

    def start(self, job: dict, pack: dict, files: dict, url: str, hooks: dict):
        if self.running() and self.state.get("status") == "applied":   # finished – just close its window
            self.send("stop")
            self.thread.join(15)
        if self.running():
            raise RuntimeError("The robot is already working on an application. Stop it first.")
        while not self.inbox.empty():
            self.inbox.get_nowait()
        self._set(status="starting", message="Opening the browser window…", questions=[], log=[], kind="",
                  job={"id": job["id"], "title": job["title"], "company": job["company"]})
        import contextvars
        from .config import current_user_id
        self.user = current_user_id()          # the robot works for whoever started it, with their data
        ctx = contextvars.copy_context()
        self.thread = threading.Thread(target=ctx.run, args=(self._run, job, pack, files, url, hooks), daemon=True)
        self.thread.start()

    # ---------------------------------------------------------------- the worker
    def _run(self, job, pack, files, url, hooks):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self._set(status="error", message="The browser part isn't installed yet. Close the black window and "
                                              "double-click run.bat again – it installs it.")
            return
        self.job, self.pack, self.files, self.hooks = job, pack, files, hooks
        self.core = (STATIC / "fill_core.js").read_text(encoding="utf-8")
        self.asked: set = set()
        try:
            with sync_playwright() as p:
                ctx = self._launch(p)
                self.ctx = ctx
                try:
                    try:
                        self._apply(url)
                    except (Stop, Closed):
                        raise
                    except Exception as e:  # keep the window open so you can carry on by hand
                        self.log(f"Problem: {str(e).splitlines()[0][:200]}")
                        self._set(status="error", questions=[],
                                  message="Something went wrong, so I've stopped. You can finish this application in "
                                          "the browser window yourself (the Fill button works there), then press "
                                          "“I've submitted” or “Close the browser”.")
                        self._hold(final=True)
                except Stop:
                    if self.state["status"] != "applied":
                        self._set(status="stopped", message="Stopped, and the browser window is closed.", questions=[])
                except Closed:
                    if self.state["status"] != "applied":
                        self._set(status="closed", message="The browser window was closed.", questions=[])
                try:
                    ctx.close()
                except Exception:
                    pass
        except Exception as e:
            self._set(status="error", message=f"Couldn't open the browser: {str(e).splitlines()[0][:300]}")

    def _launch(self, p):
        profile = user_dir() / "browser"
        profile.mkdir(parents=True, exist_ok=True)
        headless = os.environ.get("JOBHUNT_HEADLESS") == "1"
        wanted = os.environ.get("JOBHUNT_BROWSER")
        channels = [None if wanted == "chromium" else wanted] if wanted else ["chrome", "msedge", None]
        errors = []
        for ch in channels:
            kw = {"headless": headless, "accept_downloads": False}
            if headless:
                kw["viewport"] = {"width": 1280, "height": 1000}
            else:
                kw.update(no_viewport=True, chromium_sandbox=True,
                          args=["--start-maximized", "--no-first-run", "--no-default-browser-check",
                                "--disable-features=msEdgeWelcomePage,msImplicitSignin"])
            if ch:
                kw["channel"] = ch
            try:
                ctx = p.chromium.launch_persistent_context(str(profile), **kw)
                # Browsers sometimes open their own start/welcome tab: keep just one tab for the application.
                for extra in ctx.pages[1:]:
                    try:
                        extra.close()
                    except Exception:
                        pass
                self.log("Opened " + {"chrome": "Chrome", "msedge": "Microsoft Edge"}.get(ch or "", "the browser"))
                return ctx
            except Exception as e:
                errors.append(str(e).splitlines()[0][:150])
        raise RuntimeError("Chrome and Edge wouldn't open (" + "; ".join(errors) + "). If an earlier robot "
                           "window is still open, close it and try again.")

    @staticmethod
    def _is_site(pg) -> bool:
        url = pg.url or ""
        return url.startswith("http") and "127.0.0.1" not in url

    def _page(self):
        """The application's tab: ours, or a tab the application itself opened (e.g. Apply opening a new tab).
        The browser's own new-tab/start pages are ignored."""
        pages = [pg for pg in self.ctx.pages if not pg.is_closed()]
        if not pages:
            raise Closed()
        current = getattr(self, "page", None)
        opened = [pg for pg in pages if pg is not current and self._is_site(pg) and self._opener_ok(pg, current)]
        if opened:
            page = opened[-1]
        elif current is not None and not current.is_closed():
            page = current
        else:
            sites = [pg for pg in pages if self._is_site(pg)]
            page = sites[-1] if sites else pages[-1]
        if page is not current:
            self.page = page
            try:
                page.bring_to_front()
            except Exception:
                pass
        return page

    @staticmethod
    def _opener_ok(pg, current) -> bool:
        try:
            op = pg.opener()
        except Exception:
            return False
        return op is not None and (current is None or op is current or op.is_closed())

    def _settle(self, page):
        for state, ms in (("domcontentloaded", 20000), ("networkidle", 6000)):
            try:
                page.wait_for_load_state(state, timeout=ms)
            except Exception:
                pass
        try:
            page.wait_for_timeout(800)
        except Exception:
            pass   # the tab closed – _page() finds the right one next

    @staticmethod
    def _transient(e) -> bool:
        """The page moved on while it was being read (a redirect or a new step loading)."""
        return bool(re.search(r"execution context was destroyed|navigat|frame was detached|"
                              r"cannot find context|context was destroyed", str(e), re.I))

    def _js(self, page, expr, arg=None):
        for attempt in range(5):
            try:
                if not page.evaluate("() => typeof window.JHQ !== 'undefined'"):
                    page.evaluate("() => {" + self.core + "\n}")
                return page.evaluate(expr, arg) if arg is not None else page.evaluate(expr)
            except Exception as e:
                if not self._transient(e) or attempt == 4:
                    raise
                self._settle(page)

    def _text(self, page) -> str:
        return self._js(page, "() => document.body ? document.body.innerText.slice(0, 8000) : ''")

    def _check_inbox(self):
        while True:
            try:
                kind, data = self.inbox.get_nowait()
            except queue.Empty:
                return
            if kind == "stop":
                raise Stop()
            if kind == "attach":
                self._attach()
                continue
            if kind == "pause":
                self.log("Paused – you're driving")
                self._wait("paused", "Paused. Carry on in the browser window as you like. Press Continue when you "
                                     "want me to pick up from the page you're on.")

    # ---------------------------------------------------------------- the application
    def _apply(self, url=None):
        if url:
            page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
            self.page = page
            self._set(status="working", message="Opening the application…")
            self.log(f"Opening {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self._learn_advert(page)
        stuck = noform = 0
        moved = 0
        for _ in range(60):
            try:
                self._check_inbox()
                page = self._page()
                self._settle(page)
                page = self._page()
                self._set(status="working", message="Working on the application…", questions=[])
                text = self._text(page)
                info = self._js(page, "() => JHQ.scan()")
                if THANKS.search(text) and info["fields"] < 3:
                    return self._applied(page)
                if self._needs_sign_in(page):
                    self._wait("sign_in", "This site wants you to sign in or create an account. Do that in the browser "
                                          "window – Job Hunt HQ never types passwords – then press Continue.")
                    continue
                if self._captcha(page):
                    self._wait("captcha", "There's an “I'm not a robot” check. Tick it in the browser window, "
                                          "then press Continue.")
                    continue
                self._reject_cookies(page)
                small_form = info["fields"] >= 1 and (self._find(page, [NEXT]) is not None or
                                                      self._find(page, [SUBMIT_FORM]) is not None)   # e.g. an upload-only step
                if info["fields"] < 3 and not small_form:
                    if self._start_choice(page):
                        continue
                    btn = self._find(page, APPLY_CHOICES)
                    if btn is not None:
                        self.log(f"Clicking “{self._name(btn)}”")
                        self._click(page, btn)
                        continue
                    if self._find(page, [SUBMIT]) is not None:     # e.g. a review page with just Submit
                        return self._review()
                    noform += 1
                    if noform < 2:
                        page.wait_for_timeout(2500)
                        continue
                    self._wait("help", "I can't find the application form on this page. Open it in the browser window "
                                       "(for example by clicking Apply), then press Continue.")
                    noform = 0
                    continue
                noform = 0
                self._fill(page)
                self._questions(page)
                nxt, sub = self._find(page, [NEXT]), self._find(page, [SUBMIT])
                if nxt is not None:
                    before = self._js(page, "() => JHQ.signature()")
                    self.log(f"Pressing “{self._name(nxt)}”")
                    self._click(page, nxt)
                    self._settle(page)
                    page = self._page()
                    after = self._js(page, "() => JHQ.signature()")
                    if after == before:
                        stuck += 1
                        if stuck >= 2:
                            self._wait("help", "I couldn't get past this page. It may be showing an error or a question I "
                                               "couldn't answer. Sort it out in the browser window, then press Continue.")
                            stuck = 0
                    else:
                        stuck = 0
                        self.asked = set()
                    continue
                if sub is not None:
                    return self._review()
                self._wait("help", "I can't find a Next or Submit button here. Carry on in the browser window, then "
                                   "press Continue.")
            except (Stop, Closed):
                raise
            except Exception as e:
                closed = re.search(r"has been closed|target closed", str(e), re.I)
                if not (self._transient(e) or closed) or moved >= 6:
                    raise
                moved += 1          # the page changed under us (or a tab closed) – look again
                if closed and getattr(self, "page", None) is not None and self.page.is_closed():
                    self.page = None
                self._settle(self._page())
        self._review()

    def _learn_advert(self, page):
        """If the app couldn't read this advert in advance, read it from the job page now."""
        if len(self.job.get("description") or "") >= 400 or "learn_advert" not in self.hooks:
            return
        try:
            self._settle(page)
            text = self._js(page, """() => { const m = document.querySelector('main, [role=main], article') || document.body;
                                       return (m.innerText || '').slice(0, 20000); }""")
            pack = self.hooks["learn_advert"](text)
            if pack:
                self.pack = pack
                self.job["description"] = text
                self.log("Read the advert on the page and tailored your cover letter and answers to it")
        except Exception as e:
            if self._transient(e):
                return
            self.log(f"Couldn't read the advert: {str(e).splitlines()[0][:100]}")
        if len(self.job.get("description") or "") < 400:
            self._ask_for_advert()

    def _ask_for_advert(self):
        q = {"id": "advert", "kind": "textarea", "options": [], "suggestion": "", "source": "", "no_remember": True,
             "label": "I couldn't read the job description. Paste it here (copy it from the advert) so I can write "
                      "your cover letter and answers for this job – or skip."}
        text = ((self._ask([q]).get("advert") or {}).get("value") or "").strip()
        if len(text) < 150:
            self.log("No job description – using your general cover letter")
            return
        pack = self.hooks["learn_advert"](text, True, force=True)
        if pack:
            self.pack = pack
            self.job["description"] = text
            self.log("Read the job description you pasted and wrote your cover letter and answers for it")

    def _start_choice(self, page) -> bool:
        """Workday-style 'Start your application' box: use your remembered choice, or ask you once."""
        names = []
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=START_CHOICES)
            try:
                for i in range(min(loc.count(), 8)):
                    el = loc.nth(i)
                    if el.is_visible():
                        names.append(re.sub(r"\s+", " ", el.inner_text().strip()))
            except Exception:
                pass
        names = list(dict.fromkeys(n for n in names if n))
        if len(names) < 2:
            return False
        from .answers import match_option
        saved = self.hooks["remembered"]().get(__import__("jobhunt.db", fromlist=["x"]).question_key(START_QUESTION))
        choice = match_option(names, saved) if saved else None
        if not choice:
            default = next((n for n in names if re.search(r"autofill with (resume|cv)", n, re.I)), names[0])
            q = {"id": "start", "label": START_QUESTION, "kind": "select", "options": names, "suggestion": default,
                 "source": ""}
            a = (self._ask([q]).get("start") or {})
            choice = match_option(names, a.get("value") or "")
            if not choice:
                self._wait("help", "Choose how to start in the browser window, then press Continue.")
                return True
            if a.get("remember"):
                self.hooks["remember"](START_QUESTION, choice)
        el = self._find(page, [re.compile(r"^\s*" + re.escape(choice) + r"\s*$", re.I)])
        if el is None:
            return False
        self.log(f"Clicking “{choice}”")
        self._click(page, el)
        if re.search(r"linkedin|indeed|seek", choice, re.I):
            self._settle(page)
            self._wait("sign_in", f"You chose “{choice}”. Sign in and allow access in the browser window (that's "
                                  "yours to approve), then press Continue and I'll carry on.")
        return True

    def _fill(self, page):
        # Work experience, education and skills first, so the general filler doesn't put your current
        # job into every experience row.
        try:
            from . import career, sections
            sections.fill_sections(self, page, career.load())
        except Exception as e:
            if self._transient(e):
                raise
            self.log(f"Couldn't fill experience sections: {str(e).splitlines()[0][:120]}")
        res = self._js(page, "pack => JHQ.fill(pack)", self.pack)
        done = [f for f in res.get("filled", []) if "not found" not in f]
        if done:
            self.log("Filled: " + ", ".join(done))
        self._upload(page, res.get("files", []))
        for cid in res.get("combos", []):
            if not self._choose_typed(page, cid):
                self.log("Pick the highlighted list field (like City) from its drop-down yourself")

    def _upload(self, page, boxes) -> int:
        done = 0
        for f in boxes:
            if f["which"] == "letter" and not self.files.get("letter") and "make_letter" in self.hooks:
                self.files["letter"] = self.hooks["make_letter"]()
            path = self.files.get(f["which"])
            label = "CV" if f["which"] == "cv" else "cover letter"
            if not path:
                self.log(f"No {label} file to upload – attach it yourself")
                continue
            try:
                page.locator(f'[data-jhq="{f["id"]}"]').set_input_files(path, timeout=10000)
                self.log(f"Uploaded your {label}")
                done += 1
                if f["which"] == "letter":
                    self.letter_uploaded = True
                page.wait_for_timeout(1500)
            except Exception as e:
                self.log(f"Couldn't upload the {label}: {str(e).splitlines()[0][:120]}")
        return done

    def _attach(self):
        """You pressed “Attach my CV & cover letter”: get the job description if I don't have it, write the
        letter, save it in Cover Letters and put both files in the page's upload boxes."""
        page = self._page()
        self._set(status="working", message="Attaching your CV and cover letter…")
        if len(self.job.get("description") or "") < 400:
            self._ask_for_advert()
        if "make_letter" in self.hooks:
            self.files["letter"] = self.hooks["make_letter"](fresh=False) or self.files.get("letter")
        try:
            boxes = self._js(page, "() => JHQ.uploads()")
        except Exception:
            boxes = []
        done = self._upload(page, boxes) if boxes else 0
        import os
        names = ", ".join(f"“{os.path.basename(p)}”" for p in (self.files.get("cv"), self.files.get("letter")) if p)
        if not boxes:
            self.log("No empty upload boxes on this page")
            return f"I couldn't find an empty upload box on this page. Your files are ready: {names} (cover letters are in your Cover Letters folder)."
        return f"Attached {done} file{'s' if done != 1 else ''}. Check them in the browser window, then press Continue."

    def _questions(self, page):
        qs = [q for q in self._js(page, "() => JHQ.scan()")["questions"] if q["id"] not in self.asked]
        if not qs:
            return
        remembered = self.hooks["remembered"]()
        for q in qs:
            if q["kind"] == "listbox" and not q["options"]:
                q["options"] = self._listbox_options(page, q["id"])
        ask = []
        for q in qs:
            ans, src = suggest(q, remembered, self.hooks["profile"], self.pack["fields"], self.job,
                               self.hooks["cv"], self.hooks["ai"])
            q["suggestion"], q["source"] = ans, src
            if src == "story" and q.get("story_fit", 0) < 3:
                q["note"] = ("None of your examples in My career fits this question well, so this uses the closest one "
                             f"(“{q.get('story', '')}”). Rewrite it or add a better example in My career.")
            elif src == "story":
                q["note"] = (f"Built from your example “{q.get('story', '')}” in My career. Replace anything in "
                             "[brackets] with the real details.")
            if src == "own_words":
                from .advert import talking_points
                q["points"] = talking_points(self.job.get("description", ""), 4)
            if src in ("remembered", "rule") and ans and self._put(page, q, ans):
                how = "your earlier answer" if src == "remembered" else "from your details"
                self.log(f"Answered “{q['label'][:80]}”: {ans[:60]} ({how})")
            else:
                ask.append(q)
        if not ask:
            return
        answers = self._ask(ask)
        for q in ask:
            self.asked.add(q["id"])
            a = answers.get(q["id"]) or {}
            value = (a.get("value") or "").strip()
            if not value:
                continue
            if self._put(page, q, value):
                self.log(f"Answered “{q['label'][:80]}”: {value[:60]}")
                if a.get("remember"):
                    self.hooks["remember"](q["label"], value)
            else:
                self.log(f"Couldn't enter the answer to “{q['label'][:80]}” – do it in the browser window")

    # ---------------------------------------------------------------- talking to you
    def _wait(self, kind, message):
        self._set(status="waiting", kind=kind, message=message, questions=[])
        while True:
            try:
                k, data = self.inbox.get(timeout=1)
            except queue.Empty:
                self._page()   # raises Closed if you closed the window
                continue
            if k == "stop":
                raise Stop()
            if k == "done":
                return self._applied(self._page(), by_you=True)
            if k == "attach":
                msg = self._attach()
                self._set(status="waiting", kind=kind, message=msg, questions=[])
                continue
            if k in ("continue", "answers"):
                self.log("Continuing")
                return

    def _ask(self, questions) -> dict:
        self._set(status="question", kind="questions", questions=questions,
                  message="I need your answers to carry on. Suggested answers are filled in – check them.")
        while True:
            try:
                k, data = self.inbox.get(timeout=1)
            except queue.Empty:
                self._page()
                continue
            if k == "stop":
                raise Stop()
            if k == "answers":
                self._set(status="working", message="Entering your answers…", questions=[])
                return data or {}
            if k == "continue":
                self._set(status="working", questions=[])
                return {}

    def _review(self):
        note = ""
        letter = (self.files or {}).get("letter")
        if letter and not getattr(self, "letter_uploaded", False):
            name = __import__("os").path.basename(letter)
            note = (f" I didn't attach a cover letter. If the form has a box for one, it's saved in your Cover Letters "
                    f"folder as “{name}”.")
            self.log(f"Cover letter saved in your Cover Letters folder: {name}")
        self._set(status="review", kind="review", questions=[],
                  message="I've done everything up to the final step. Check the application in the browser window "
                          "and press its Submit button yourself. I'll notice the confirmation page, or press "
                          "“I've submitted” here." + note)
        self.log("Waiting for you to check and submit")
        self._hold()

    def _hold(self, final=False):
        while True:
            try:
                k, data = self.inbox.get(timeout=1.5)
            except queue.Empty:
                k = None
            if k == "stop":
                raise Stop()
            page = self._page()
            if final:
                if k == "done" and self.state["status"] != "applied":
                    self.hooks["applied"](page.url)
                    self._set(status="applied", message="Marked as applied. You can close the browser window.")
                continue
            if k == "done":
                return self._applied(page, by_you=True)
            if k == "attach":
                msg = self._attach()
                self._set(status="review", kind="review", message=msg + " Then press the form's Submit button yourself.")
                continue
            if k == "continue":
                self.log("Continuing")
                return self._apply()
            try:
                text = page.evaluate("() => document.body ? document.body.innerText.slice(0, 8000) : ''")
            except Exception:
                continue
            if THANKS.search(text):
                return self._applied(page)

    def _applied(self, page, by_you=False):
        self.hooks["applied"](page.url if page else "")
        self.log("Marked as applied in Job Hunt HQ")
        self._set(status="applied", kind="", questions=[],
                  message=("Marked as applied." if by_you else "The employer confirmed your application, so I've "
                           "marked it as applied.") + " You can close the browser window.")
        self._hold(final=True)

    # ---------------------------------------------------------------- page helpers
    def _visible_first(self, loc):
        try:
            for i in range(min(loc.count(), 12)):
                el = loc.nth(i)
                if el.is_visible() and el.is_enabled() and not el.evaluate("e => !!e.closest('#jhq-panel')"):
                    return el
        except Exception:
            pass
        return None

    def _find(self, page, patterns):
        for pat in patterns:
            for loc in (page.get_by_role("button", name=pat), page.get_by_role("link", name=pat)):
                el = self._visible_first(loc)
                if el is not None:
                    return el
            subs = page.locator("input[type=submit], input[type=button]")
            try:
                for i in range(min(subs.count(), 10)):
                    el = subs.nth(i)
                    if pat.search(el.get_attribute("value") or "") and el.is_visible():
                        return el
            except Exception:
                pass
        return None

    def _name(self, el) -> str:
        try:
            return (el.inner_text(timeout=2000) or el.get_attribute("value") or "").strip()[:60]
        except Exception:
            return "button"

    def _click(self, page, el):
        try:
            el.click(timeout=8000)
        except Exception:
            self._wait("help", "Something on the page is in the way (maybe a cookie banner or pop-up). Close it in "
                               "the browser window, then press Continue.")

    def _needs_sign_in(self, page) -> bool:
        try:
            return page.locator("input[type=password]:visible").count() > 0
        except Exception:
            return False

    def _captcha(self, page) -> bool:
        try:
            return page.evaluate("""() => [...document.querySelectorAll('iframe')].some(f => {
                const s = f.src || '', r = f.getBoundingClientRect();
                return /recaptcha\\/api2\\/anchor|recaptcha\\/enterprise\\/anchor|hcaptcha\\.com|challenges\\.cloudflare\\.com/.test(s)
                       && !/size=invisible/.test(s) && r.width > 50 && r.height > 30; })""")
        except Exception:
            return False

    def _reject_cookies(self, page):
        el = self._find(page, [COOKIE_REJECT])
        if el is not None:
            try:
                el.click(timeout=3000)
                self.log("Turned down optional cookies")
                page.wait_for_timeout(500)
            except Exception:
                pass

    def _options_now(self, page) -> list:
        try:
            return [t.strip() for t in page.locator("[role=option]:visible").all_inner_texts() if t.strip()]
        except Exception:
            return []

    def _listbox_options(self, page, qid) -> list:
        try:
            page.locator(f'[data-jhq="{qid}"]').click(timeout=5000)
            page.wait_for_timeout(800)
            opts = self._options_now(page)[:80]
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            return opts
        except Exception:
            return []

    def _put(self, page, q, value) -> bool:
        try:
            r = self._js(page, "([id, v]) => JHQ.answer(id, v)", [q["id"], value])
        except Exception:
            return False
        if r == "robot":
            return self._choose_listbox(page, q["id"], value) if q["kind"] == "listbox" else self._choose_typed(page, q["id"])
        return r == "ok"

    def _choose_listbox(self, page, qid, value) -> bool:
        try:
            page.locator(f'[data-jhq="{qid}"]').click(timeout=5000)
            page.wait_for_timeout(700)
            opts = page.locator("[role=option]:visible")
            texts = [t.strip() for t in opts.all_inner_texts()]
            want = match_option(texts, value)
            if want is None:
                page.keyboard.press("Escape")
                return False
            opts.nth(texts.index(want)).click(timeout=5000)
            page.wait_for_timeout(400)
            return True
        except Exception:
            return False

    def _choose_typed(self, page, qid) -> bool:
        """A typed field with a suggestion list (like City): type it, then pick the first match."""
        try:
            loc = page.locator(f'[data-jhq="{qid}"]')
            value = loc.input_value(timeout=3000)
            if not value:
                return False
            loc.fill("")
            loc.press_sequentially(value, delay=40)
            for _ in range(8):
                page.wait_for_timeout(400)
                opts = page.locator("[role=option]:visible")
                if opts.count():
                    texts = [t.strip() for t in opts.all_inner_texts()]
                    want = match_option(texts, value) or texts[0]
                    opts.nth(texts.index(want)).click(timeout=4000)
                    self.log(f"Chose “{want[:60]}” from the list")
                    return True
            return False
        except Exception:
            return False


AGENT = Agent()
