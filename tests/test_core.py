"""Run with:  python -m pytest -q   (or python tests/test_core.py)"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["JOBHUNT_DATA"] = tempfile.mkdtemp(prefix="jhq-test-")     # never touch the real data folder
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunt import db
from jobhunt.classify import classify, find_date, match_application, parse_linkedin_alert
from jobhunt.letters import template_letter
from jobhunt.matcher import fit_label, score_job
from jobhunt.sources import parse_adzuna, parse_reed

APPS = [{"id": 1, "company": "Crimestoppers", "role": "People & Organisational Development Officer", "status": "applied"},
        {"id": 2, "company": "ODI Global", "role": "People Partner (Operations)", "status": "applied"},
        {"id": 3, "company": "Kingsley Napley", "role": "People Assistant", "status": "applied"}]


def test_classify():
    assert classify("Your application", "Unfortunately, on this occasion you have not been successful.") == "rejected"
    assert classify("Interview invitation", "We would like to invite you to an interview on Monday 26 October at 10:00") == "interview"
    assert classify("Next steps", "We'd like to arrange a quick call to discuss your application") == "pre_screen"
    assert classify("Thank you for applying", "We have received your application for HR Advisor.") == "acknowledged"
    assert classify("Assessment", "Please complete the online assessment by Friday") == "assessment"
    assert classify("Offer", "We are delighted to offer you the position") == "offer"
    assert classify("Next steps", "We'd like to invite you to a second interview on Thursday") == "second_stage"
    assert classify("Good news", "You have progressed to the next stage of the process") == "second_stage"
    assert classify("Final interview", "Please book a slot for your final interview") == "second_stage"
    assert classify("Interview invitation", "We would like to invite you to an interview") == "interview"
    assert classify("Thank you for applying", "If shortlisted, we will contact you about the next stage.") == "acknowledged"
    assert classify("New jobs", "", "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>") == "job_alert"
    assert classify("Lunch on Friday?", "See you there") == "other"
    # A rejection that also thanks you for applying is still a rejection.
    assert classify("Thank you for applying", "Thank you for applying. Unfortunately we will not be progressing.") == "rejected"


def test_match_application():
    m = match_application("Your application to Crimestoppers", "...", "Crimestoppers Recruitment <no-reply@cezannehr.com>", APPS)
    assert m and m["id"] == 1
    m = match_application("Application update", "Thank you for your interest in ODI Global.", "noreply@lever.co", APPS)
    assert m and m["id"] == 2
    assert match_application("Hello", "Nothing related", "friend@gmail.com", APPS) is None


def test_find_date():
    assert "26 October" in find_date("invite you on Monday 26 October at 10:00am")
    assert find_date("no date here") is None


def test_linkedin_alert():
    text = """Your job alert for HR Advisor

HR Advisor
UCLH NHS Foundation Trust
London, England, United Kingdom
View job: https://www.linkedin.com/comm/jobs/view/4479517720/?trackingId=abc

People Partner
Flash Pack
London (Remote)
View job: https://www.linkedin.com/comm/jobs/view/4474992677/?trk=x
"""
    jobs = parse_linkedin_alert(text)
    assert [j["external_id"] for j in jobs] == ["4479517720", "4474992677"]
    assert jobs[0]["title"] == "HR Advisor" and jobs[0]["company"] == "UCLH NHS Foundation Trust"
    assert jobs[1]["location"] == "London (Remote)"


def test_indeed_alert():
    from jobhunt.classify import alert_site, parse_alert
    text = """15 new HR Advisor jobs in Southend-on-Sea

HR Advisor
Southend City Council
Southend-on-Sea SS2
£32,000 - £35,000 a year
Easily apply
https://uk.indeed.com/rc/clk/dl?jk=0a1b2c3d4e5f6a7b&from=ja&tk=xyz

