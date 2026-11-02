"""Where places are, for "how far is this job from me?". Uses postcodes.io (free, UK, no key needed) and keeps
every answer in data/geo_cache.json so each place is only looked up once."""
from __future__ import annotations

import json
import math
import re
import threading
import time

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
        if not _abroad(place):
            r = requests.get(f"{base}/places", params={"q": place, "limit": 5}, timeout=8).json()
            results = r.get("result") or []
            # prefer towns/cities over farms and streets with the same name
            rank = {"City": 0, "Town": 1, "Suburban Area": 2, "Village": 3, "Hamlet": 4, "Other Settlement": 5}
            results.sort(key=lambda x: rank.get(x.get("local_type"), 9))
            for res in results:
                if res.get("latitude"):
                    return [res["latitude"], res["longitude"]]
        hit = _osm(place)                    # anywhere else in the world
        if hit is None:
            return None
        if hit:
            return [hit["lat"], hit["lon"]]
    except Exception:
        return None          # offline or the service is busy: try again next time
    return []                # looked up, nothing found


ABROAD = re.compile(r",\s*(france|germany|deutschland|netherlands|nederland|belgium|belgique|belgi[eë]|spain|españa|espana|"
                    r"portugal|italy|italia|poland|polska|austria|österreich|switzerland|schweiz|suisse|ireland|"
                    r"united states|usa|canada|australia|uae|united arab emirates)\s*$", re.I)


def _abroad(place: str) -> bool:
    return bool(ABROAD.search(place or ""))


_OSM_LOCK = threading.Lock()
_OSM_LAST = [0.0]


def _osm(place: str):
    """OpenStreetMap's free place search (at most one request a second, as its rules ask)."""
    with _OSM_LOCK:
        wait = 1.1 - (time.time() - _OSM_LAST[0])
        if wait > 0:
            time.sleep(wait)
        _OSM_LAST[0] = time.time()
        try:
            r = requests.get("https://nominatim.openstreetmap.org/search",
                             params={"q": place, "format": "jsonv2", "addressdetails": 1, "limit": 1,
                                     "accept-language": "en"},
                             headers={"User-Agent": "JobHuntHQ/1.0 (personal job-search assistant)"}, timeout=10)
            r.raise_for_status()
            res = r.json()
        except Exception:
            return None
    if not res:
        return {}
    a = res[0].get("address") or {}
    town = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("suburb") or \
        res[0].get("name") or ""
    region = a.get("state") or a.get("county") or a.get("region") or ""
    return {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "town": town, "region": region,
            "country": (a.get("country_code") or "").upper(), "country_name": a.get("country") or ""}


def describe(place: str) -> dict:
    """What a typed place is: {"label": "Leeds, West Yorkshire, England, United Kingdom", "country": "GB"} – shown
    to the person as they type, so they can see it's understood."""
    place = (place or "").strip()
    if len(place) < 2:
        return {}
    key = "describe:" + re.sub(r"\s+", " ", place.lower())
    with _LOCK:
        cache = _load()
        if key in cache:
            return cache[key] or {}
    out = {}
    try:
        m = POSTCODE.search(place)
        if m and not _abroad(place):
            res = (requests.get(f"https://api.postcodes.io/postcodes/{m.group(1)}{m.group(2)}", timeout=8).json()
                   .get("result") or {})
            if res:
                bits = [res.get("postcode"), res.get("admin_district"), res.get("region") or res.get("country"),
                        res.get("country"), "United Kingdom"]
                out = {"label": ", ".join(dict.fromkeys(b for b in bits if b)), "country": "GB"}
        if not out and not _abroad(place):
            res = (requests.get("https://api.postcodes.io/places", params={"q": place, "limit": 5}, timeout=8).json()
                   .get("result") or [])
            rank = {"City": 0, "Town": 1, "Suburban Area": 2, "Village": 3, "Hamlet": 4, "Other Settlement": 5}
            res.sort(key=lambda x: rank.get(x.get("local_type"), 9))
            if res and res[0].get("name_1", "").lower().startswith(place.split(",")[0].strip().lower()[:4]):
                r0 = res[0]
                bits = [r0.get("name_1"), r0.get("county_unitary") or r0.get("district_borough"), r0.get("region"),
                        r0.get("country"), "United Kingdom"]
                out = {"label": ", ".join(dict.fromkeys(b for b in bits if b)), "country": "GB"}
        if not out:
            hit = _osm(place)
            if hit:
                bits = [hit["town"], hit["region"], hit["country_name"]]
                out = {"label": ", ".join(dict.fromkeys(b for b in bits if b)), "country": hit["country"]}
    except Exception:
        return {}
    with _LOCK:
        _load()[key] = out
        _save()
    return out


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
