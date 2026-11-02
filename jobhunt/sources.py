"""Job sources: Reed and Adzuna (free official APIs) plus jobs added by link."""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime

import requests

TIMEOUT = 20
UA = {"User-Agent": "JobHuntHQ/1.0 (personal job search tool)"}


def clean_text(text: str | None) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def salary_text(lo, hi) -> str:
    def fmt(v):
        return f"£{int(round(v)):,}"
    if lo and hi and int(lo) != int(hi):
        return f"{fmt(lo)} – {fmt(hi)}"
    if lo or hi:
        return fmt(lo or hi)
    return ""


def is_remote(*texts) -> bool:
    blob = " ".join(t or "" for t in texts).lower()
    return any(w in blob for w in ("remote", "work from home", "home-based", "home based", "fully remote"))


# ---------------------------------------------------------------- Reed
REED_URL = "https://www.reed.co.uk/api/1.0/search"


def _reed_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None


def parse_reed(payload: dict) -> list[dict]:
    jobs = []
    for r in payload.get("results", []):
        lo, hi = r.get("minimumSalary"), r.get("maximumSalary")
        desc = clean_text(r.get("jobDescription"))
        jobs.append({
            "source": "Reed",
            "external_id": str(r.get("jobId")),
            "title": clean_text(r.get("jobTitle")),
            "company": clean_text(r.get("employerName")),
            "location": clean_text(r.get("locationName")),
            "salary_min": lo, "salary_max": hi,
            "salary_text": salary_text(lo, hi),
            "url": r.get("jobUrl"),
            "description": desc,
            "posted": _reed_date(r.get("date")),
            "closes": _reed_date(r.get("expirationDate")),
            "remote": int(is_remote(r.get("jobTitle"), desc, r.get("locationName"))),
        })
    return jobs


def search_reed(api_key: str, keywords: str, location: str, distance: int, min_salary: int | None) -> list[dict]:
    params = {"keywords": keywords, "locationName": location, "distanceFromLocation": distance,
              "resultsToTake": 100}
    if min_salary:
        params["minimumSalary"] = min_salary
    resp = requests.get(REED_URL, params=params, auth=(api_key, ""), headers=UA, timeout=TIMEOUT)
    resp.raise_for_status()
    return parse_reed(resp.json())


# ---------------------------------------------------------------- Adzuna
ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


def parse_adzuna(payload: dict) -> list[dict]:
    jobs = []
    for r in payload.get("results", []):
        lo, hi = r.get("salary_min"), r.get("salary_max")
        desc = clean_text(r.get("description"))
        loc = (r.get("location") or {}).get("display_name", "")
        created = (r.get("created") or "")[:10] or None
        jobs.append({
            "source": "Adzuna",
            "external_id": str(r.get("id")),
            "title": clean_text(r.get("title")),
            "company": clean_text((r.get("company") or {}).get("display_name")),
            "location": loc,
            "salary_min": lo, "salary_max": hi,
            "salary_text": salary_text(lo, hi),
            "url": r.get("redirect_url"),
            "description": desc,
            "posted": created,
            "closes": None,
            "remote": int(is_remote(r.get("title"), desc, loc)),
        })
    return jobs


def search_adzuna(app_id: str, app_key: str, keywords: str, location: str, distance_miles: int,
                  min_salary: int | None, max_age_days: int, country: str = "gb") -> list[dict]:
    params = {"app_id": app_id, "app_key": app_key, "what": keywords, "where": location,
              "distance": int(distance_miles * 1.609), "max_days_old": max_age_days,
              "results_per_page": 50, "content-type": "application/json"}
    if min_salary:
        params["salary_min"] = min_salary
    resp = requests.get(ADZUNA_URL.format(country=country or "gb"), params=params, headers=UA, timeout=TIMEOUT)
    resp.raise_for_status()
    return parse_adzuna(resp.json())