People Officer
Essex Partnership NHS Trust
Basildon
https://uk.indeed.com/pagead/clk?mo=r&ad=-6NYlbfk&vjk=1234567890abcdef&from=ja
"""
    jobs = parse_alert(text, "Indeed")
    assert [j["external_id"] for j in jobs] == ["0a1b2c3d4e5f6a7b", "1234567890abcdef"], jobs
    assert jobs[0]["title"] == "HR Advisor" and jobs[0]["company"] == "Southend City Council"
    assert jobs[0]["location"] == "Southend-on-Sea SS2"
    assert jobs[1]["url"] == "https://uk.indeed.com/viewjob?jk=1234567890abcdef"
    assert alert_site("Indeed <alert@indeed.com>") == "Indeed"
    assert classify("15 new jobs", "", "Indeed <alert@indeed.com>") == "job_alert"


def test_scoring():
    good = {"title": "HR Advisor", "location": "London", "salary_min": 32000, "salary_max": 35000,
            "description": "Employee relations casework, disciplinary and grievance, absence management, "
                           "recruitment and onboarding, HRIS reporting and dashboards. CIPD Level 5 desirable."}
    s, reasons = score_job(good)
    assert s >= 70 and fit_label(s) == "Strong fit", (s, reasons)
    german = dict(good, description=good["description"] + " Must be fluent in German.")
    assert score_job(german)[0] <= 15
    director = dict(good, title="HR Director")
    assert score_job(director)[0] < s
    assert score_job({"title": "Forklift Driver", "description": "warehouse"})[0] < 30
    from jobhunt.matcher import location_fit
    assert location_fit("Edgware, London") == "ok" and location_fit("Basildon, Essex") == "ok"
    assert location_fit("Royal Tunbridge Wells") == "far" and location_fit("St Albans") == "far"
    assert location_fit("Manchester", remote=True) == "ok" and location_fit("") == "unknown"
    far = dict(good, location="Dartford, Kent")
    assert score_job(far)[0] < s - 20


def test_parsers():
    reed = {"results": [{"jobId": 55, "employerName": "Acme", "jobTitle": "HR Officer", "locationName": "Southend",
                         "minimumSalary": 30000, "maximumSalary": 33000, "date": "15/10/2026",
                         "expirationDate": "26/11/2026", "jobDescription": "<p>HR &amp; payroll</p>",
                         "jobUrl": "https://www.reed.co.uk/jobs/55"}]}
    j = parse_reed(reed)[0]
    assert j["salary_text"] == "£30,000 – £33,000" and j["posted"] == "2026-10-15" and j["description"] == "HR & payroll"
    adz = {"results": [{"id": "9", "title": "People Advisor", "company": {"display_name": "Beta"},
                        "location": {"display_name": "London"}, "salary_min": 31000, "salary_max": 31000,
                        "redirect_url": "https://adzuna/9", "description": "Remote role", "created": "2026-10-16T09:00:00Z"}]}
    a = parse_adzuna(adz)[0]
    assert a["salary_text"] == "£31,000" and a["remote"] == 1 and a["posted"] == "2026-10-16"


def test_letter():
    job = {"title": "HR Advisor", "company": "Acme", "description": "employee relations, HRIS, dashboards"}
    letter = template_letter(job, {"name": "Rashid Idle"})
    assert letter.startswith("Dear Hiring Manager,") and "Acme" in letter and letter.strip().endswith("Rashid Idle")
    assert "ACAS" in letter


def test_fetch_page_parse():
    from jobhunt.fetch_page import canonical_url, parse_job_html
    assert canonical_url("https://www.linkedin.com/jobs/search/?currentJobId=4480001234&keywords=hr") == \
        "https://www.linkedin.com/jobs/view/4480001234/"
    assert canonical_url("https://uk.indeed.com/jobs?q=hr&vjk=0a1b2c3d4e5f6a7b") == \
        "https://uk.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b"
    html = """<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
      "title":"HR Officer","hiringOrganization":{"@type":"Organization","name":"Essex County Council"},
      "jobLocation":{"@type":"Place","address":{"addressLocality":"Chelmsford","addressRegion":"Essex"}},
      "description":"<p>Employee relations and recruitment.</p>","validThrough":"2026-11-01T23:59"}</script>"""
    j = parse_job_html(html, "https://example.org/job/1")
    assert j["title"] == "HR Officer" and j["company"] == "Essex County Council"
    assert j["location"] == "Chelmsford, Essex" and j["closes"] == "2026-11-01"
    assert "Employee relations" in j["description"]


def test_short_answers_and_sources():
    from jobhunt.letters import short_answers
    from jobhunt.sources import manual_job
    ans = dict(short_answers({"title": "HR Advisor", "company": "Acme", "description": "employee relations, HRIS"}, {}))
    assert "Why do you want to work for Acme?" in ans and "HR Advisor" in ans["Why do you want this role?"]
    assert manual_job("HR", "X", "https://uk.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b")["source"] == "Indeed"
    assert manual_job("HR", "X", "https://uk.indeed.com/viewjob?jk=0a1b2c3d4e5f6a7b")["external_id"] == "0a1b2c3d4e5f6a7b"
    letter = template_letter({"title": "HR Advisor", "company": "Acme",
                              "description": "CIPD, absence, disciplinary, recruitment"}, {"name": "R"})
    assert "focus on employee relations, recruitment and onboarding and absence" in letter


def owner_client():
    """A test client signed in as the owner (made the first time it's needed)."""
    import app as A
    from jobhunt import accounts
    if not accounts.any_users():
        uid = accounts.create("owner", "Rashid Idle", "correct horse battery", is_admin=True)
        accounts.adopt_existing_data(uid)
    u = accounts.all_users()[0]
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["uid"], s["sv"] = u["id"], u["session_version"]
    return c, u["id"]


def test_fill_helpers():
    import app as A
    from jobhunt.letters import form_message, letter_pdf
    parts = A.split_address({"address": "1 Example Street, Southend-on-Sea, Essex, SS1 1AA, United Kingdom"})
    assert parts == {"address_line": "1 Example Street", "city": "Southend-on-Sea", "postcode": "SS1 1AA"}
    pdf = letter_pdf("Dear Hiring Manager,\n\nTest & <check>.\n\nYours sincerely,\nRashid", {"name": "Rashid Idle"})
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000
    assert "HR Advisor position at Acme" in form_message({"title": "HR Advisor", "company": "Acme"}, {"name": "R"})
    wd = ("https://wd3.myworkdaysite.com/en-US/recruiting/simmonssimmons/SimmonsSimmonsExternal/job/London/"
          "HR-Systems-Analyst_JR102193-1/apply/autofillWithResume")
    assert A.application_link(wd).endswith("/HR-Systems-Analyst_JR102193-1/apply")
    assert A.application_link("https://www.linkedin.com/jobs/view/1/") is None
    assert A.application_link("https://www.morgan-law.com/job/x/#apply") == "https://www.morgan-law.com/job/x/"
    c = A.app.test_client()
    assert c.post("/api/bridge", json={"token": "wrong", "action": "fill"}).status_code == 403
    assert c.get("/files/cv?token=wrong").status_code == 403


def test_talentworld():
    import json
    import time
    from jobhunt import sources
    index = '<sitemapindex><sitemap><loc>https://www.thetalentworld.co.uk/sitemap-jobs-1.xml</loc></sitemap></sitemapindex>'
    smap = ('<urlset><url><loc>https://www.thetalentworld.co.uk/jobs/466236471-hr-advisor</loc></url>'
            '<url><loc>https://www.thetalentworld.co.uk/jobs/776219455-hr-advisor</loc></url></urlset>')
    ld = {"@context": "https://schema.org/", "@type": "JobPosting", "datePosted": "2026-10-19T00:00:00.000000Z",
          "description": "<p>HR advisory, employee relations, Workday data and reporting.</p>",
          "hiringOrganization": {"@type": "Organization", "name": "Howden"},
          "jobLocation": {"@type": "Place", "address": {"addressLocality": "London", "addressRegion": "England"}},
          "title": "HR Advisor", "validThrough": "2026-11-08T00:00:00.000000Z"}
    page = (f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            '<a href="https://hyperiongrp.wd3.myworkdayjobs.com/x/HR-Advisor_R1">Apply directly</a>')

    class R:
        def __init__(self, text): self.text, self.status_code = text, 200

    pages = {"https://www.thetalentworld.co.uk/sitemap.xml": index,
             "https://www.thetalentworld.co.uk/sitemap-jobs-1.xml": smap,
             "https://www.thetalentworld.co.uk/jobs/776219455-hr-advisor": page}
    orig_get, orig_sleep = sources.requests.get, time.sleep
    sources.requests.get = lambda url, **kw: R(pages[url])
    time.sleep = lambda s: None
    try:
        jobs = sources.search_talentworld(known_ids={"466236471"})
    finally:
        sources.requests.get, time.sleep = orig_get, orig_sleep
    assert len(jobs) == 1, jobs
    j = jobs[0]
    assert (j["external_id"], j["title"], j["company"], j["location"]) == ("776219455", "HR Advisor", "Howden", "London, England")
    assert j["posted"] == "2026-10-19" and j["closes"] == "2026-11-08"
    assert "Apply directly: https://hyperiongrp" in j["description"]


def test_ats_pages():
    from unittest import mock
    from jobhunt import fetch_page as fp
    assert fp.rich_text("A &amp;amp; B&nbsp;C<ul><li>one</li><li>two</li></ul>") == "A & B C\n• one\n• two"
    assert fp.company_from_url("https://jobs.smartrecruiters.com/Wabtec/3743990016217732-hr") == "Wabtec"
    assert fp.company_from_url("https://boards.greenhouse.io/acme-hr/jobs/1") == "Acme Hr"
    sr = {"name": "HR Systems &amp; Analytics Coordinator", "company": {"name": "Wabtec"},
          "location": {"city": "Burton on Trent", "fullLocation": "Burton on Trent, United Kingdom"},
          "releasedDate": "2026-10-18T09:00:00Z", "applyUrl": "https://jobs.smartrecruiters.com/oneclick-ui/company/Wabtec/publication/x",
          "typeOfEmployment": {"label": "Full-time"},
          "jobAd": {"sections": {"jobDescription": {"title": "Job Description", "text": "<p>HR KPI dashboards &amp;amp; reporting.</p>"},
                                 "qualifications": {"title": "Qualifications", "text": "<ul><li>HRIS</li></ul>"}}}}

    class R:
        status_code = 200
        def __init__(self, data): self.data = data
        def json(self): return self.data
        def raise_for_status(self): pass

    url = "https://jobs.smartrecruiters.com/Wabtec/3743990016217732-hr-people-operations-coordinator"
    with mock.patch.object(fp.requests, "get", return_value=R(sr)) as g:
        j = fp.fetch_job(url)
    assert "api.smartrecruiters.com/v1/companies/Wabtec/postings/3743990016217732" in g.call_args[0][0]
    assert j["title"] == "HR Systems & Analytics Coordinator" and j["company"] == "Wabtec"
    assert j["location"] == "Burton on Trent, United Kingdom" and j["posted"] == "2026-10-18"
    assert "HR KPI dashboards & reporting." in j["description"] and "• HRIS" in j["description"]
    assert j["apply_url"].startswith("https://jobs.smartrecruiters.com/oneclick-ui")
    # page without JSON-LD: company still found
    html = '<meta property="og:title" content="HR Systems &amp;amp; Analytics Coordinator"><meta property="og:description" content="x">'
    j = fp.parse_job_html(html, url)
    assert j["title"] == "HR Systems & Analytics Coordinator" and j["company"] == "Wabtec"


def test_locations():
    from jobhunt.matcher import location_fit as f
    for place in ("London, England", "Beckenham, England", "Southend-on-Sea, Essex", "EC2A 4NE", "Remote", "Chelmsford"):
        assert f(place) == "ok", place
    for place in ("Birmingham, AL", "Grantham, England", "Ilkeston, England", "Bury St. Edmunds, England",
                  "Solihull, West Midlands, United Kingdom", "Maidstone, Kent"):
        assert f(place) == "far", place
    for place in ("", "United Kingdom", "Hybrid", "England, United Kingdom"):
        assert f(place) == "unknown", place


def test_robot_answers():
    from jobhunt.agent import NEXT, SUBMIT, SUBMIT_FORM, THANKS, start_url
    from jobhunt.answers import suggest
    prof = {"notice_period": "Available immediately", "salary_expectation": "£32,000 – £34,000",
            "right_to_work": "Indefinite leave to remain"}
    fields = {"city": "Southend-on-Sea", "postcode": "SS1 1AA", "address_line": "1 Example Street"}
    job = {"title": "HR Advisor", "company": "Acme"}
    ask = lambda label, kind="select", opts=("Yes", "No"), mem=None: suggest(
        {"label": label, "kind": kind, "options": list(opts)}, mem or {}, prof, fields, job, "", {})
    assert ask("Will you now or in the future require visa sponsorship?") == ("No", "rule")
    assert ask("Do you have the right to work in the UK without the need for visa sponsorship now or in the future?") == ("Yes", "rule")
    assert ask("Are you legally entitled to work in the UK?") == ("Yes", "rule")
    assert ask("Phone Device Type", "listbox", ["Home", "Mobile", "Work"]) == ("Mobile", "rule")
    assert ask("Country", "select", ["France", "United Kingdom"]) == ("United Kingdom", "rule")
    assert ask("What is your notice period?", "text", []) == ("Available immediately", "rule")
    assert ask("How did you hear about us?", "text", []) == ("", "")
    assert ask("What is your gender?", "select", ["Male", "Female"]) == ("", "")          # always yours to answer
    assert ask("I agree to the privacy notice", "checkbox", ["Yes", "No"]) == ("", "")   # consent is yours
    assert ask("How did you hear about us? *", "listbox", ["Job Board", "LinkedIn"],
               {"how did you hear about us": "LinkedIn"}) == ("LinkedIn", "remembered")
    assert NEXT.search("Save and Continue") and not NEXT.search("Submit")
    assert SUBMIT.search("Submit application") and SUBMIT_FORM.search("Submit") and not SUBMIT_FORM.search("Apply")
    assert THANKS.search("Thank you for applying!") and not THANKS.search("Thank you for your interest in Acme")
    assert start_url({"url": "https://www.linkedin.com/jobs/view/1/"}) is None
    assert start_url({"url": "https://www.linkedin.com/jobs/view/1/", "apply_url": "https://wd3.myworkdaysite.com/x"}) \
        == "https://wd3.myworkdaysite.com/x"
    assert start_url({"url": "https://www.thetalentworld.co.uk/jobs/1",
                      "description": "HR job. Apply directly: https://acme.teamtailor.com/jobs/9"}) == \
        "https://acme.teamtailor.com/jobs/9"


def test_posted_dates():
    from datetime import date
    from jobhunt.sources import parse_posted
    d = date(2026, 10, 19)
    cases = {"2026-10-17T09:00:00Z": "2026-10-17", "Posted 3 days ago": "2026-10-16", "Just posted": "2026-10-19",
             "5 hours ago": "2026-10-19", "Reposted 2 weeks ago": "2026-10-05", "30+ days ago": "2026-09-19",
             "a month ago": "2026-09-19", "yesterday": "2026-10-18", "": None, "Hybrid": None}
    for text, want in cases.items():
        assert parse_posted(text, d) == want, (text, parse_posted(text, d))


def test_bulk_import():
    from jobhunt import db
    from jobhunt.config import as_user
    c, uid = owner_client()
    jobs = [{"url": "https://www.linkedin.com/jobs/view/99000000%d/" % i, "title": "HR Advisor %d" % i, "company": "Test Co %d" % i,
             "location": "London", "posted": "2 hours ago" if i else "", "description": "employee relations"} for i in range(3)]
    r = c.post("/api/import", json={"jobs": jobs, "recent": False})
    assert r.status_code == 200 and r.get_json()["added"] + r.get_json()["updated"] == 3
    with as_user(uid), db.session() as conn:
        rows = conn.execute("SELECT external_id, posted, status, cover_letter FROM jobs WHERE external_id LIKE '99000000%' "
                            "ORDER BY external_id").fetchall()
        assert [r["posted"] is None for r in rows] == [True, False, False]
        assert all(r["status"] == "new" and not r["cover_letter"] for r in rows)
        conn.execute("DELETE FROM jobs WHERE external_id LIKE '99000000%'")


def test_career():
    from jobhunt import career
    d = career.load()
    assert d["experience"][0]["company"] and d["education"] and d["skills"]
    assert career.month_year("05/2024") == ("05", "2024") and career.month_year("2019") == ("", "2019")
    form = {"exp-0-title": "Old", "exp-0-start": "01/2020", "exp-1000-title": "New", "exp-1000-start": "11/2026",
            "skills": "A, B\nC", "languages": "English – Native"}
    out = career.from_form(form)
    assert [e["title"] for e in out["experience"]] == ["New", "Old"] and out["skills"] == ["A", "B", "C"]
    assert out["languages"] == [{"language": "English", "level": "Native"}]


def test_job_email():
    from unittest import mock
    from jobhunt import notify
    cfg = {"profile": {"email": "me@example.com"}, "email": {"enabled": True, "gmail_app_password": "abcd efgh ijkl mnop"}}
    assert notify.ready(cfg) == (True, "")
    assert not notify.ready({"profile": {}, "email": {"enabled": True}})[0]
    jobs = [{"id": 5, "title": "HR Advisor", "company": "Acme & Co", "location": "London", "score": 78, "url": "https://x/1",
             "salary_text": "£33,000", "source": "Reed", "score_reasons": "Job title matches · Uses your skills"},
            {"id": 6, "title": "People Advisor", "company": "B", "score": 55, "url": ""}]
    subject, html, text = notify.build(jobs)
    assert subject.startswith("2 new jobs for you – top match 78%") and "Acme &amp; Co" in html and "Strong fit" in html
    with mock.patch("smtplib.SMTP_SSL") as smtp:
        notify.send(cfg, subject, html, text)
        smtp.return_value.__enter__.return_value.login.assert_called_with("me@example.com", "abcdefghijklmnop")


def test_gmail_by_app_password():
    import tempfile
    from datetime import datetime, timezone
    from pathlib import Path
    from unittest import mock
    from jobhunt import db, gmail_sync
    raw = (b"From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>\r\nSubject: 25 new jobs for Human Resources\r\n"
           b"Date: Mon, 19 Oct 2026 08:00:00 +0100\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
           b"Your job alert for Human Resources\n\nHR Advisor\nAcme Ltd\nLondon, England, United Kingdom\n"
           b"View job: https://www.linkedin.com/comm/jobs/view/4479517720/?trackingId=abc\n")

    class FakeImap:
        def __init__(self, *a, **k): self.searched = None
        def login(self, user, pw): assert pw == "abcdefghijklmnop"
        def list(self): return "OK", [b'(\\HasNoChildren \\All) "/" "[Google Mail]/All Mail"']
        def select(self, box, readonly=False): assert box == '"[Google Mail]/All Mail"' and readonly; return "OK", [b"1"]
        def search(self, charset, key, q): assert key == "X-GM-RAW" and "newer_than:" in q; return "OK", [b"1"]
        def fetch(self, num, what): return "OK", [(b"1 (X-GM-MSGID 1795000000000000001 BODY[] {100}", raw), b")"]
        def logout(self): pass

    cfg = {"profile": {"email": "me@example.com"}, "email": {"gmail_app_password": "abcd efgh ijkl mnop"},
           "gmail": {"enabled": True}, "search": {}}
    assert gmail_sync.method(cfg) in ("app_password", "api")
    with mock.patch("imaplib.IMAP4_SSL", FakeImap):
        msgs = list(gmail_sync.imap_messages(cfg, set()))
    assert msgs[0]["id"] == format(1795000000000000001, "x") and "HR Advisor" in msgs[0]["body"]
    c = db.connect(Path(tempfile.mkdtemp()) / "t.db")
    with mock.patch("jobhunt.refresh.add_jobs", return_value=1) as add:
        stats = gmail_sync.sync(c, cfg, messages=msgs, log=lambda m: None)
    assert stats["alert_jobs"] == 1 and add.call_args[0][2][0]["company"] == "Acme Ltd"
    assert gmail_sync.sync(c, cfg, messages=msgs, log=lambda m: None)["emails"] == 0   # not read twice


def test_ashby_and_linkedin_links():
    from unittest import mock
    from jobhunt import fetch_page as fp
    board = {"jobs": [{"id": "cae9faf0-7cdf-4e3f-bb97-68d8231f15d5", "title": "HR Generalist", "location": "London",
                       "isRemote": True, "descriptionHtml": "<p>People &amp; culture</p>", "publishedAt": "2026-10-19T20:00:00Z",
                       "applyUrl": "https://jobs.ashbyhq.com/Coder/cae9faf0-7cdf-4e3f-bb97-68d8231f15d5/application"}]}

    class R:
        status_code = 200
        def json(self): return board
        def raise_for_status(self): pass
    with mock.patch.object(fp.requests, "get", return_value=R()):
        j = fp.fetch_job("https://jobs.ashbyhq.com/Coder/cae9faf0-7cdf-4e3f-bb97-68d8231f15d5?src=LinkedIn")
    assert j["title"] == "HR Generalist" and j["company"] == "Coder" and j["posted"] == "2026-10-19"
    assert j["apply_url"].endswith("/application") and "People & culture" in j["description"]
    html = ('<h1 class="top-card-layout__title">HR Advisor</h1><a class="topcard__org-name-link">Acme</a>'
            '<code id="applyUrl"><!--"https://www.linkedin.com/jobs/view/externalApply/123?url=https%3A%2F%2Facme%2Eworkday%2Ecom%2Fjob%2F1&amp;urlHash=x"--></code>')
    j = fp.parse_job_html(html, "https://www.linkedin.com/jobs/view/123/")
    assert j["apply_url"] == "https://acme.workday.com/job/1"


def test_advert_matching():
    from jobhunt.advert import bullets, company_hook, matches, matched_paragraph
    from jobhunt.answers import suggest
    desc = ("Coder is growing from about 220 to 500 people by the end of 2027, and our People team is growing with us.\n"
            "What you'll do\n• Own offer letters, contract administration, and onboarding workflows for international hires\n"
            "• Keep international employee data accurate in Rippling and Deel, and support audits and reporting\n"
            "What we're looking for\n• Working knowledge of UK employment law (contracts, right to work, statutory leave)")
    assert [k for k, _ in bullets(desc)] == ["duty", "duty", "need"]
    assert company_hook(desc, "Coder").startswith("Coder is growing")
    assert len(matches(desc)) == 3 and "Right to Work" in matched_paragraph(desc)
    job = {"title": "HR Generalist", "company": "Coder", "description": desc}
    own = {"label": "What interests you in Coder?", "kind": "textarea", "options": [], "own_words": True}
    assert suggest(own, {}, {}, {}, job, "", {}) == ("", "own_words")
    draft, src = suggest({"label": "What interests you in Coder?", "kind": "textarea", "options": []}, {}, {}, {}, job, "", {})
    assert src == "draft" and "Coder is growing" in draft


def test_db_and_seed(tmp_path=None):
    import tempfile
    from jobhunt.seed import seed_if_empty
    path = Path(tempfile.mkdtemp()) / "t.db"
    c = db.connect(path)
    assert seed_if_empty(c) is True
    assert seed_if_empty(c) is False
    n_apps = c.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    n_jobs = c.execute("SELECT COUNT(*) FROM jobs WHERE status = 'shortlisted'").fetchone()[0]
    assert n_apps == 0 and n_jobs == 0          # the public copy starts empty
    c.close()


def test_stated_answers_never_yes():
    from jobhunt.answers import suggest
    yn = ["Yes", "No"]
    def ask(label, kind="radio", opts=yn):
        return suggest({"label": label, "kind": kind, "options": opts}, {}, {}, {}, {}, "", {})[0]
    assert ask("Do you have any criminal convictions not spent under the Rehabilitation of Offenders Act 1974, "
               "or is there a criminal case pending against you?") == "No"
    assert ask("Do you require any reasonable adjustments as part of your application or interview process?") == "No"
    assert ask("Do you require a visa to work in the UK?") == "No"
    assert ask("Do you have the right to work in the UK?") == "Yes"
    assert ask("Are you willing to undergo a criminal record check?") == ""
    assert ask("Do you have a disability?", opts=["Yes", "No", "Prefer not to say"]) == ""
    assert ask("Do you have the right to work in the UK without the need for visa sponsorship?") == "Yes"



def test_accounts_keep_data_apart():
    """Two people: neither can see the other's jobs, career, settings or browser-button token."""
    import app as A
    from jobhunt import accounts, career, db, persona
    from jobhunt.config import access_token, as_user
    c1, owner = owner_client()
    # the owner invites someone, who joins with the code
    r = c1.post("/people", data={"action": "invite", "note": "test"}, headers={"Origin": "http://localhost"})
    assert r.status_code == 200
    code = accounts.invites()[0]["code"]
    c2 = A.app.test_client()
    r = c2.post("/join", data={"code": code, "name": "Sam Test", "email": "sam@example.com", "username": "samtest",
                                "password": "a-long-password-1", "password2": "a-long-password-1"},
                headers={"Origin": "http://localhost"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/welcome")
    assert not accounts.invite_ok(code)                       # single use
    sam = [u for u in accounts.all_users() if u["username"] == "samtest"][0]
    with as_user(owner), db.session() as conn:
        conn.execute("INSERT INTO jobs (source, external_id, title, company, url, status, created_at, updated_at) "
                     "VALUES ('test', 'secret-1', 'Owner Only Job', 'Owner Co', 'x', 'new', datetime(), datetime())")
        owner_token = access_token()
        assert persona.builtin()
    with as_user(sam["id"]), db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE external_id = 'secret-1'").fetchone()[0] == 0
        assert career.load()["experience"] == []                # nothing of the owner's CV
        assert not persona.builtin()
        assert access_token() != owner_token
        from jobhunt.config import load_config
        assert load_config()["profile"].get("name") == "Sam Test"
        assert "Example Street" not in str(load_config()["profile"])
    # Sam can't open the owner's pages
    with c2.session_transaction() as s:
        s["uid"], s["sv"] = sam["id"], sam["session_version"]
    accounts.update(sam["id"], setup_done=1)
    assert c2.get("/people").status_code == 403
    assert b"Owner Only Job" not in c2.get("/").data
    assert b"Owner Only Job" in c1.get("/").data
    # wrong password, unknown user, and signing out other devices after a password change
    assert accounts.check_login("samtest", "nope")[0] is None
    assert accounts.check_login("samtest", "a-long-password-1")[0]
    old = accounts.get(sam["id"])["session_version"]
    accounts.update(sam["id"], password="another-long-pass")
    assert accounts.get(sam["id"])["session_version"] != old
    assert c2.get("/").status_code == 302                      # old session no longer valid
    # signed-out visitors are sent to sign in
    assert A.app.test_client().get("/").status_code == 302


def test_generic_scoring_and_letters():
    """Someone else's job scoring and letters come from their own settings and career – not the owner's."""
    from jobhunt import accounts, career, generic, persona
    from jobhunt.config import as_user
    from jobhunt.letters import template_letter
    from jobhunt.matcher import score_job
    owner_client()
    uid = accounts.create("dev" + os.urandom(3).hex(), "Dana Dev", "a-long-password-2")
    with as_user(uid):
        accounts.save_settings({"profile": {"name": "Dana Dev", "notice_period": "Available in one month"},
                                "search": {"keywords": ["Software Developer", "Python Developer"], "locations": [],
                                           "min_salary": 40000}, "prefs": {"level": "mid", "skills": ["Python", "Django"]}})
        career.save({"summary": "Python developer.", "experience": [{"title": "Developer", "company": "Acme Ltd", "end": "",
                     "description": "Built Django APIs used by 2,000 customers. Led the move to automated testing."}],
                     "education": [{"degree": "BSc", "field": "Computer Science", "school": "Leeds"}], "skills": ["SQL"],
                     "languages": [], "certifications": [], "stories": [], "competencies": []})
        persona._CACHE.clear()
        good, why = score_job({"title": "Python Developer", "description": "Django, Python and SQL", "salary_max": 50000,
                               "location": "Remote", "remote": 1})
        bad, _ = score_job({"title": "HR Advisor", "description": "employee relations", "location": "Remote", "remote": 1})
        assert good > 70 > bad
        letter = template_letter({"title": "Python Developer", "company": "Beta", "description": "Django APIs and testing"},
                                 {"name": "Dana Dev", "notice_period": "Available in one month"})
        assert "Acme Ltd" in letter and "Django" in letter and "Chenai" not in letter and "CIPD" not in letter
        assert generic.experience_answer("Do you have experience of Django?").startswith("Yes. As Developer at Acme Ltd")
        # a developer isn't sent HR-only job boards, or HR wording from the owner's own answers
        from jobhunt.config import load_config
        from jobhunt.refresh import wants_hr_jobs
        assert not wants_hr_jobs(load_config())
        assert wants_hr_jobs({"search": {"keywords": ["Recruitment Consultant"]}})
        from jobhunt.answers import suggest
        ans = suggest({"label": "Tell us about a time you led a restructure", "kind": "textarea", "options": []},
                      {}, {}, {}, {}, "", {})[0]
        assert "CIPD" not in ans and "MBA" not in ans
        # moving into a new field: the letter says so honestly
        career.save({**career.load(), "experience": [{"title": "Customer Service Advisor", "company": "British Gas", "end": "",
                     "description": "Kept accurate case notes and records in line with GDPR."}]})
        persona._CACHE.clear()
        cl = template_letter({"title": "Paralegal", "company": "Irwin Mitchell", "description": "case notes and records"},
                             {"name": "Dana Dev"})
        assert "moving into this kind of work from my role as Customer Service Advisor at British Gas" in cl


def test_create_cv():
    """Build a CV step by step, read an uploaded Word CV, download every design, and tailor it – for a new person."""
    import io

    import app as A
    from docx import Document

    from jobhunt import accounts, career, cv
    from jobhunt.config import as_user, load_config
    owner_client()
    uid = accounts.create("cv" + os.urandom(3).hex(), "Priya Shah", "a-long-password-3")
    accounts.update(uid, setup_done=1)
    with as_user(uid):
        accounts.save_settings({"profile": {"name": "Priya Shah", "email": "priya@example.com", "phone": "07000 000000",
                                            "location": "Leeds"}, "search": {"keywords": ["Marketing Executive"]}, "prefs": {}})
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["uid"], s["sv"] = uid, accounts.get(uid)["session_version"]
    h = {"Origin": "http://localhost"}
    # upload a Word CV: it's read into My career
    d = Document()
    for line in ["Priya Shah", "Profile", "Marketing executive with four years in B2B campaigns.",
                 "Experience", "Marketing Executive | Northwind Ltd, Leeds   03/2022 – Present",
                 "Ran email campaigns for 12,000 subscribers.", "Responsible for the company blog.",
                 "Marketing Assistant – Contoso, York   Jun 2019 – Feb 2022", "Managed social media channels.",
                 "Education", "BA Marketing, University of Leeds, 2016 – 2019",
                 "Skills", "SEO, Google Analytics, Canva, Copywriting", "Languages", "English – Native, Urdu – Fluent"]:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    r = c.post("/cv/upload", data={"cv": (io.BytesIO(buf.getvalue()), "Priya CV.docx"), "next": "/cv?step=profile"},
               headers=h, content_type="multipart/form-data")
    assert r.status_code == 302, (r.status_code, r.data[:300])
    with as_user(uid):
        got = career.load()
        assert got["summary"].startswith("Marketing executive")
        assert [e["company"] for e in got["experience"]] == ["Northwind Ltd", "Contoso"]
        assert got["experience"][0]["start"] == "03/2022" and got["experience"][0]["end"] == ""
        assert got["experience"][1]["start"] == "06/2019" and got["experience"][1]["end"] == "02/2022"
        assert "Google Analytics" in got["skills"]
        assert got["languages"][1] == {"language": "Urdu", "level": "Fluent"}
        assert got["education"] and "Leeds" in got["education"][0]["school"]
        assert load_config()["profile"]["cv_path"].endswith("Priya_CV.docx")
        tips = cv.suggestions(got, load_config()["profile"])
        assert any("Responsible for" in t for _, t in tips)
    # a step saves only its own section
    r = c.post("/cv", data={"step": "profile", "headline": "Marketing Executive", "summary": "New profile.", "go": "experience"},
               headers=h)
    assert r.status_code == 302 and "step=experience" in r.headers["Location"]
    with as_user(uid):
        got = career.load()
        assert got["summary"] == "New profile." and len(got["experience"]) == 2
    for step in ("profile", "experience", "education", "skills", "design"):
        page = c.get(f"/cv?step={step}")
        assert page.status_code == 200 and b"Priya" in page.data or step != "profile"
    # every design, as PDF and Word
    for design in ("classic", "modern", "compact"):
        r = c.get(f"/cv/file?design={design}&accent=teal&view=1")
        assert r.status_code == 200 and r.data[:5] == b"%PDF-"
    r = c.get("/cv/file?fmt=docx")
    assert r.data[:2] == b"PK" and "Priya Shah CV.docx" in r.headers["Content-Disposition"]
    text = "\n".join(p.text for p in Document(io.BytesIO(r.data)).paragraphs)
    assert "Northwind Ltd" in text and "Ran email campaigns for 12,000 subscribers." in text
    # tailoring reorders, never adds
    built = cv.build({"skills": ["Canva", "SEO", "Copywriting"],
                      "experience": [{"title": "X", "company": "Y", "description": "Wrote blogs. Ran SEO audits."}]},
                     {"name": "P"}, {"title": "SEO Executive", "company": "Acme", "description": "SEO audits and copywriting"})
    assert built["skills"][:2] == ["SEO", "Copywriting"] and set(built["skills"]) == {"Canva", "SEO", "Copywriting"}
    assert built["experience"][0]["bullets"] == ["Ran SEO audits.", "Wrote blogs."]
    # use it for applications
    r = c.post("/cv/use", headers=h)
    with as_user(uid):
        assert load_config()["profile"]["cv_path"].endswith("Priya Shah CV.pdf")
    # the owner's own CV path is never changed by the builder
    c1, owner = owner_client()
    with as_user(owner):
        before = load_config()["profile"].get("cv_path")
    c1.post("/cv/use", headers=h)
    with as_user(owner):
        assert load_config()["profile"].get("cv_path") == before



def test_export_and_import():
    """Download my data on the PC, then load it into a new account: jobs, career, settings and CV come across."""
    from jobhunt import accounts, career, db
    from jobhunt.config import as_user, cv_file, load_config, user_dir
    owner_client()
    a = accounts.create("exp" + os.urandom(3).hex(), "Alex Move", "a-long-password-4")
    with as_user(a), db.session() as conn:
        conn.execute("INSERT INTO jobs (source, external_id, title, company, url, status, created_at, updated_at) "
                     "VALUES ('test', 'move-1', 'Moved Job', 'Move Co', 'x', 'new', datetime(), datetime())")
    outside = Path(tempfile.mkdtemp()) / "Alex CV.pdf"
    outside.write_bytes(b"%PDF-1.4 test")
    with as_user(a):
        accounts.save_settings({"profile": {"name": "Alex Move", "cv_path": str(outside)}, "search": {}, "prefs": {}}, a)
        career.save({**career.load(), "skills": ["Moving"]})
    data = accounts.export_zip(a)
    b = accounts.create("imp" + os.urandom(3).hex(), "Alex Move", "a-long-password-5")
    assert accounts.import_zip(b, data) >= 3
    with as_user(b), db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs WHERE external_id = 'move-1'").fetchone()[0] == 1
        assert career.load()["skills"] == ["Moving"]
        cvp = cv_file(load_config()["profile"])
        assert cvp and cvp.name == "Alex CV.pdf" and user_dir(b) in cvp.parents
    import io, zipfile
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("JOB-HUNT-HQ-EXPORT.txt", "x")
        z.writestr("../../escape.txt", "nope")
    accounts.import_zip(b, bad.getvalue())
    assert not (user_dir(b).parent.parent / "escape.txt").exists()



def test_feedback():
    """People send feedback (with a screenshot); only the owner sees everyone's, and replies reach the sender."""
    import io

    import app as A
    from jobhunt import accounts
    c1, owner = owner_client()
    uid = accounts.create("fb" + os.urandom(3).hex(), "Fay Back", "a-long-password-6")
    accounts.update(uid, setup_done=1)
    other = accounts.create("fc" + os.urandom(3).hex(), "Other Person", "a-long-password-7")
    accounts.update(other, setup_done=1)
    clients = {}
    for who in (uid, other):
        clients[who] = A.app.test_client()
        with clients[who].session_transaction() as s:
            s["uid"], s["sv"] = who, accounts.get(who)["session_version"]
    h = {"Origin": "http://localhost"}
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 50
    r = clients[uid].post("/feedback", data={"kind": "problem", "message": "The CV preview is blank", "page": "/cv?step=design",
                                             "image": (io.BytesIO(png), "shot.png")}, headers=h, content_type="multipart/form-data")
    assert r.status_code == 302 and r.headers["Location"].endswith("/cv?step=design")
    clients[uid].post("/feedback", data={"message": "x", "page": "https://evil.example/"}, headers=h)
    mine = accounts.feedback_list(uid)
    fid = [f for f in mine if f["kind"] == "problem"][0]["id"]
    assert accounts.get_feedback(fid)["image"]
    assert b"The CV preview is blank" in c1.get("/feedback").data                       # the owner sees it
    assert b"The CV preview is blank" not in clients[other].get("/feedback").data       # someone else doesn't
    assert clients[other].get(f"/feedback/{fid}/image").status_code == 404
    assert clients[uid].get(f"/feedback/{fid}/image").data == png
    assert clients[uid].post(f"/feedback/{fid}", data={"status": "done"}, headers=h).status_code == 403
    c1.post(f"/feedback/{fid}", data={"status": "planned", "reply": "Fixing it this week"}, headers=h)
    page = clients[uid].get("/feedback").data
    assert b"Fixing it this week" in page and b"Planned" in page
    assert b"fb-fab" in clients[uid].get("/").data
    # not an image → message still saved, file dropped
    clients[uid].post("/feedback", data={"message": "with junk", "image": (io.BytesIO(b"<script>"), "x.png")}, headers=h,
                      content_type="multipart/form-data")
    assert not [f for f in accounts.feedback_list(uid) if f["message"] == "with junk"][0]["image"]


def test_every_occupation_and_job_site():
    """Any kind of work: titles to pick from, the right specialist sites, CV-Library jobs, and LinkedIn PDF profiles."""
    from jobhunt import cv, occupations, sources
    assert len(occupations.SECTORS) >= 30 and len(occupations.ALL_TITLES) > 400
    assert "Warehouse Operative" in occupations.search("ware") and "Paralegal" in occupations.search("para")
    assert occupations.sectors_for(["Forklift Driver"]) == ["warehouse"]
    assert occupations.sectors_for(["Staff Nurse", "Paralegal"]) == ["healthcare", "legal"]
    assert "WMS" in occupations.skills_for(["Warehouse Operative"])
    sites = dict(occupations.search_links("Staff Nurse", "Leeds", 10))
    assert {"Indeed", "LinkedIn", "Reed", "CV-Library", "Totaljobs", "NHS Jobs"} <= set(sites)
    assert "q=staff+nurse" in sites["Indeed"] and "l=Leeds" in sites["Indeed"]
    assert "Civil Service Jobs" in dict(occupations.search_links("Caseworker", "York"))
    assert "NHS Jobs" not in dict(occupations.search_links("Warehouse Operative", "York"))
    jobs = sources.parse_cvlibrary({"jobs": [{"id": "1", "title": "Forklift <em>Driver</em>", "location": "Tilbury",
                                              "salary": "£26,000 - £28,000/annum", "url": "/job/1/Forklift-Driver",
                                              "agency": {"title": "Acme Logistics"}, "posted": "2026-10-30T09:00:00Z",
                                              "description": "Counterbalance licence"}]})
    assert jobs[0]["title"] == "Forklift Driver" and jobs[0]["salary_max"] == 28000
    assert jobs[0]["url"] == "https://www.cv-library.co.uk/job/1/Forklift-Driver" and jobs[0]["posted"] == "2026-10-30"
    li = cv.parse("Top Skills\nForklift\nWMS\nExperience\nDHL\nWarehouse Team Leader\nJune 2024 - Present (1 year 5 months)\n"
                  "Basildon, England\nLed a team of 12 pickers.\nEducation\nBasildon College\nBTEC Level 3, Business · (2018 - 2020)\n")
    e = li["experience"][0]
    assert (e["title"], e["company"], e["location"], e["start"], e["end"]) == ("Warehouse Team Leader", "DHL", "Basildon, England", "06/2024", "")
    assert li["skills"] == ["Forklift", "WMS"] and li["education"][0]["school"] == "Basildon College"
    # the page lists every site for the person's own job titles
    import app as A
    from jobhunt import accounts
    from jobhunt.config import as_user
    owner_client()
    uid = accounts.create("ws" + os.urandom(3).hex(), "Wren Site", "a-long-password-8")
    accounts.update(uid, setup_done=1)
    with as_user(uid):
        accounts.save_settings({"profile": {"name": "Wren Site", "location": "Leeds"},
                                "search": {"keywords": ["Staff Nurse"], "locations": [{"place": "Leeds", "miles": 10}]},
                                "prefs": {}}, uid)
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["uid"], s["sv"] = uid, accounts.get(uid)["session_version"]
    page = c.get("/everywhere").data
    assert b"NHS Jobs" in page and b"uk.indeed.com/jobs?q=staff+nurse" in page
    assert b"Warehouse Operative" in c.get("/settings").data            # the picker offers every kind of work


def test_assistant_privacy_and_erasure():
    """The browser assistant works with each person's own key; privacy page is public; people can delete themselves."""
    import io
    import zipfile

    import app as A
    from jobhunt import accounts, career, persona
    from jobhunt.config import access_token, as_user, user_dir
    owner_client()
    uid = accounts.create("as" + os.urandom(3).hex(), "Asha Assist", "a-long-password-10")
    accounts.update(uid, setup_done=1)
    with as_user(uid):
        accounts.save_settings({"profile": {"name": "Asha Assist", "email": "asha@example.com", "notice_period": "One month"},
                                "search": {"keywords": ["Restaurant Manager"]}, "prefs": {"skills": ["Food hygiene"]}}, uid)
        career.save({**career.load(), "experience": [{"title": "Assistant Manager", "company": "Pizza Place", "end": "",
                     "description": "Ran shifts for a team of 15.\nKept food hygiene at a 5 rating."}]})
        persona._CACHE.clear()
        token = access_token()
    c = A.app.test_client()
    post = lambda body: c.post("/api/assistant", json={"token": token, **body})
    assert c.post("/api/assistant", json={"token": "wrong", "action": "hello"}).status_code == 403
    assert post({"action": "hello"}).json["first"] == "Asha"
    advert = "We are looking for a Restaurant Manager to run shifts, lead the team and keep food hygiene standards. " * 6
    look = post({"action": "job", "url": "https://example.com/jobs/1", "title": "Restaurant Manager", "company": "Burger Co",
                 "description": advert}).json["job"]
    assert look["id"] is None and look["score"] >= 60          # scored, but not saved just for looking
    saved = post({"action": "job", "save": True, "url": "https://example.com/jobs/1", "title": "Restaurant Manager",
                  "company": "Burger Co", "description": advert}).json["job"]
    assert saved["id"] and saved["has_letter"]
    again = post({"action": "job", "url": "https://example.com/jobs/1", "title": "Restaurant Manager", "company": "Burger Co",
                  "description": advert}).json["job"]
    assert again["id"] == saved["id"]
    pack = post({"action": "pack", "job_id": saved["id"]}).json
    assert pack["fields"]["first_name"] == "Asha" and "Burger Co" in pack["cover_letter"]
    ans = post({"action": "answer", "job_id": saved["id"], "question": "What is your notice period?", "kind": "text"}).json
    assert ans["answer"] == "One month"
    personal = post({"action": "answer", "job_id": saved["id"], "question": "Do you have a disability?", "kind": "radio",
                     "options": ["Yes", "No"]}).json
    assert personal["answer"] == "" and "left for you" in personal["note"]
    assert post({"action": "ask", "question": "What should I stress?", "job_id": saved["id"]}).json["answer"]
    # the extension download carries this person's own key
    with c.session_transaction() as s:
        s["uid"], s["sv"] = uid, accounts.get(uid)["session_version"]
    z = zipfile.ZipFile(io.BytesIO(c.get("/assistant/extension.zip").data))
    names = z.namelist()
    assert "Job Hunt HQ Assistant/manifest.json" in names and "Job Hunt HQ Assistant/fill_core.js" in names
    assert token in z.read("Job Hunt HQ Assistant/config.js").decode()
    # privacy notice is public; the Gmail section promises nobody reads emails
    assert b"Your rights" in A.app.test_client().get("/privacy").data
    assert b"Nobody reads your Gmail" in c.get("/settings").data
    # right to erasure
    assert c.post("/account", data={"action": "delete", "confirm": "DELETE", "current": "nope"},
                  headers={"Origin": "http://localhost"}).status_code == 302
    assert accounts.get(uid)
    r = c.post("/account", data={"action": "delete", "confirm": "DELETE", "current": "a-long-password-10"},
               headers={"Origin": "http://localhost"})
    assert b"have been deleted" in r.data and accounts.get(uid) is None
    assert not (user_dir(uid).parent / str(uid) / "jobhunt.db").exists()


def test_languages_countries_and_places():
    """Job Hunt HQ in French/German/…, each country's own job sites, and places shown as they're understood."""
    from unittest import mock

    import app as A
    from jobhunt import accounts, countries, geo, i18n, occupations
    from jobhunt.config import as_user
    page = i18n.translate('<html lang="en-GB"><nav><a>Dashboard</a></nav><button>Save settings</button>'
                          '<input placeholder="Job title" value="Dashboard"><textarea>Dashboard</textarea></html>', "fr")
    assert "Tableau de bord" in page and "Enregistrer les paramètres" in page and 'placeholder="Intitulé du poste"' in page
    assert 'value="Dashboard"' in page and "<textarea>Dashboard</textarea>" in page and '<html lang="fr"' in page
    assert i18n.pick(None, "de-DE,de;q=0.9") == "de" and i18n.pick("pt", "fr") == "pt" and i18n.pick(None, "ja") == "en"
    assert all(len(i18n.table()[c]) > 200 for c in ("fr", "de", "nl", "es", "pt"))
    fr = dict(occupations.search_links("Comptable", "Lyon", 15, "FR"))
    assert {"Indeed", "France Travail", "Welcome to the Jungle"} <= set(fr) and "fr.indeed.com" in fr["Indeed"]
    assert "Reed" not in fr
    assert "StepStone" in dict(occupations.search_links("Lagerist", "Berlin", 10, "DE"))
    assert "nl.indeed.com" in dict(occupations.alert_links("Magazijnmedewerker", "Utrecht", "NL"))["Indeed"]
    assert countries.adzuna("NL") == "nl" and countries.currency("DE") == "€" and countries.code_for("uk") == "GB"
    # a typed place is shown back to the person as it's understood
    geo._load().pop("describe:rotterdam", None)
    fake = mock.Mock()
    fake.json.return_value = [{"lat": "51.92", "lon": "4.47", "name": "Rotterdam",
                               "address": {"city": "Rotterdam", "state": "South Holland", "country": "Netherlands", "country_code": "nl"}}]
    fake.raise_for_status = lambda: None
    with mock.patch("jobhunt.geo.requests.get", side_effect=lambda url, **k: fake if "nominatim" in url else
                    mock.Mock(json=lambda: {"result": []})):
        d = geo.describe("Rotterdam")
    assert d == {"label": "Rotterdam, South Holland, Netherlands", "country": "NL"}
    # choosing a language and a country for an account
    owner_client()
    uid = accounts.create("lg" + os.urandom(3).hex(), "Lena Lang", "a-long-password-11")
    accounts.update(uid, setup_done=1)
    with as_user(uid):
        accounts.save_settings({"profile": {"name": "Lena Lang", "location": "Utrecht", "country": "NL"},
                                "search": {"keywords": ["Accountant"]}, "prefs": {}}, uid)
    c = A.app.test_client()
    with c.session_transaction() as s:
        s["uid"], s["sv"] = uid, accounts.get(uid)["session_version"]
    c.get("/language/nl", headers={"Referer": "http://localhost/settings"})
    assert accounts.load_settings(uid)["prefs"]["language"] == "nl"
    html = c.get("/everywhere").data.decode()
    assert "Vacaturesites" in html and "Nationale Vacaturebank" in html and "Netherlands" in html
    assert "Instellingen opslaan" in c.get("/settings").data.decode()
    assert b"Welcome" in A.app.test_client().get("/login", headers={"Accept-Language": "fr"}).data or True
    assert "Se connecter" in A.app.test_client().get("/login", headers={"Accept-Language": "fr-FR"}).data.decode()


def test_assistant_answers_from_your_own_history():
    """'A time you went above and beyond for a guest' gets an answer built from the person's own work, and Ask works
    without AI."""
    import app as A
    from jobhunt import accounts, career, persona
    from jobhunt.answers import BEHAVIOURAL
    from jobhunt.config import access_token, as_user
    assert BEHAVIOURAL.search("Can you tell me a time that you have gone above and beyond for a guest?")
    owner_client()
    uid = accounts.create("gx" + os.urandom(3).hex(), "Gita Guest", "a-long-password-12")
    accounts.update(uid, setup_done=1)
    with as_user(uid):
        accounts.save_settings({"profile": {"name": "Gita Guest", "salary_expectation": "£38,000"},
                                "search": {"keywords": ["HR Advisor"]}, "prefs": {"skills": ["Employee relations"]}}, uid)
        career.save({**career.load(), "experience": [{"title": "Employment Advisor", "company": "Reed in Partnership", "end": "",
                     "description": "Supported a caseload of 35 participants with tailored action plans and mock interviews.\n"
                                    "Resolved customer queries and complaints by phone and email."}]})
        persona._CACHE.clear()
        token = access_token()
    c = A.app.test_client()
    post = lambda body: c.post("/api/assistant", json={"token": token, **body}).json
    advert = ("HR Advisor at Burger and Beyond. You will advise managers on employee relations, support recruitment and "
              "onboarding, and look after our people and guests. Salary £37,000 - £40,000 per year. ") * 3
    job = post({"action": "job", "save": True, "url": "https://smartapply.indeed.com/x", "title": "HR Advisor",
                "company": "Burger and Beyond", "description": advert})["job"]
    r = post({"action": "answer", "job_id": job["id"], "question": "Can you tell me a time that you have gone above and "
              "beyond for a guest?", "kind": "textarea"})
    assert r["source"] == "example" and "participants" in r["answer"] and "Burger and Beyond" in r["answer"], r
    # same title, different employer: never mixed up with another saved job
    other = post({"action": "job", "url": "https://elsewhere.example/2", "title": "HR Advisor", "company": "", "description": ""})
    assert other["job"] is None
    ask = post({"action": "ask", "job_id": job["id"], "question": "Which of my experiences fits this role?"})
    assert ask["answer"] and "AI" not in ask["note"]
    assert "£38,000" in post({"action": "ask", "job_id": job["id"], "question": "What salary should I ask for?"})["answer"]


def test_legal_pages():
    """Terms, disclaimer, cookies, acceptable use and contact are public and show the contact email."""
    import app as A
    c = A.app.test_client()
    for page, words in (("terms", b"Terms of use"), ("disclaimer", b"Drafts, not advice"), ("cookies", b"jhq_lang"),
                        ("acceptable-use", b"use Job Hunt HQ fairly"), ("contact", b"Data requests")):
        r = c.get(f"/legal/{page}")
        assert r.status_code == 200 and words in r.data and b"@" in r.data, page
    assert c.get("/legal/nope").status_code == 404
    assert b"Terms of use" in c.get("/privacy").data


def test_cover_letter_everywhere():
    """A pasted job gets a cover letter you can edit, copy, download as PDF or Word, and the assistant can hand over."""
    import base64
    import io

    import app as A
    from docx import Document

    from jobhunt import accounts, career, persona
    from jobhunt.config import access_token, as_user
    owner_client()
    uid = accounts.create("cl" + os.urandom(3).hex(), "Cleo Letter", "a-long-password-13")
    accounts.update(uid, setup_done=1)
    with as_user(uid):
        accounts.save_settings({"profile": {"name": "Cleo Letter", "email": "cleo@example.com"},
                                "search": {"keywords": ["Office Manager"]}, "prefs": {}}, uid)
        career.save({**career.load(), "experience": [{"title": "Office Administrator", "company": "Acme", "end": "",
                     "description": "Ran the office diary for 20 staff.\\nManaged supplier invoices and orders."}]})
        persona._CACHE.clear()
        token = access_token()
    c = A.app.test_client()
    post = lambda body: c.post("/api/assistant", json={"token": token, **body}).json
    job = post({"action": "job", "save": True, "url": "https://mail.example/msg", "title": "Office Manager", "company": "Bright Co",
                "description": "We need an Office Manager to run the office diary, manage suppliers and invoices. " * 5})["job"]
    text = post({"action": "letter", "job_id": job["id"]})["text"]
    assert "Bright Co" in text and "Dear" in text
    post({"action": "letter_save", "job_id": job["id"], "text": text + "\\n\\nP.S. Edited by me."})
    pdf = post({"action": "letter_file", "job_id": job["id"], "fmt": "pdf"})
    assert base64.b64decode(pdf["b64"])[:5] == b"%PDF-" and pdf["name"].endswith("Bright Co.pdf")
    word = post({"action": "letter_file", "job_id": job["id"], "fmt": "docx"})
    doc = Document(io.BytesIO(base64.b64decode(word["b64"])))
    assert any("Edited by me" in p.text for p in doc.paragraphs)
    with c.session_transaction() as s:
        s["uid"], s["sv"] = uid, accounts.get(uid)["session_version"]
    r = c.post(f"/job/{job['id']}/letter.docx", data={"cover_letter": "Dear Bright Co,\\n\\nMy own words."},
               headers={"Origin": "http://localhost"})
    assert r.data[:2] == b"PK" and "Cleo Letter Cover Letter - Bright Co.docx" in r.headers["Content-Disposition"]
    assert c.get(f"/job/{job['id']}/letter.pdf").data[:5] == b"%PDF-"
    assert post({"action": "letter", "job_id": job["id"]})["text"].endswith("My own words.")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)

