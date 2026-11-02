"""Every kind of work, so anyone can pick the jobs they want – with the usual titles and skills for each field.

Used by the set-up and My settings pages (pick a field, tick the titles), to suggest skills for scoring, and to
link each search to the right category on CV-Library, NHS Jobs, Civil Service Jobs and the other job sites."""
from __future__ import annotations

import re

# key: (label, CV-Library category, [job titles], [skills])
SECTORS: dict[str, tuple[str, str, list[str], list[str]]] = {
    "admin": ("Administration and office", "administration",
              ["Administrator", "Office Administrator", "Admin Assistant", "Receptionist", "Office Manager",
               "Personal Assistant", "Executive Assistant", "Data Entry Clerk", "Secretary", "Medical Secretary",
               "Legal Secretary", "Team Administrator", "Operations Administrator", "Facilities Coordinator"],
              ["Microsoft Office", "Data entry", "Diary management", "Minute taking", "Filing", "Customer service",
               "Attention to detail", "Organisation"]),
    "accountancy": ("Accountancy and finance", "accountancy",
                    ["Accounts Assistant", "Accounts Payable Clerk", "Accounts Receivable Clerk", "Credit Controller",
                     "Bookkeeper", "Payroll Administrator", "Payroll Officer", "Finance Assistant", "Assistant Accountant",
                     "Management Accountant", "Financial Accountant", "Finance Manager", "Financial Analyst",
                     "Financial Controller", "Tax Advisor", "Auditor"],
                    ["Excel", "Sage", "Xero", "QuickBooks", "Reconciliations", "Purchase ledger", "Sales ledger",
                     "VAT returns", "Month end", "AAT", "ACCA", "CIMA"]),
    "banking": ("Banking, insurance and financial services", "banking",
                ["Customer Service Advisor (Banking)", "Bank Cashier", "Mortgage Advisor", "Financial Adviser",
                 "Fraud Analyst", "Compliance Officer", "KYC Analyst", "AML Analyst", "Claims Handler",
                 "Underwriter", "Insurance Advisor", "Risk Analyst", "Relationship Manager", "Investment Analyst"],
                ["FCA regulations", "KYC", "AML", "Fraud prevention", "Claims handling", "Customer service",
                 "Risk assessment", "CeMAP"]),
    "customer_services": ("Customer service and call centre", "customer_services",
                          ["Customer Service Advisor", "Customer Service Assistant", "Call Centre Agent",
                           "Contact Centre Advisor", "Customer Experience Advisor", "Complaints Handler",
                           "Customer Support Specialist", "Customer Success Manager", "Help Desk Advisor",
                           "Team Leader (Customer Service)", "Customer Service Manager", "Live Chat Agent"],
                          ["Customer service", "Complaints handling", "Call handling", "CRM", "Salesforce",
                           "Zendesk", "Problem solving", "Active listening", "De-escalation"]),
    "sales": ("Sales and business development", "sales",
              ["Sales Assistant", "Sales Executive", "Sales Advisor", "Telesales Executive", "Business Development Executive",
               "Business Development Manager", "Account Manager", "Key Account Manager", "Field Sales Representative",
               "Sales Manager", "Sales Coordinator", "Estate Agent", "Lettings Negotiator", "Car Sales Executive"],
              ["B2B sales", "B2C sales", "Lead generation", "Negotiation", "CRM", "Salesforce", "Cold calling",
               "Account management", "Targets"]),
    "marketing": ("Marketing, PR and communications", "marketing",
                  ["Marketing Assistant", "Marketing Executive", "Digital Marketing Executive", "Social Media Executive",
                   "Content Writer", "Copywriter", "SEO Executive", "PPC Executive", "Email Marketing Executive",
                   "Marketing Manager", "Communications Officer", "PR Executive", "Brand Manager", "Events Coordinator"],
                  ["SEO", "PPC", "Google Analytics", "Social media", "Copywriting", "Content creation", "Canva",
                   "HubSpot", "Email marketing", "Adobe Creative Suite"]),
    "it": ("IT, software and data", "it",
           ["IT Support Technician", "Service Desk Analyst", "IT Support Engineer", "Junior Developer",
            "Software Developer", "Software Engineer", "Web Developer", "Front End Developer", "Back End Developer",
            "Full Stack Developer", "Data Analyst", "Data Engineer", "Data Scientist", "Business Analyst",
            "Systems Administrator", "Network Engineer", "Cyber Security Analyst", "DevOps Engineer",
            "QA Tester", "Product Manager", "Project Manager (IT)", "Scrum Master", "UX Designer"],
           ["Python", "JavaScript", "SQL", "Excel", "Power BI", "Azure", "AWS", "Windows", "Microsoft 365",
            "Active Directory", "Networking", "Git", "Agile", "ITIL"]),
    "design": ("Design, creative and media", "design",
               ["Graphic Designer", "Junior Designer", "UI Designer", "UX Designer", "Motion Graphics Designer",
                "Video Editor", "Photographer", "Illustrator", "Interior Designer", "Animator", "Creative Assistant",
                "Journalist", "Editor", "Producer", "Runner"],
               ["Adobe Photoshop", "Adobe Illustrator", "Adobe InDesign", "Figma", "Premiere Pro", "After Effects",
                "Typography", "Branding", "Video editing"]),
    "education": ("Education and teaching", "education",
                  ["Teaching Assistant", "Learning Support Assistant", "Special Needs Teaching Assistant",
                   "Primary Teacher", "Secondary Teacher", "Cover Supervisor", "Nursery Practitioner", "Nursery Nurse",
                   "Early Years Practitioner", "Tutor", "Lecturer", "Trainer", "Learning Facilitator",
                   "Exams Officer", "School Administrator", "SENCO", "Assessor"],
                  ["Lesson planning", "Behaviour management", "Safeguarding", "SEN", "EYFS", "Classroom support",
                   "Enhanced DBS", "QTS"]),
    "healthcare": ("Healthcare and nursing", "healthcare",
                   ["Healthcare Assistant", "Nursing Assistant", "Registered Nurse", "Staff Nurse", "Mental Health Nurse",
                    "Midwife", "Paramedic", "Pharmacy Assistant", "Pharmacist", "Dental Nurse", "Dental Receptionist",
                    "Physiotherapist", "Occupational Therapist", "Radiographer", "Phlebotomist", "GP Receptionist",
                    "Medical Receptionist", "Clinical Coding Officer", "Optical Assistant"],
                   ["Patient care", "Infection control", "Clinical observations", "Safeguarding", "Care Certificate",
                    "NMC registration", "HCPC registration", "Record keeping", "Medication administration"]),
    "care": ("Social care and support work", "healthcare",
             ["Care Assistant", "Support Worker", "Senior Care Assistant", "Home Carer", "Domiciliary Care Worker",
              "Residential Support Worker", "Mental Health Support Worker", "Care Coordinator", "Care Manager",
              "Registered Manager", "Social Worker", "Family Support Worker", "Youth Worker", "Key Worker",
              "Activities Coordinator"],
             ["Personal care", "Safeguarding", "Medication administration", "Care planning", "Moving and handling",
              "Person-centred care", "CQC standards", "Care Certificate", "NVQ/Diploma in Health and Social Care"]),
    "hr": ("HR and recruitment", "recruitment",
           ["HR Administrator", "HR Assistant", "HR Coordinator", "HR Officer", "HR Advisor", "HR Business Partner",
            "HR Manager", "People Advisor", "People Partner", "Recruitment Consultant", "Recruitment Coordinator",
            "Recruitment Advisor", "Talent Acquisition Partner", "Resourcer", "L&D Coordinator",
            "Learning and Development Advisor", "HR Systems Analyst", "Payroll and HR Administrator"],
           ["Employee relations", "Recruitment", "Onboarding", "HRIS", "Absence management", "Employment law",
            "CIPD", "Right to Work checks", "Learning and development"]),
    "legal": ("Legal", "legal",
              ["Paralegal", "Legal Assistant", "Legal Secretary", "Legal Cashier", "Conveyancing Assistant",
               "Conveyancer", "Trainee Solicitor", "Solicitor", "Legal Executive", "Litigation Assistant",
               "Compliance Assistant", "Contracts Administrator", "Court Clerk", "Legal Receptionist"],
              ["Legal research", "Case management", "Document preparation", "Conveyancing", "Litigation",
               "Attention to detail", "Client care", "Confidentiality", "LLB", "CILEx"]),
    "hospitality": ("Hospitality, catering and food", "hospitality",
                    ["Waiter/Waitress", "Bartender", "Barista", "Kitchen Porter", "Commis Chef", "Chef de Partie",
                     "Sous Chef", "Head Chef", "Cook", "Restaurant Manager", "Assistant Manager (Hospitality)",
                     "Hotel Receptionist", "Front of House", "Housekeeper", "Room Attendant", "Catering Assistant",
                     "Food Production Operative"],
                    ["Food hygiene", "Customer service", "Cash handling", "Food preparation", "Allergen awareness",
                     "Team working", "Stock rotation", "Level 2 Food Safety"]),
    "retail": ("Retail", "retail",
               ["Retail Assistant", "Sales Assistant (Retail)", "Customer Assistant", "Cashier", "Shelf Stacker",
                "Visual Merchandiser", "Stock Assistant", "Supervisor (Retail)", "Assistant Store Manager",
                "Store Manager", "Area Manager", "Pharmacy Counter Assistant", "Optical Retail Assistant"],
               ["Customer service", "Cash handling", "Visual merchandising", "Stock control", "Till operation",
                "Sales targets", "Team leadership"]),
    "warehouse": ("Warehouse, logistics and driving", "warehouse",
                  ["Warehouse Operative", "Picker Packer", "Forklift Driver", "Warehouse Team Leader",
                   "Warehouse Supervisor", "Warehouse Manager", "Stock Controller", "Goods In Operative",
                   "Delivery Driver", "Van Driver", "HGV Class 1 Driver", "HGV Class 2 Driver", "Multi-drop Driver",
                   "Courier", "Logistics Coordinator", "Transport Planner", "Supply Chain Analyst", "Shipping Clerk"],
                  ["Picking and packing", "Forklift (counterbalance)", "Reach truck", "Stock control", "WMS",
                   "Health and safety", "Full UK driving licence", "CPC", "Route planning", "Inventory management"]),
    "construction": ("Construction and trades", "construction",
                     ["Labourer", "General Builder", "Bricklayer", "Carpenter", "Joiner", "Electrician", "Plumber",
                      "Gas Engineer", "Painter and Decorator", "Plasterer", "Roofer", "Groundworker", "Site Manager",
                      "Quantity Surveyor", "Estimator", "Construction Manager", "Building Surveyor",
                      "Maintenance Operative", "Multi-skilled Operative", "Handyperson"],
                     ["CSCS card", "Health and safety", "Reading drawings", "SMSTS", "SSSTS", "18th Edition",
                      "Gas Safe", "City & Guilds", "NVQ Level 2/3", "Power tools"]),
    "engineering": ("Engineering and manufacturing", "engineering",
                    ["Production Operative", "Machine Operator", "Assembly Operative", "CNC Machinist",
                     "Maintenance Engineer", "Mechanical Engineer", "Electrical Engineer", "Field Service Engineer",
                     "Design Engineer", "Quality Inspector", "Quality Engineer", "Process Engineer",
                     "Manufacturing Engineer", "Project Engineer", "Welder", "Fabricator", "Engineering Apprentice",
                     "Production Manager"],
                    ["AutoCAD", "SolidWorks", "PLC", "Lean manufacturing", "Six Sigma", "ISO 9001",
                     "Health and safety", "Fault finding", "Preventive maintenance"]),
    "automotive": ("Automotive and motor trade", "automotive",
                   ["Vehicle Technician", "Mechanic", "MOT Tester", "Service Advisor", "Parts Advisor",
                    "Vehicle Valeter", "Body Shop Technician", "Paint Sprayer", "Tyre Fitter", "Car Sales Executive",
                    "Workshop Controller"],
                   ["Vehicle diagnostics", "Servicing", "MOT", "Customer service", "Parts ordering", "IMI Level 3"]),
    "science": ("Science, pharma and laboratory", "science",
                ["Laboratory Technician", "Lab Assistant", "Research Assistant", "Research Scientist", "Chemist",
                 "Biologist", "Microbiologist", "QC Analyst", "QA Officer", "Clinical Research Associate",
                 "Clinical Trials Assistant", "Regulatory Affairs Officer"],
                ["Laboratory techniques", "GLP", "GMP", "Data analysis", "Sample preparation", "HPLC", "LIMS"]),
    "public_sector": ("Public sector, government and civil service", "public_sector",
                      ["Administrative Officer (Civil Service)", "Executive Officer", "Higher Executive Officer",
                       "Caseworker", "Policy Officer", "Council Officer", "Housing Officer", "Benefits Advisor",
                       "Work Coach", "Revenues Officer", "Planning Officer", "Environmental Health Officer",
                       "Community Officer", "Customer Service Officer (Council)"],
                      ["Casework", "Policy", "Stakeholder engagement", "Report writing", "Data protection",
                       "Customer service", "Civil Service Success Profiles"]),
    "charity": ("Charity and not-for-profit", "charity",
                ["Fundraiser", "Fundraising Officer", "Volunteer Coordinator", "Project Officer", "Programme Officer",
                 "Community Engagement Officer", "Charity Shop Assistant", "Grants Officer", "Campaigns Officer",
                 "Support Worker (Charity)"],
                ["Fundraising", "Stakeholder engagement", "Volunteer management", "Grant writing",
                 "Community engagement", "Project management"]),
    "security": ("Security, emergency services and armed forces", "security",
                 ["Security Officer", "Door Supervisor", "CCTV Operator", "Retail Security Officer",
                  "Police Officer", "Police Community Support Officer", "Prison Officer", "Firefighter",
                  "Emergency Call Handler", "Security Supervisor"],
                 ["SIA licence", "CCTV", "Conflict management", "Patrols", "First aid", "Report writing"]),
    "cleaning": ("Cleaning and facilities", "cleaning",
                 ["Cleaner", "Office Cleaner", "Domestic Assistant", "Housekeeper", "Caretaker",
                  "Facilities Assistant", "Facilities Manager", "Porter", "Window Cleaner", "Grounds Maintenance Operative"],
                 ["Cleaning procedures", "COSHH", "Health and safety", "Time management", "Reliability"]),
    "leisure": ("Leisure, sport, travel and tourism", "leisure",
                ["Leisure Assistant", "Lifeguard", "Gym Instructor", "Personal Trainer", "Sports Coach",
                 "Travel Consultant", "Holiday Representative", "Cabin Crew", "Tour Guide", "Events Assistant",
                 "Activity Instructor"],
                ["Customer service", "First aid", "NPLQ", "Level 2/3 Fitness", "Coaching", "Sales"]),
    "aviation": ("Aviation and airports", "aviation_aerospace",
                 ["Cabin Crew", "Customer Service Agent (Airport)", "Ground Handler", "Baggage Handler",
                  "Aircraft Engineer", "Airport Security Officer", "Check-in Agent", "Air Traffic Assistant"],
                 ["Customer service", "Safety procedures", "Airside pass", "Teamwork"]),
    "property": ("Property and housing", "managerial",
                 ["Lettings Negotiator", "Estate Agent", "Property Manager", "Block Manager", "Lettings Administrator",
                  "Housing Officer", "Housing Assistant", "Surveyor", "Facilities Manager"],
                 ["Property management", "Lettings", "Tenancy law", "Customer service", "Negotiation"]),
    "purchasing": ("Procurement and purchasing", "purchasing_procurement",
                   ["Purchasing Assistant", "Buyer", "Junior Buyer", "Procurement Officer", "Procurement Manager",
                    "Category Manager", "Supply Chain Coordinator", "Merchandiser"],
                   ["Negotiation", "Supplier management", "Procurement", "SAP", "Excel", "CIPS"]),
    "environmental": ("Environment, energy and agriculture", "environmental",
                      ["Environmental Officer", "Sustainability Officer", "Ecologist", "Energy Advisor",
                       "Solar Installer", "Farm Worker", "Gardener", "Horticulturist", "Waste Operative",
                       "Water Treatment Operative"],
                      ["Environmental compliance", "Sustainability", "Data analysis", "Field work", "Driving licence"]),
    "management": ("Management, projects and consulting", "managerial",
                   ["Operations Manager", "General Manager", "Project Coordinator", "Project Manager",
                    "Programme Manager", "Business Manager", "Office Manager", "Consultant", "Management Consultant",
                    "Change Manager", "Operations Coordinator"],
                   ["Project management", "Stakeholder management", "Budgeting", "Leadership", "PRINCE2", "Agile",
                    "Process improvement", "Reporting"]),
    "beauty": ("Hair, beauty and wellbeing", "leisure",
               ["Hairdresser", "Barber", "Beauty Therapist", "Nail Technician", "Spa Therapist", "Massage Therapist",
                "Make-up Artist", "Salon Receptionist", "Salon Manager"],
               ["NVQ Level 2/3", "Client consultation", "Customer service", "Appointments", "Health and safety"]),
    "languages": ("Languages and translation", "multilingual",
                  ["Translator", "Interpreter", "Multilingual Customer Service Advisor", "Language Teacher",
                   "Bilingual Administrator"],
                  ["Translation", "Interpreting", "Fluent second language", "Customer service"]),
}

