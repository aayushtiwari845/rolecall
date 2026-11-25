"""Deterministic enrichment: fast, free, testable.

Every job goes through these rules at ingest time. They decide whether a posting is a
tech role at all (non-tech roles are dropped), and fill seniority, role family,
employment and remote type, locations, skills, years of experience and salary.
An LLM pass can later refine low-confidence fields, but the system works without one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.enrich.locations import parse_location
from app.enrich.skills import extract_skills
from app.ingest.types import RawJob

RULES_VERSION = 7

# ---------------------------------------------------------------- tech filter
_TECH_TITLE = re.compile(
    r"engineer|engineering|developer|programmer|\bsde\b|\bswe\b|software|scientist|"
    r"machine learning|\bml\b|\bai\b|\bllm|data\b|analytics|devops|\bsre\b|site reliability|"
    r"infrastructure|platform|cloud|security|\bqa\b|\bsdet\b|test automation|full[- ]?stack|"
    r"back[- ]?end|front[- ]?end|mobile|android|\bios\b|firmware|embedded|architect|"
    r"technical intern|tech intern|research intern|technologist",
    re.I,
)
_NON_TECH = re.compile(
    r"\bsales\b|account (?:executive|manager)|recruit|talent|\bhr\b|human resources|marketing|"
    r"customer success|legal|counsel|finance|accountant|payroll|office manager|"
    r"mechanical|civil|chemical|electrical engineer|structural|manufacturing|hvac|construction|"
    r"field service|process engineer|quality inspector|biomedical|clinical|nurse|pharma|"
    r"product designer|graphic designer|ux designer|ui/ux designer|copywriter|content writer|"
    r"business development|\bbdr\b|\bsdr\b|partnerships|procurement|supply chain|warehouse|"
    r"executive assistant|community manager|social media|\bpr\b|data entry|"
    r"product manager|program manager|project manager|product owner|scrum master|"
    r"solutions? (?:engineer|architect|consultant)|customer (?:engineer|architect)|pre-?sales|"
    r"technical account manager|implementation (?:consultant|specialist)",
    re.I,
)


# Titles that are software work on their own. Generic ones ("Engineer", "Architect",
# "Intern") need evidence from the description, since "Simulation Engineer" or
# "Hardware Engineer" are engineering but not software.
_STRONG_TECH_TITLE = re.compile(
    r"developer|programmer|\bsde\b|\bswe\b|software|machine learning|\bml\b|\bai\b|\bllm|"
    r"\bdata (?:engineer|scien|analy|platform)|analytics engineer|devops|\bsre\b|site reliability|"
    r"\bcloud|security engineer|\bsdet\b|test automation|full[- ]?stack|back[- ]?end|front[- ]?end|"
    r"\bmobile|android|\bios\b|firmware|embedded software|platform engineer|infrastructure engineer|"
    r"web |\bapplied scientist|research (?:engineer|scientist)|\bqa\b",
    re.I,
)
_SOFTWARE_CATEGORIES = {
    "language",
    "backend",
    "frontend",
    "mobile",
    "database",
    "data",
    "ml",
    "ai",
    "cloud",
    "infra",
}


def looks_tech_title(title: str) -> bool:
    return bool(_TECH_TITLE.search(title)) and not _NON_TECH.search(title)


def is_tech_role(title: str, skills: list[str]) -> bool:
    if not looks_tech_title(title):
        return False
    if _STRONG_TECH_TITLE.search(title):
        return True
    from app.enrich.skills import CATEGORIES

    software = [s for s in skills if CATEGORIES.get(s) in _SOFTWARE_CATEGORIES]
    return len(software) >= 3


# Common function words; postings mostly in another language are dropped because the
# audience applies in English.
_EN = re.compile(r"\b(the|and|with|you|our|will|for|are|your|team|experience)\b", re.I)
_OTHER = re.compile(
    r"\b(und|mit|für|der|die|das|wir|sie|ihre|bei|oder|"  # German
    r"el|los|las|para|con|una|nuestro|experiencia|"  # Spanish
    r"les|des|pour|avec|vous|nous|une|"  # French
    r"você|para|com|uma|não|nosso|"  # Portuguese
    r"het|een|wij|voor|"  # Dutch
    r"och|att|för|med)\b",  # Swedish
    re.I,
)


def is_english(title: str, text: str) -> bool:
    sample = f"{title} {text[:2500]}"
    en, other = len(_EN.findall(sample)), len(_OTHER.findall(sample))
    if en + other < 8:
        return not re.search(
            r"\(m/w/d\)|\(w/m/d\)|praktikum|werkstudent|ingenieur|desarrollador|estágio|stagiaire",
            title,
            re.I,
        )
    return en >= other * 1.5


# ---------------------------------------------------------------- role family
_FAMILY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("security", re.compile(r"security|appsec|infosec|penetration|cyber|devsecops", re.I)),
    (
        "ai_llm",
        re.compile(
            r"\bllm|gen(?:erative)?\s?ai|\bai engineer|applied ai|\bai (?:agent|platform|product)|prompt|\bagents?\b|ai/ml engineer|ai developer|ai research",
            re.I,
        ),
    ),
    (
        "ml",
        re.compile(
            r"machine learning|\bml\b|mlops|deep learning|computer vision|\bnlp\b|research scientist|applied scientist|research engineer|\bai\b|recommend|ranking|perception",
            re.I,
        ),
    ),
    (
        "data_eng",
        re.compile(
            r"data engineer|data platform|\betl\b|analytics engineer|big data|data infrastructure|data pipeline",
            re.I,
        ),
    ),
    (
        "data_science",
        re.compile(
            r"data scien|data analyst|analytics|statistician|business intelligence|\bbi\b|quant|decision scien|insights",
            re.I,
        ),
    ),
    (
        "infra",
        re.compile(
            r"devops|\bsre\b|site reliability|infrastructure|platform engineer|cloud|systems engineer|reliability|network engineer|kubernetes|production engineer|build engineer|release engineer|developer productivity",
            re.I,
        ),
    ),
    ("mobile", re.compile(r"android|\bios\b|mobile|flutter|react native", re.I)),
    ("embedded", re.compile(r"embedded|firmware|fpga|hardware|robotics|asic|silicon", re.I)),
    ("qa", re.compile(r"\bqa\b|quality|\btest|\bsdet\b|automation engineer", re.I)),
    ("fullstack", re.compile(r"full[- ]?stack", re.I)),
    (
        "frontend",
        re.compile(
            r"front[- ]?end|\bui engineer|web developer|react developer|javascript|\bweb engineer",
            re.I,
        ),
    ),
    (
        "backend",
        re.compile(
            r"back[- ]?end|server|\bapi\b|distributed systems|java developer|python developer|golang|go engineer|payments|core banking",
            re.I,
        ),
    ),
    (
        "swe",
        re.compile(
            r"software|\bsde\b|\bswe\b|developer|programmer|engineer|technologist|architect", re.I
        ),
    ),
]


def role_family(title: str, department: str | None = None) -> str:
    for family, pat in _FAMILY_RULES:
        if pat.search(title):
            return family
    if department:
        for family, pat in _FAMILY_RULES[:-1]:
            if pat.search(department):
                return family
    return "swe" if looks_tech_title(title) else "other"


# ---------------------------------------------------------------- seniority
_INTERN = re.compile(
    r"\bintern(?:ship)?s?\b|\btrainee\b|apprentice|\bco-?op\b|working student|werkstudent|summer (?:analyst|associate|engineer)|industrial placement",
    re.I,
)
_NEW_GRAD = re.compile(
    r"new grad|graduate|entry[- ]level|fresher|university|campus|early career|associate (?:software|engineer|developer|data)|\bsde[- ]?(?:i|1)\b|\b(?:engineer|developer) (?:i|1)\b|\blevel (?:i|1)\b|\bl1\b|\bjunior\b|\bjr\.?\b|20(?:2[5-9]) start",
    re.I,
)
_STAFF = re.compile(
    r"\bstaff\b|principal|distinguished|\bfellow\b|director|head of|\bvp\b|vice president|chief|\bcto\b|engineering manager|manager,|\bmanager\b",
    re.I,
)
_SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|\blead\b|\bsde[- ]?(?:iii|3)\b|\b(?:engineer|developer) (?:iii|iv|3|4)\b|\bl[4-6]\b",
    re.I,
)
_MID = re.compile(
    r"\bsde[- ]?(?:ii|2)\b|\b(?:engineer|developer) (?:ii|2)\b|\bmid[- ]level\b|\bintermediate\b",
    re.I,
)

_YOE = re.compile(
    r"(?:(?:minimum|min\.?|at least|over)\s+(?:of\s+)?)?(\d{1,2})(?:\.\d)?\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?"
    r"(?:years?|yrs?)(?:'s)?(?:\s+of)?(?:\s+[\w/+#.-]+){0,5}?\s+(?:experience|exp\b|industry|professional|work)",
    re.I,
)
_YOE_ALT = re.compile(
    r"experience\s*(?:of|:)?\s*(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:years|yrs)", re.I
)


def years_of_experience(text: str) -> tuple[float | None, float | None]:
    """The first stated requirement wins: postings lead with the core ask
    ("5+ years of software engineering") before narrower ones ("2+ years of React")."""
    found: list[tuple[int, float, float | None]] = []
    for m in list(_YOE.finditer(text)) + list(_YOE_ALT.finditer(text)):
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else None
        if lo > 15 or (hi is not None and (hi < lo or hi > 20)):
            continue
        # "1+ years ... 5+ years preferred": a later "preferred" does not override.
        found.append((m.start(), lo, hi))
    if not found:
        return None, None
    _, lo, hi = min(found)
    return lo, hi


def seniority(
    title: str, min_yoe: float | None, employment_hint: str | None, text: str = ""
) -> str | None:
    if employment_hint == "intern" or _INTERN.search(title):
        return "intern"
    if _STAFF.search(title):
        return "staff_plus"
    if _SENIOR.search(title):
        return "senior"
    if _NEW_GRAD.search(title):
        return "new_grad" if not re.search(r"junior|jr", title, re.I) else "junior"
    if _MID.search(title):
        return "mid"
    if min_yoe is not None:
        if min_yoe <= 1:
            return "new_grad"
        if min_yoe <= 2:
            return "junior"
        if min_yoe <= 5:
            return "mid"
        return "senior"
    if re.search(
        r"new grad|recent graduates?|freshers? (?:welcome|can apply)|0-1 years?|no experience required",
        text[:4000],
        re.I,
    ):
        return "new_grad"
    return None  # no signal: unknown, the LLM pass or ranking handles it


# ---------------------------------------------------------------- employment / remote
def employment_type(title: str, hint: str | None, level: str, text: str) -> str:
    if hint:
        return hint
    if level == "intern":
        return "intern"
    if re.search(r"\bcontract(?:or)?\b|freelance|\btemporary\b|\btemp\b", title, re.I):
        return "contract"
    if re.search(r"part[- ]time", title, re.I):
        return "part_time"
    return "full_time"


_LI_TAG = re.compile(r"#LI[-_ ]?(remote|hybrid|onsite|on-site)\b", re.I)
_HYBRID_TEXT = re.compile(
    r"hybrid (?:work|working|model|schedule|role based|position|arrangement|setup|policy)|"
    r"\d\s*(?:days?|x)\s*(?:a|per|/)\s*week(?:\s*(?:in|at|from)\s*(?:the|our)?\s*office)?|"
    r"(?:in|from) (?:the|our) office \d\s*days|onsite (?:on )?(?:monday|tuesday|wednesday|thursday|friday)|"
    r"in[- ]office (?:on )?(?:monday|tuesday|wednesday|thursday)|this is a hybrid \(",
    re.I,
)
_REMOTE_TEXT = re.compile(
    r"fully remote|100% remote|remote[- ](?:first|only)|work from anywhere|"
    r"this (?:role|position) is (?:fully )?remote|(?:role|position|job) (?:is|can be) (?:performed|done) remotely",
    re.I,
)


def remote_type(hint: str | None, location: str, title: str, text: str) -> str:
    if hint:
        return hint
    loc = f"{location} {title}"
    if re.search(r"\bhybrid\b", loc, re.I):
        return "hybrid"
    if re.search(r"\bremote\b|work from home|\bwfh\b|anywhere", loc, re.I):
        return "remote"
    # Recruiters' LinkedIn tags state the work mode explicitly.
    tag = _LI_TAG.search(text)
    if tag:
        return {"remote": "remote", "hybrid": "hybrid"}.get(tag.group(1).lower(), "onsite")
    # "Hybrid" alone is ambiguous ("a hybrid role between data and engineering"), so
    # only phrases about where and when people work count.
    if _HYBRID_TEXT.search(text):
        return "hybrid"
    if _REMOTE_TEXT.search(text[:4000]):
        return "remote"
    return "onsite"


# ---------------------------------------------------------------- salary
_MULT = {
    "k": 1e3,
    "l": 1e5,
    "lpa": 1e5,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "cr": 1e7,
    "crore": 1e7,
    "m": 1e6,
}
_INR = re.compile(
    r"(?:₹|inr|rs\.?)\s*([\d,.]+)\s*(k|l|lpa|lakhs?|lac|cr|crore)?\s*(?:-|–|to)\s*(?:₹|inr|rs\.?)?\s*([\d,.]+)\s*(k|l|lpa|lakhs?|lac|cr|crore)?"
    r"|([\d.]+)\s*(?:-|–|to)\s*([\d.]+)\s*(lpa|lakhs?)",
    re.I,
)
_USD = re.compile(
    r"(\$|usd\s?|€|eur\s?|£|gbp\s?)([\d,.]+)\s*(k)?\s*(?:-|–|to)\s*(?:\$|usd\s?|€|eur\s?|£|gbp\s?)?([\d,.]+)\s*(k)?",
    re.I,
)
_PERIOD = [
    (re.compile(r"per month|/\s?month|/mo\b|monthly|a month|stipend", re.I), "month"),
    (re.compile(r"per hour|/\s?h(?:ou)?r\b|hourly", re.I), "hour"),
]
_CUR = {"$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _period(window: str) -> str:
    for pat, period in _PERIOD:
        if pat.search(window):
            return period
    return "year"


def salary(text: str) -> tuple[float | None, float | None, str | None, str | None]:
    m = _INR.search(text)
    if m:
        if m.group(5):
            lo, hi, unit_lo, unit_hi = _num(m.group(5)), _num(m.group(6)), m.group(7), m.group(7)
        else:
            lo, hi, unit_lo, unit_hi = _num(m.group(1)), _num(m.group(3)), m.group(2), m.group(4)
            unit_lo = unit_lo or unit_hi
        if lo and hi:
            mul_lo = _MULT.get((unit_lo or "").lower(), 1)
            mul_hi = _MULT.get((unit_hi or unit_lo or "").lower(), 1)
            window = text[m.start() : m.end() + 40]
            period = (
                "year"
                if (unit_lo or "").lower() in {"lpa", "l", "lakh", "lakhs", "lac", "cr", "crore"}
                else _period(window)
            )
            return lo * mul_lo, hi * mul_hi, "INR", period
    m = _USD.search(text)
    if m:
        lo, hi = _num(m.group(2)), _num(m.group(4))
        if lo and hi:
            k = 1e3 if (m.group(3) or m.group(5)) else 1
            lo, hi = lo * k, hi * k
            if hi >= 1000:  # ignore tiny numbers like "$5-10" (not salaries)
                window = text[m.start() : m.end() + 40]
                return lo, hi, _CUR.get(m.group(1).strip().lower(), "USD"), _period(window)
    return None, None, None, None


# Rough fixed rates, only for "minimum pay" filtering and display normalisation.
FX_TO_INR = {
    "INR": 1.0,
    "USD": 85.0,
    "EUR": 92.0,
    "GBP": 108.0,
    "CAD": 62.0,
    "AUD": 56.0,
    "SGD": 64.0,
    "AED": 23.0,
}
_PER_YEAR = {"year": 1, "month": 12, "hour": 2000}


def annual_inr(amount: float | None, currency: str | None, period: str | None) -> float | None:
    if amount is None or not currency:
        return None
    rate = FX_TO_INR.get(currency.upper())
    if rate is None:
        return None
    return amount * rate * _PER_YEAR.get(period or "year", 1)


# ---------------------------------------------------------------- orchestration
@dataclass
class Enrichment:
    is_tech: bool
    seniority: str | None
    role_family: str
    employment_type: str
    remote_type: str
    cities: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    min_yoe: float | None = None
    max_yoe: float | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None


def enrich(job: RawJob) -> Enrichment:
    text = job.description_text or ""
    title = job.title or ""
    skills = extract_skills(f"{title}\n{text}")[:40]
    tech = is_tech_role(title, skills)
    if not tech and job.source_kind in {"hn"}:
        tech = bool(_TECH_TITLE.search(text[:500]))
    tech = tech and is_english(title, text)
    lo, hi = years_of_experience(text)
    level = seniority(title, lo, job.employment_hint, text)
    loc = parse_location(job.location_raw, job.countries_hint)
    remote = remote_type(job.remote_hint, job.location_raw or "", title, text)
    countries = list(loc.countries)
    if remote == "remote" and loc.worldwide and "WW" not in countries:
        countries.append("WW")
    countries += [f"R:{r}" for r in loc.regions if f"R:{r}" not in countries]
    smin, smax, cur, period = (
        job.salary_min,
        job.salary_max,
        job.salary_currency,
        job.salary_period,
    )
    if smin is None and smax is None:
        smin, smax, cur, period = salary(text)
    return Enrichment(
        is_tech=tech,
        seniority=level,
        role_family=role_family(title, job.department),
        employment_type=employment_type(title, job.employment_hint, level, text),
        remote_type=remote,
        cities=loc.cities,
        countries=countries,
        skills=extract_skills(f"{title}\n{text}")[:40],
        min_yoe=lo,
        max_yoe=hi,
        salary_min=smin,
        salary_max=smax,
        salary_currency=(cur or None) and cur.upper(),
        salary_period=period,
    )
