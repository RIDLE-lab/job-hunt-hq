"""Where places are, for "how far is this job from me?". Uses postcodes.io (free, UK, no key needed) and keeps
every answer in data/geo_cache.json so each place is only looked up once."""
from __future__ import annotations

import json
import math
import re
import threading

import requests

from .config import DATA_DIR

CACHE_FILE = DATA_DIR / "geo_cache.json"
_LOCK = threading.Lock()
_CACHE: dict | None = None
POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
OUTCODE = re.compile(r"^\s*([A-Z]{1,2}\d[A-Z\d]?)\s*$", re.I)


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _CACHE = {}
    return _CACHE


def _save():
    try:
        DATA_DIR.mkdir(exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_CACHE), encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except Exception:
        pass


def _lookup(place: str):
    base = "https://api.postcodes.io"
    m = POSTCODE.search(place)
    try:
        if m:
            r = requests.get(f"{base}/postcodes/{m.group(1)}{m.group(2)}", timeout=8).json()
            res = r.get("result") or {}
            if res.get("latitude"):
                return [res["latitude"], res["longitude"]]
        m = OUTCODE.match(place)
        if m:
            r = requests.get(f"{base}/outcodes/{m.group(1)}", timeout=8).json()
            res = r.get("result") or {}
            if res.get("latitude"):
                return [res["latitude"], res["longitude"]]
        r = requests.get(f"{base}/places", params={"q": place, "limit": 5}, timeout=8).json()
        results = r.get("result") or []
        # prefer towns/cities over farms and streets with the same name
        rank = {"City": 0, "Town": 1, "Suburban Area": 2, "Village": 3, "Hamlet": 4, "Other Settlement": 5}
        results.sort(key=lambda x: rank.get(x.get("local_type"), 9))
        for res in results:
            if res.get("latitude"):
                return [res["latitude"], res["longitude"]]
    except Exception:
        return None          # offline or the service is busy: try again next time
    return []                # looked up, nothing found


def locate(place: str):
    """(lat, lon) for a UK town, city or postcode, or None if it can't be found."""
    key = re.sub(r"\s+", " ", (place or "").strip().lower())
    if not key or len(key) < 2:
        return None
    with _LOCK:
        cache = _load()
        if key in cache:
            v = cache[key]
            return tuple(v) if v else None
    found = _lookup(place)
    if found is None:
        return None
    with _LOCK:
        _load()[key] = found
        _save()
    return tuple(found) if found else None


def miles(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


VAGUE = re.compile(r"^(united kingdom|uk|england|scotland|wales|northern ireland|great britain|gb|britain|"
                   r"multiple locations?|various|nationwide|hybrid|flexible|on-?site|office|anywhere|remote)$", re.I)


def job_place(location: str):
    """The most specific findable place in a job's location text: 'Canary Wharf, London E14' → E14 / Canary Wharf."""
    loc = re.sub(r"\((hybrid|remote|on-?site)\)", "", location or "", flags=re.I)
    m = POSTCODE.search(loc)
    if m:
        hit = locate(m.group(0))
        if hit:
            return hit
    for part in [p.strip(" .") for p in re.split(r"[,/|;]| - ", loc)]:
        if not part or VAGUE.match(part):
            continue
        hit = locate(part)
        if hit:
            return hit
    return None