# ---------------------------------------------------------------- CV-Library (needs a partner key from CV-Library)
CVLIB_URL = "https://www.cv-library.co.uk/search-jobs-json"
CVLIB_MILES = [1, 2, 5, 7, 10, 15, 20, 25, 35, 50, 75, 100]


def _money(text: str) -> tuple[float | None, float | None]:
    nums = [float(n.replace(",", "")) for n in re.findall(r"£?\s?(\d[\d,]*(?:\.\d+)?)", text or "")]
    nums = [n for n in nums if n >= 1000]          # yearly figures only; hourly/daily pay stays as text
    return (min(nums), max(nums)) if nums else (None, None)


def parse_cvlibrary(payload: dict) -> list[dict]:
    jobs = []
    for r in payload.get("jobs", []):
        sal = r.get("salary")
        if isinstance(sal, dict):
            lo, hi = sal.get("min"), sal.get("max")
            text = salary_text(lo, hi) if sal.get("period") in (None, "annum", "annually", "yearly") else \
                f"£{lo or ''}–£{hi or ''} per {sal.get('period')}".replace("–£ ", "")
        else:
            text = clean_text(sal)
            lo, hi = _money(text)
        url = r.get("url") or ""
        desc = clean_text(re.sub(r"</?em>", "", r.get("description") or ""))
        title = clean_text(re.sub(r"</?em>", "", r.get("title") or ""))
        jobs.append({
            "source": "CV-Library",
            "external_id": str(r.get("id")),
            "title": title,
            "company": clean_text((r.get("agency") or {}).get("title")),
            "location": clean_text(r.get("location")),
            "salary_min": lo, "salary_max": hi, "salary_text": text,
            "url": url if url.startswith("http") else "https://www.cv-library.co.uk" + url,
            "description": desc,
            "posted": (r.get("posted") or "")[:10] or None,
            "closes": (r.get("expiry_date") or "")[:10] or None,
            "remote": int(is_remote(title, desc, r.get("location"))),
        })
    return jobs


def search_cvlibrary(key: str, keywords: str, location: str, distance: int, min_salary: int | None,
                     max_age_days: int = 14) -> list[dict]:
    miles = min(CVLIB_MILES, key=lambda m: abs(m - int(distance or 15)))
    posted = min([1, 3, 7, 14, 28], key=lambda d: abs(d - int(max_age_days or 14)))
    params = {"key": key, "q": keywords, "geo": location, "distance": miles, "posted": posted,
              "limit": 100, "description_limit": 4000, "nohl": 1, "salary_detailed": 1, "id_as_string": 1}
    if min_salary:
        params.update(salarymin=min_salary, salarytype="annum")
    resp = requests.get(CVLIB_URL, params=params, headers=UA, timeout=TIMEOUT)
    if resp.status_code == 404:                     # no (more) results
        return []
    resp.raise_for_status()
    return parse_cvlibrary(resp.json())


# ---------------------------------------------------------------- The Talent World (HR-only job board)
TALENTWORLD = "https://www.thetalentworld.co.uk"


def talentworld_ids(sitemap_xml: str) -> list[tuple[int, str]]:
    """(job id, url) pairs from a sitemap, newest (highest id) first."""
    found = re.findall(r"<loc>\s*(https://www\.thetalentworld\.co\.uk/jobs/(\d+)-[^<\s]+)\s*</loc>", sitemap_xml)
    return sorted({(int(i), u) for u, i in found}, reverse=True)


