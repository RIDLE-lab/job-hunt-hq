"""Back-up for the browser button: read one job page from its link.

Works for most company career sites and LinkedIn's public job pages. Indeed usually blocks
this, so on Indeed use the "Send to Job Hunt HQ" button instead. Only the single page you
asked for is fetched – nothing is crawled.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from urllib.parse import urlparse

import requests

from .sources import clean_text

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/128.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}


def rich_text(text: str | None) -> str:
    """HTML (sometimes encoded twice, e.g. '&amp;amp;') -> readable text that keeps its paragraphs."""
    text = text or ""
    for _ in range(2):
        text = htmllib.unescape(text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|ul|ol|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n• ", text)
    text = re.sub(r"<[^>]+>", " ", text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n+•", "\n•", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


ATS_NAMES = r"rippling|recruit(ing|ee)\b|greenhouse|\blever\b|workable|teamtailor|ashby|smartrecruiters|jobvite|icims|" \
            r"applytojob|jazzhr|bamboohr|workday|pinpoint|breezy"


def company_from_url(url: str) -> str:
    """Best guess at the employer from the link, e.g. jobs.smartrecruiters.com/Wabtec/... -> Wabtec."""
    u = urlparse(url)
    host, parts = u.hostname or "", [x for x in u.path.split("/") if x]
    ats = ("smartrecruiters.com", "greenhouse.io", "lever.co", "workable.com", "teamtailor.com", "pinpointhq.com",
           "ashbyhq.com", "recruitee.com", "breezy.hr", "bamboohr.com", "ats.rippling.com", "jobvite.com", "applytojob.com")
    if any(host.endswith(a) for a in ats) and parts:
        return parts[0].replace("-", " ").replace("_", " ").strip().title() if parts[0].islower() else parts[0]
    if "myworkdaysite.com" in host and len(parts) > 2:
        return parts[2]
    if host.endswith("myworkdayjobs.com"):
        return host.split(".")[0]
    bits = [b for b in host.split(".") if b not in ("www", "jobs", "careers", "apply", "co", "uk", "com", "org", "net")]
    return bits[0].replace("-", " ").title() if bits else ""


def _meta(html: str, prop: str) -> str:
    m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)', html, re.I) \
        or re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']', html, re.I)
    return clean_text(m.group(1)) if m else ""


def parse_job_html(html: str, url: str) -> dict:
    job = {"url": url, "title": "", "company": "", "location": "", "salary": "", "description": "", "closes": "",
           "posted": ""}
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for d in items:
            if not isinstance(d, dict) or d.get("@type") != "JobPosting":
                continue
            job["title"] = job["title"] or clean_text(d.get("title"))
            org = d.get("hiringOrganization") or {}
            job["company"] = job["company"] or clean_text(org.get("name") if isinstance(org, dict) else org)
            locs = d.get("jobLocation") or []
            loc = (locs[0] if isinstance(locs, list) and locs else locs) or {}
            addr = loc.get("address", {}) if isinstance(loc, dict) else {}
            if isinstance(addr, dict) and not job["location"]:
                job["location"] = ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressRegion")) if x)
            job["description"] = job["description"] or rich_text(d.get("description"))
            job["closes"] = (d.get("validThrough") or "")[:10]
            job["posted"] = (d.get("datePosted") or "")[:10]
            sal = d.get("baseSalary") or {}
            val = sal.get("value", {}) if isinstance(sal, dict) else {}
            if isinstance(val, dict) and (val.get("minValue") or val.get("value")):
                lo, hi = val.get("minValue") or val.get("value"), val.get("maxValue")
                unit = str(val.get("unitText") or "").lower()
                job["salary"] = f"£{float(lo):,.0f}" + (f" – £{float(hi):,.0f}" if hi and hi != lo else "") + \
                                (f" per {unit}" if unit and unit != "year" else "")
    # schema.org microdata (SmartRecruiters pages and others)
    if not job["title"]:
        m = re.search(r'itemprop="title"[^>]*>(.*?)</', html, re.S)
        job["title"] = clean_text(m.group(1)) if m else ""
    if not job["company"]:
        m = re.search(r'itemprop="hiringOrganization".{0,400}?itemprop="name"[^>]*content="([^"]+)"', html, re.S)
        job["company"] = clean_text(m.group(1)) if m else ""
    if not job["location"]:
        m = re.search(r'formattedaddress="([^"]+)"', html, re.I) or \
            re.search(r'itemprop="addressLocality"[^>]*(?:content="([^"]+)"|>([^<]+)<)', html)
        job["location"] = clean_text(next((g for g in m.groups() if g), "")) if m else ""
    if not job["description"]:
        m = re.search(r'itemprop="description"[^>]*>(.*?)</section>', html, re.S)
        job["description"] = rich_text(m.group(1)) if m else ""
    # LinkedIn public pages
    if not job["title"]:
        m = re.search(r'class="[^"]*top-card-layout__title[^"]*"[^>]*>(.*?)<', html, re.S)
        job["title"] = clean_text(m.group(1)) if m else ""
    if not job["company"]:
        m = re.search(r'class="[^"]*topcard__org-name-link[^"]*"[^>]*>(.*?)<', html, re.S)
        job["company"] = clean_text(m.group(1)) if m else ""
    if not job["location"]:
        m = re.search(r'class="[^"]*topcard__flavor--bullet[^"]*"[^>]*>(.*?)<', html, re.S)
        job["location"] = clean_text(m.group(1)) if m else ""
    if not job["description"]:
        m = re.search(r'class="[^"]*(?:show-more-less-html__markup|description__text)[^"]*"[^>]*>(.*?)</(?:div|section)>',
                      html, re.S)
        job["description"] = clean_text(m.group(1)) if m else ""
    # Fallbacks: the page's own heading and text (most careers pages put the advert on the first page)
    if not job["title"]:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
        job["title"] = clean_text(m.group(1)) if m else ""
    if not job["description"]:
        m = re.search(r"<(main|article)[^>]*>(.*?)</\1>", html, re.S | re.I)
        body = m.group(2) if m else (re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I) or [None, html])[1]
        body = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
        text = rich_text(body)
        if len(text) > 400:
            job["description"] = text[:20000]
    job["title"] = job["title"] or _meta(html, "og:title")
    if not job["title"]:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        job["title"] = clean_text(m.group(1)).split(" | ")[0].split(" - ")[0] if m else ""
    job["description"] = job["description"] or rich_text(_meta(html, "og:description") or _meta(html, "description"))
    job["title"] = clean_text(htmllib.unescape(job["title"]))
    # "HR Advisor - Acme - LinkedIn" style titles
    if job["title"] and not job["company"] and " at " in job["title"]:
        job["title"], job["company"] = [s.strip() for s in job["title"].split(" at ", 1)]
    job["company"] = clean_text(htmllib.unescape(job["company"])) or _meta(html, "og:site_name") or company_from_url(url)
    # "Rippling Recruiting", "Greenhouse"… is the hiring system, not the employer: use "Title | Employer" or the link.
    if re.search(ATS_NAMES, job["company"] or "", re.I):
        m = re.match(r"^(.+?)\s+[|–-]\s+([^|–-]{2,60})$", job["title"] or "")
        if m and not re.search(ATS_NAMES, m.group(2), re.I):
            job["title"], job["company"] = m.group(1).strip(), m.group(2).strip()
        else:
            job["company"] = company_from_url(url) or job["company"]
    m = re.match(r"^(.+?)\s+\|\s+(.{2,60})$", job["title"] or "")
    if m and job["company"] and m.group(2).strip().lower() == job["company"].lower():
        job["title"] = m.group(1).strip()
    # LinkedIn's public job pages carry the employer's application link behind "Apply"
    m = re.search(r'externalApply/\d+\?url=([^"&\s]+)', html) or re.search(r'"companyApplyUrl"\s*:\s*"([^"]+)"', html) or \
        re.search(r'safety/go/?\?url=([^"&\s]+)', html)
    if m:
        from urllib.parse import unquote
        link = unquote(htmllib.unescape(m.group(1))).replace("\\u002F", "/")
        if link.startswith("http") and "linkedin.com" not in link:
            job["apply_url"] = link
    return job


def canonical_url(url: str) -> str:
    url = url.strip()
    m = re.search(r"linkedin\.com/.*?(?:currentJobId=|jobs/view/(?:[^/]*-)?)(\d{6,})", url)
    if m:
        return f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
    m = re.search(r"(https?://[a-z.]*indeed\.[a-z.]+)/.*?[?&](?:vjk|jk)=([0-9a-f]{16})", url)
    if m:
        return f"{m.group(1)}/viewjob?jk={m.group(2)}"
    return url


def _sections_text(sections: list[tuple[str, str]]) -> str:
    return "\n\n".join((f"{t}\n" if t else "") + rich_text(x) for t, x in sections if x and rich_text(x))


def ats_job(url: str) -> dict | None:
    """Recruitment systems with a public job feed: read the advert from the feed instead of the page.
    SmartRecruiters, Greenhouse and Lever all publish these for job boards to use."""
    m = re.search(r"smartrecruiters\.com/(?:oneclick-ui/company/)?([^/?#]+)/(?:publication/)?(\d{6,})", url)
    if m:
        co, pid = m.groups()
        d = requests.get(f"https://api.smartrecruiters.com/v1/companies/{co}/postings/{pid}", headers=HEADERS, timeout=20)
        d.raise_for_status()
        return parse_smartrecruiters(d.json(), url)
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([^/?#&]+)/jobs/(\d+)", url) or \
        re.search(r"greenhouse\.io/embed/job_app\?for=([^&]+)&token=(\d+)", url)
    if m:
        co, pid = m.groups()
        d = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{co}/jobs/{pid}?pay_transparency=true",
                         headers=HEADERS, timeout=20)
        d.raise_for_status()
        j = d.json()
        return {"url": url, "title": clean_text(j.get("title")), "company": clean_text(j.get("company_name")) or company_from_url(url),
                "location": clean_text((j.get("location") or {}).get("name")), "salary": "",
                "description": rich_text(j.get("content")), "closes": "", "posted": (j.get("updated_at") or "")[:10],
                "apply_url": j.get("absolute_url") or url}
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        org, pid = m.groups()
        d = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true",
                         headers=HEADERS, timeout=20)
        d.raise_for_status()
        j = next((x for x in d.json().get("jobs", []) if x.get("id") == pid), None)
        if j:
            comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
            return {"url": url.split("?")[0], "title": clean_text(j.get("title")), "company": company_from_url(url),
                    "location": clean_text(j.get("location")) + (" (remote)" if j.get("isRemote") else ""),
                    "salary": comp, "description": rich_text(j.get("descriptionHtml")) or j.get("descriptionPlain", ""),
                    "closes": "", "posted": (j.get("publishedAt") or "")[:10],
                    "apply_url": j.get("applyUrl") or url.split("?")[0].rstrip("/") + "/application"}
    m = re.search(r"jobs\.(?:eu\.)?lever\.co/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        co, pid = m.groups()
        api = "api.eu.lever.co" if ".eu." in url else "api.lever.co"
        d = requests.get(f"https://{api}/v0/postings/{co}/{pid}", headers=HEADERS, timeout=20)
        d.raise_for_status()
        j = d.json()
        parts = [("", j.get("description"))] + [(x.get("text", ""), "<ul>" + (x.get("content") or "") + "</ul>")
                                                for x in j.get("lists") or []] + [("", j.get("additional"))]
        return {"url": url, "title": clean_text(j.get("text")), "company": company_from_url(url),
                "location": clean_text((j.get("categories") or {}).get("location")), "salary": "",
                "description": _sections_text(parts), "closes": "", "posted": "",
                "apply_url": j.get("applyUrl") or url}
    return None


def parse_smartrecruiters(d: dict, url: str) -> dict:
    loc = d.get("location") or {}
    place = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("region")) if x)
    if loc.get("remote"):
        place = (place + " (remote)").strip()
    secs = (d.get("jobAd") or {}).get("sections") or {}
    order = ("jobDescription", "qualifications", "additionalInformation", "companyDescription")
    desc = _sections_text([((secs.get(k) or {}).get("title", ""), (secs.get(k) or {}).get("text", "")) for k in order])
    kind = ((d.get("typeOfEmployment") or {}).get("label") or "").strip()
    return {"url": url, "title": clean_text(d.get("name")),
            "company": clean_text((d.get("company") or {}).get("name")) or company_from_url(url),
            "location": clean_text(place), "salary": "", "description": desc + (f"\n\nType: {kind}" if kind else ""),
            "closes": "", "posted": (d.get("releasedDate") or "")[:10], "apply_url": d.get("applyUrl") or ""}


def fetch_job(url: str) -> dict:
    url = canonical_url(url)
    try:
        job = ats_job(url)
        if job and job["title"]:
            return job
    except (requests.RequestException, ValueError):
        pass  # fall back to reading the page itself
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if resp.status_code in (403, 429) or "captcha" in resp.text[:5000].lower():
        raise PermissionError("This site blocked the request. Use the 'Send to Job Hunt HQ' button on the job page instead.")
    resp.raise_for_status()
    job = parse_job_html(resp.text, url)
    if not job["title"] or len(job["description"]) < 200:
        raise ValueError("Couldn't read the advert from that link. Use the 'Send to Job Hunt HQ' button, "
                         "or paste the advert text below.")
    return job
