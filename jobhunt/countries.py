"""Countries Job Hunt HQ works in: each one's main job sites, its Adzuna search (for automatic job finding),
currency, distance unit and usual language.

Search link templates use: {q} title, {l} place (URL-encoded), {qs}/{ls} as-slugs, {mi} miles, {km} kilometres."""
from __future__ import annotations

import re
from urllib.parse import quote_plus

# code: (name, adzuna country or "", currency symbol, uses miles, default language, [(site, url template)])
COUNTRIES: dict[str, tuple] = {
    "GB": ("United Kingdom", "gb", "£", True, "en", [
        ("Indeed", "https://uk.indeed.com/jobs?q={q}&l={l}&radius={mi}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("Reed", "https://www.reed.co.uk/jobs/{qs}-jobs-in-{ls}?proximity={mi}"),
        ("CV-Library", "https://www.cv-library.co.uk/search-jobs?q={q}&geo={l}&distance={mi}"),
        ("Totaljobs", "https://www.totaljobs.com/jobs/{qs}/in-{ls}?radius={mi}"),
        ("Adzuna", "https://www.adzuna.co.uk/jobs/search?q={q}&w={l}&d={mi}"),
        ("Glassdoor", "https://www.glassdoor.co.uk/Job/jobs.htm?sc.keyword={q}&locKeyword={l}"),
        ("Guardian Jobs", "https://jobs.theguardian.com/searchjobs/?Keywords={q}&radialtown={l}&RadialLocation={mi}"),
        ("Find a job (GOV.UK)", "https://findajob.dwp.gov.uk/search?q={q}&w={l}&d={mi}")]),
    "IE": ("Ireland", "", "€", False, "en", [
        ("Indeed", "https://ie.indeed.com/jobs?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("IrishJobs", "https://www.irishjobs.ie/jobs/{qs}/in-{ls}"),
        ("Jobs.ie", "https://www.jobs.ie/jobs/{qs}/in-{ls}"),
        ("Glassdoor", "https://www.glassdoor.ie/Job/jobs.htm?sc.keyword={q}&locKeyword={l}")]),
    "FR": ("France", "fr", "€", False, "fr", [
        ("Indeed", "https://fr.indeed.com/emplois?q={q}&l={l}&radius={km}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("France Travail", "https://candidat.francetravail.fr/offres/recherche?motsCles={q}&lieux={l}"),
        ("Welcome to the Jungle", "https://www.welcometothejungle.com/fr/jobs?query={q}&aroundQuery={l}"),
        ("HelloWork", "https://www.hellowork.com/fr-fr/emploi/recherche.html?k={q}&l={l}"),
        ("APEC (cadres)", "https://www.apec.fr/candidat/recherche-emploi.html/emploi?motsCles={q}&lieux={l}"),
        ("Adzuna", "https://www.adzuna.fr/search?q={q}&w={l}")]),
    "DE": ("Germany", "de", "€", False, "de", [
        ("Indeed", "https://de.indeed.com/jobs?q={q}&l={l}&radius={km}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("StepStone", "https://www.stepstone.de/jobs/{qs}/in-{ls}?radius={km}"),
        ("Bundesagentur für Arbeit", "https://www.arbeitsagentur.de/jobsuche/suche?was={q}&wo={l}&umkreis={km}"),
        ("XING", "https://www.xing.com/jobs/search?keywords={q}&location={l}"),
        ("Adzuna", "https://www.adzuna.de/search?q={q}&w={l}")]),
    "NL": ("Netherlands", "nl", "€", False, "nl", [
        ("Indeed", "https://nl.indeed.com/vacatures?q={q}&l={l}&radius={km}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("Nationale Vacaturebank", "https://www.nationalevacaturebank.nl/vacature/zoeken?query={q}&location={l}&distance={km}"),
        ("werk.nl", "https://www.werk.nl/werkzoekenden/vacatures/?zoekterm={q}&plaats={l}"),
        ("Jobbird", "https://www.jobbird.com/nl/vacature?s={q}&rad_location={l}"),
        ("Adzuna", "https://www.adzuna.nl/search?q={q}&w={l}")]),
    "BE": ("Belgium", "be", "€", False, "nl", [
        ("Indeed", "https://be.indeed.com/jobs?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("StepStone", "https://www.stepstone.be/jobs/{qs}/in-{ls}"),
        ("VDAB (Flanders)", "https://www.vdab.be/vindeenjob/vacatures?trefwoord={q}&locatie={l}"),
        ("Le Forem (Wallonia)", "https://www.leforem.be/recherche-offres-emploi.html?query={q}&location={l}"),
        ("Jobat", "https://www.jobat.be/nl/jobs/zoeken?keyword={q}&location={l}")]),
    "ES": ("Spain", "es", "€", False, "es", [
        ("Indeed", "https://es.indeed.com/ofertas?q={q}&l={l}&radius={km}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("InfoJobs", "https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword={q}&provinceIds=&normalizedJobTitleIds=&cityIds=&teleworkingIds=&categoryIds=&workdayIds=&educationIds=&segmentId=&contractTypeIds=&page=1&sortBy=PUBLICATION_DATE&onlyForeignCountry=false&countryIds=17&sinceDate=ANY&subcategoryIds=&location={l}"),
        ("InfoEmpleo", "https://www.infoempleo.com/trabajo/?q={q}&l={l}"),
        ("Tecnoempleo (IT)", "https://www.tecnoempleo.com/ofertas-trabajo/?te={q}"),
        ("Adzuna", "https://www.adzuna.es/search?q={q}&w={l}")]),
    "PT": ("Portugal", "", "€", False, "pt", [
        ("Indeed", "https://pt.indeed.com/ofertas?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("Net-Empregos", "https://www.net-empregos.com/pesquisa-empregos.asp?chaves={q}&zona=&categoria=0"),
        ("Sapo Emprego", "https://emprego.sapo.pt/ofertas-emprego?q={q}&l={l}"),
        ("IEFP", "https://iefponline.iefp.pt/IEFP/pesquisas/search.do?keyword={q}"),
        ("ITJobs (IT)", "https://www.itjobs.pt/emprego?q={q}")]),
    "IT": ("Italy", "it", "€", False, "it", [
        ("Indeed", "https://it.indeed.com/offerte-lavoro?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("InfoJobs", "https://www.infojobs.it/offerte-lavoro/{qs}?location={l}"),
        ("Subito Lavoro", "https://www.subito.it/annunci-italia/vendita/offerte-lavoro/?q={q}"),
        ("Adzuna", "https://www.adzuna.it/search?q={q}&w={l}")]),
    "PL": ("Poland", "pl", "zł", False, "pl", [
        ("Pracuj.pl", "https://www.pracuj.pl/praca/{q};kw/{l};wp"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("Indeed", "https://pl.indeed.com/praca?q={q}&l={l}"),
        ("OLX Praca", "https://www.olx.pl/praca/q-{qs}/"),
        ("Adzuna", "https://www.adzuna.pl/search?q={q}&w={l}")]),
    "AT": ("Austria", "at", "€", False, "de", [
        ("Karriere.at", "https://www.karriere.at/jobs/{qs}/{ls}"),
        ("AMS", "https://jobs.ams.at/public/emps/jobs?query={q}&location={l}"),
        ("StepStone", "https://www.stepstone.at/jobs/{qs}/in-{ls}"),
        ("Indeed", "https://at.indeed.com/jobs?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}")]),
    "CH": ("Switzerland", "ch", "CHF", False, "de", [
        ("jobs.ch", "https://www.jobs.ch/en/vacancies/?term={q}&location={l}"),
        ("Jobup (French-speaking)", "https://www.jobup.ch/en/jobs/?term={q}&location={l}"),
        ("Indeed", "https://ch.indeed.com/jobs?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}")]),
    "US": ("United States", "us", "$", True, "en", [
        ("Indeed", "https://www.indeed.com/jobs?q={q}&l={l}&radius={mi}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("Glassdoor", "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&locKeyword={l}"),
        ("ZipRecruiter", "https://www.ziprecruiter.com/jobs-search?search={q}&location={l}&radius={mi}"),
        ("USAJOBS (government)", "https://www.usajobs.gov/Search/Results?k={q}&l={l}")]),
    "CA": ("Canada", "ca", "$", False, "en", [
        ("Indeed", "https://ca.indeed.com/jobs?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("Job Bank", "https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring={q}&locationstring={l}"),
        ("Workopolis", "https://www.workopolis.com/jobsearch/find-jobs?ak={q}&l={l}")]),
    "AU": ("Australia", "au", "$", False, "en", [
        ("SEEK", "https://www.seek.com.au/{qs}-jobs/in-{ls}"),
        ("Indeed", "https://au.indeed.com/jobs?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("Workforce Australia", "https://www.workforceaustralia.gov.au/individuals/jobs/search?searchText={q}")]),
    "AE": ("United Arab Emirates", "", "AED", False, "en", [
        ("Bayt", "https://www.bayt.com/en/uae/jobs/{qs}-jobs/"),
        ("Indeed", "https://ae.indeed.com/jobs?q={q}&l={l}"),
        ("LinkedIn", "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}"),
        ("GulfTalent", "https://www.gulftalent.com/jobs/search?keywords={q}")]),
}
ALIASES = {"UK": "GB", "ENGLAND": "GB", "SCOTLAND": "GB", "WALES": "GB", "NORTHERN IRELAND": "GB"}


def code_for(value: str) -> str:
    v = (value or "").strip().upper()
    if v in COUNTRIES:
        return v
    if v in ALIASES:
        return ALIASES[v]
    for code, c in COUNTRIES.items():
        if c[0].upper() == v:
            return code
    return "GB"


def name(code: str) -> str:
    return COUNTRIES.get(code_for(code), COUNTRIES["GB"])[0]


def adzuna(code: str) -> str:
    return COUNTRIES.get(code_for(code), COUNTRIES["GB"])[1]


def currency(code: str) -> str:
    return COUNTRIES.get(code_for(code), COUNTRIES["GB"])[2]


def uses_miles(code: str) -> bool:
    return COUNTRIES.get(code_for(code), COUNTRIES["GB"])[3]


def language(code: str) -> str:
    return COUNTRIES.get(code_for(code), COUNTRIES["GB"])[4]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def site_links(code: str, title: str, place: str, miles: int = 15) -> list[tuple[str, str]]:
    sites = COUNTRIES.get(code_for(code), COUNTRIES["GB"])[5]
    vals = {"q": quote_plus(title or ""), "l": quote_plus(place or ""), "qs": _slug(title), "ls": _slug(place),
            "mi": int(miles or 15), "km": int(round((miles or 15) * 1.609))}
    return [(n, u.format(**vals)) for n, u in sites]


def site_names(code: str) -> list[str]:
    return [n for n, _ in COUNTRIES.get(code_for(code), COUNTRIES["GB"])[5]]


# International dialling codes, so a phone number works on forms anywhere ("+44" for the United Kingdom).
DIAL_CODES = [
    ("GB", "United Kingdom", "+44"), ("IE", "Ireland", "+353"), ("FR", "France", "+33"), ("DE", "Germany", "+49"),
    ("NL", "Netherlands", "+31"), ("BE", "Belgium", "+32"), ("ES", "Spain", "+34"), ("PT", "Portugal", "+351"),
    ("IT", "Italy", "+39"), ("PL", "Poland", "+48"), ("AT", "Austria", "+43"), ("CH", "Switzerland", "+41"),
    ("SE", "Sweden", "+46"), ("NO", "Norway", "+47"), ("DK", "Denmark", "+45"), ("FI", "Finland", "+358"),
    ("RO", "Romania", "+40"), ("GR", "Greece", "+30"), ("CZ", "Czechia", "+420"), ("HU", "Hungary", "+36"),
    ("LT", "Lithuania", "+370"), ("LV", "Latvia", "+371"), ("BG", "Bulgaria", "+359"), ("TR", "Türkiye", "+90"),
    ("US", "United States", "+1"), ("CA", "Canada", "+1"), ("AU", "Australia", "+61"), ("NZ", "New Zealand", "+64"),
    ("AE", "United Arab Emirates", "+971"), ("SA", "Saudi Arabia", "+966"), ("QA", "Qatar", "+974"),
    ("KW", "Kuwait", "+965"), ("EG", "Egypt", "+20"), ("MA", "Morocco", "+212"), ("SO", "Somalia", "+252"),
    ("SL", "Somaliland", "+252"), ("ET", "Ethiopia", "+251"), ("KE", "Kenya", "+254"), ("NG", "Nigeria", "+234"),
    ("GH", "Ghana", "+233"), ("ZA", "South Africa", "+27"), ("IN", "India", "+91"), ("PK", "Pakistan", "+92"),
    ("BD", "Bangladesh", "+880"), ("LK", "Sri Lanka", "+94"), ("PH", "Philippines", "+63"), ("CN", "China", "+86"),
    ("HK", "Hong Kong", "+852"), ("SG", "Singapore", "+65"), ("MY", "Malaysia", "+60"), ("JP", "Japan", "+81"),
    ("KR", "South Korea", "+82"), ("BR", "Brazil", "+55"), ("MX", "Mexico", "+52"), ("AR", "Argentina", "+54"),
    ("JM", "Jamaica", "+1"), ("TT", "Trinidad and Tobago", "+1"),
]


def dial_code(country: str | None) -> str:
    country = (country or "GB").upper()
    return next((code for c, _, code in DIAL_CODES if c == country), "+44")


def international(phone: str, code: str) -> str:
    """'07392 003078' with '+44' → '+44 7392 003078' (numbers already starting with + are left alone)."""
    phone = (phone or "").strip()
    if not phone or phone.startswith("+") or phone.startswith("00"):
        return phone
    return f"{code} {phone[1:] if phone.startswith('0') else phone}".strip()