ALL_TITLES = sorted({t for _, _, titles, _ in SECTORS.values() for t in titles}, key=str.lower)


def _norm(t: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", (t or "").lower()).strip()


def search(q: str, limit: int = 20) -> list[str]:
    """Job titles for a few typed letters: 'ware' → Warehouse Operative, Warehouse Manager…"""
    q = (q or "").strip().lower()
    if not q:
        return []
    starts = [t for t in ALL_TITLES if t.lower().startswith(q)]
    words = [t for t in ALL_TITLES if t not in starts and any(w.startswith(q) for w in t.lower().split())]
    inside = [t for t in ALL_TITLES if t not in starts and t not in words and q in t.lower()]
    return (starts + words + inside)[:limit]


def sectors_for(titles: list[str]) -> list[str]:
    """Which fields a set of chosen job titles belong to (by exact title, then by shared words)."""
    found = []
    for t in titles or []:
        n = _norm(t)
        best = None
        for key, (_, _, ts, _) in SECTORS.items():
            if any(_norm(x) == n for x in ts):
                best = key
                break
        if not best:
            tw = set(re.findall(r"[a-z]+", n)) - {"assistant", "manager", "officer", "advisor", "senior", "junior",
                                                    "lead", "team", "leader", "coordinator", "executive", "and"}
            scores = []
            for key, (label, _, ts, _) in SECTORS.items():
                vocab = set(re.findall(r"[a-z]+", " ".join(ts).lower() + " " + label.lower()))
                scores.append((len(tw & vocab), key))
            scores.sort(reverse=True)
            if scores and scores[0][0] > 0:
                best = scores[0][1]
        if best and best not in found:
            found.append(best)
    return found


def skills_for(titles: list[str], limit: int = 12) -> list[str]:
    out = []
    for key in sectors_for(titles):
        for s in SECTORS[key][3]:
            if s not in out:
                out.append(s)
    return out[:limit]


def as_json() -> dict:
    return {k: {"label": v[0], "titles": v[2], "skills": v[3]} for k, v in SECTORS.items()}


# ------------------------------------------------------------------ search the big job sites, ready-filled
def _q(s: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(s or "")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def search_links(title: str, place: str, miles: int = 15, country: str = "GB") -> list[tuple[str, str]]:
    """(site, url) – each opens that site's own search for this job and place, on the main sites of the person's
    country (and, in the UK, the specialist sites for their field too)."""
    from . import countries
    if countries.code_for(country) != "GB":
        return countries.site_links(country, _norm(title) or title, place, miles)
    t, p = _q(_norm(title) or title), _q(place)
    links = [
        ("Indeed", f"https://uk.indeed.com/jobs?q={t}&l={p}&radius={miles}"),
        ("LinkedIn", f"https://www.linkedin.com/jobs/search/?keywords={t}&location={p}"),
        ("Reed", f"https://www.reed.co.uk/jobs/{_slug(_norm(title))}-jobs-in-{_slug(place)}?proximity={miles}"),
        ("CV-Library", f"https://www.cv-library.co.uk/search-jobs?q={t}&geo={p}&distance={miles}"),
        ("Totaljobs", f"https://www.totaljobs.com/jobs/{_slug(_norm(title))}/in-{_slug(place)}?radius={miles}"),
        ("Adzuna", f"https://www.adzuna.co.uk/jobs/search?q={t}&w={p}&d={miles}"),
        ("Glassdoor", f"https://www.glassdoor.co.uk/Job/jobs.htm?sc.keyword={t}&locKeyword={p}"),
        ("Guardian Jobs", f"https://jobs.theguardian.com/searchjobs/?Keywords={t}&radialtown={p}&RadialLocation={miles}"),
        ("Find a job (GOV.UK)", f"https://findajob.dwp.gov.uk/search?q={t}&w={p}&d={miles}"),
    ]
    sectors = sectors_for([title])
    if {"healthcare", "care"} & set(sectors):
        links.append(("NHS Jobs", f"https://www.jobs.nhs.uk/candidate/search/results?keyword={t}&location={p}&distance={miles}"))
    if {"public_sector", "admin", "management"} & set(sectors):
        links.append(("Civil Service Jobs", f"https://www.civilservicejobs.service.gov.uk/csr/index.cgi?SID=&what={t}&where={p}"))
    if "education" in sectors:
        links.append(("Teaching Vacancies (GOV.UK)", f"https://teaching-vacancies.service.gov.uk/jobs?keyword={t}&location={p}&radius={miles}"))
    if "charity" in sectors:
        links.append(("CharityJob", f"https://www.charityjob.co.uk/jobs?keywords={t}&location={p}"))
    if "legal" in sectors:
        links.append(("TotallyLegal", f"https://www.totallylegal.com/jobs/?keywords={t}"))
    if "hospitality" in sectors:
        links.append(("Caterer.com", f"https://www.caterer.com/jobs/{_slug(_norm(title))}/in-{_slug(place)}?radius={miles}"))
    if {"it", "design"} & set(sectors):
        links.append(("CWJobs", f"https://www.cwjobs.co.uk/jobs/{_slug(_norm(title))}/in-{_slug(place)}?radius={miles}"))
    if "hr" in sectors:
        links.append(("CIPD Jobs", f"https://jobs.cipd.org/jobs/?keywords={t}&location={p}"))
    return links


def alert_links(title: str, place: str, country: str = "GB") -> list[tuple[str, str]]:
    """Where to switch on daily job-alert emails – Job Hunt HQ reads LinkedIn and Indeed alerts from Gmail."""
    from . import countries
    links = dict(countries.site_links(country, _norm(title) or title, place))
    return [(n, links[n]) for n in ("LinkedIn", "Indeed") if n in links]