def search_talentworld(known_ids: set[str], max_new: int = 40, log=print) -> list[dict]:
    """Newest jobs from thetalentworld.co.uk via its public sitemap (the site's robots.txt allows this;
    it asks tools not to use its RSS feed, so we don't). Waits 1 second between pages, as the site asks."""
    import time
    from .fetch_page import HEADERS, parse_job_html

    index = requests.get(f"{TALENTWORLD}/sitemap.xml", headers=HEADERS, timeout=TIMEOUT).text
    maps = re.findall(r"<loc>\s*(https://www\.thetalentworld\.co\.uk/sitemap-jobs-\d+\.xml)\s*</loc>", index)
    ids: list[tuple[int, str]] = []
    for m in maps or [f"{TALENTWORLD}/sitemap-jobs-1.xml"]:
        time.sleep(1)
        ids += talentworld_ids(requests.get(m, headers=HEADERS, timeout=TIMEOUT).text)
    ids.sort(reverse=True)
    new = [(i, u) for i, u in ids if str(i) not in known_ids][:max_new]
    jobs = []
    for job_id, url in new:
        time.sleep(1)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                continue
            j = parse_job_html(resp.text, url)
        except Exception as e:
            log(f"The Talent World: couldn't read {url}: {e}")
            continue
        if not j["title"]:
            continue
        m = re.search(r'href="(https?://[^"]+)"[^>]*>\s*Apply directly', resp.text)
        desc = j["description"]
        if m:
            desc = f"{desc}\n\nApply directly: {m.group(1)}"
        jobs.append({
            "source": "The Talent World", "external_id": str(job_id), "title": j["title"],
            "company": j["company"], "location": j["location"], "salary_min": None, "salary_max": None,
            "salary_text": j.get("salary", ""), "url": url, "description": desc,
            "posted": j.get("posted") or None, "closes": j["closes"] or None,
            "remote": int(is_remote(j["title"], desc, j["location"])),
        })
    return jobs


def parse_posted(text, today=None) -> str | None:
    """A posting date from '2026-10-17', 'Posted 3 days ago', 'Just posted', '30+ days ago', '2 weeks ago'…"""
    from datetime import date, timedelta
    today = today or date.today()
    t = str(text or "").strip().lower()
    if not t:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m:
        return m.group(1)
    if re.search(r"just (now|posted)|today|minute|hour|\bnew\b", t):
        return today.isoformat()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    short = re.search(r"(\d+)\s*(mo|m|h|d|w)\b\s*ago", t)          # LinkedIn's "2h ago", "3d ago", "1w ago"
    if short:
        unit = short.group(2)
        if unit in ("m", "h"):
            return today.isoformat()
        return (today - timedelta(days=int(short.group(1)) * {"d": 1, "w": 7, "mo": 30}[unit])).isoformat()
    m = re.search(r"(\d+)\+?\s*(day|week|month)s?\s*ago", t) or re.search(r"(an?|one)\s+(day|week|month)\s*ago", t)
    if m:
        n = 1 if m.group(1) in ("a", "an", "one") else int(m.group(1))
        days = {"day": 1, "week": 7, "month": 30}[m.group(2)] * n
        return (today - timedelta(days=days)).isoformat()
    return None


# ---------------------------------------------------------------- Added by hand
def manual_job(title: str, company: str, url: str, location: str = "", salary: str = "",
               description: str = "", closes: str | None = None) -> dict:
    """A job pasted in by the user (LinkedIn, NHS Jobs, CharityJob…). Nothing is fetched."""
    url = url or ""
    m = re.search(r"/jobs/view/(\d+)", url) or re.search(r"[?&](?:vjk|jk)=([0-9a-f]{16})", url)
    source = ("LinkedIn" if "linkedin.com" in url else "Indeed" if "indeed." in url else
              "Reed" if "reed.co.uk" in url else "Added by you")
    ext = m.group(1) if m else hashlib.sha1(f"{title}|{company}|{url}".encode()).hexdigest()[:16]
    return {
        "source": source, "external_id": ext, "title": title.strip(), "company": company.strip(),
        "location": location.strip(), "salary_min": None, "salary_max": None, "salary_text": salary.strip(),
        "url": url.strip(), "description": description.strip(),
        "posted": datetime.now().date().isoformat(), "closes": closes or None,
        "remote": int(is_remote(title, description, location)),
    }
