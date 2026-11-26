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

RULES_VERSION = 15

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
    r"technical account manager|implementation (?:consultant|specialist)|"
    r"hydraulic|valve|content developer|sales specialist|\bgtm\b|brand identity|designer\b|"
    r"representative|crowd-?test|test real apps|partner strategy|developer engagement|"
    r"\bseller\b|\bhw developer|hardware design",
    re.I,
)


# Titles that are software work on their own. Generic ones ("Engineer", "Architect",
# "Intern") need evidence from the description, since "Simulation Engineer" or
# "Hardware Engineer" are engineering but not software.
_STRONG_TECH_TITLE = re.compile(
    r"developer|programmer|\bsde\b|\bswe\b|software|machine learning|\bml\b|\bai\b|\bllm|"
    r"\bdata (?:engineer|scien|analy|platform)|analytics engineer|devops|\bsre\b|site reliability|"
    r"\bcloud|security engineer|\bsdet\b|test automation|full[- ]?stack|back[- ]?end|front[- ]?end|"
    r"\bmobile (?:app|developer|engineer|software)|android|\bios\b|firmware|embedded software|"
    r"platform engineer|infrastructure engineer|"
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
    r"new grad|graduate|entry[- ]level|fresher|university|campus|early career|associate (?:software|engineer|developer|data|sde)|\bsde[- ]?(?:i|1)\b|\b(?:engineer|developer) (?:i|1)\b|\blevel (?:i|1)\b|\bl1\b|\bjunior\b|\bjr\.?\b|"
    # Cohort years in any decade: "2027 start", "2026 batch", "2027 passouts", "class of 2028".
    r"\b20[2-9]\d\s*(?:start|intake|batch|graduates?|grads?|pass[- ]?outs?)\b|class of 20[2-9]\d",
    re.I,
)
_STAFF = re.compile(
    r"\bstaff\b|principal|distinguished|\bfellow\b|director|head of|\bvp\b|vice president|chief|\bcto\b|engineering manager|manager,|\bmanager\b",
    re.I,
)
# A ladder number after the job noun: "Engineer II", "Site Reliability Engineer- II",
# "Software Engineer-I", "Applied Scientist II", "Software Engineer Ⅰ".
_LADDER = r"\b(?:engineer|developer|scientist|analyst)\s*[-–]?\s*"
_SENIOR = re.compile(
    r"\bsenior\b|\bsr\.?\b|\blead\b|\bleader\b|\barchitect\b|\bexpert\b|\bsde[- ]?(?:iii|3)\b|"
    + _LADDER
    + r"(?:iii|iv|3|4|Ⅲ|Ⅳ)(?![\w.-])|\bl[4-6]\b",
    re.I,
)
_MID = re.compile(
    r"\bsde[- ]?(?:ii|2)\b|"
    + _LADDER
    + r"(?:ii|2|Ⅱ)(?![\w.-])|\bmid[- ]level\b|\bintermediate\b|\bmedior\b",
    re.I,
)
_LADDER_ONE = re.compile(_LADDER + r"(?:i|1|Ⅰ)(?![\w.-])", re.I)
# A board's own level field, e.g. LinkedIn-style "Experience level: Mid-Senior level".
# "Associate" is left out: boards use it for everything from interns to architects.
_LISTED_LEVEL = re.compile(
    r"(?:experience|seniority|career|job) level\s*[:\-–]\s*"
    r"(mid[- ]senior|executive|director|entry|internship)",
    re.I,
)
# Several asks: "Overall, 10-14 years of experience" is the requirement, a later
# "Min 1-2 yrs of hands on Exp in this skill" is not.
_OVERALL = re.compile(r"(?:overall|total|in total)\W{0,3}(?:\w+\W+){0,3}$", re.I)

_YOE = re.compile(
    r"(?:(?:minimum|min\.?|at least|over)\s+(?:of\s+)?)?(\d{1,2}(?:\.\d)?)\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?"
    r"(?:years?|yrs?)(?:'s)?(?:\s+of)?(?:\s+[\w/+#.-]+){0,5}?\s+(?:experience|exp\b|industry|professional|work)",
    re.I,
)
_YOE_ALT = re.compile(
    r"experience\s*(?:of|:)?\s*(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*(?:years|yrs)", re.I
)
_YR = r"(?:years?|yrs?)(?:'s?|’s?)?"
_YOE_MORE = [
    # "Experience: 6+ years in ...", "Experience level: 6-8 yrs", "Experience : 18+ years"
    re.compile(
        r"experience(?:\s+level)?\s*[:\-–]\s*(?:minimum\s+(?:of\s+)?|min\.?\s+|at least\s+)?"
        r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?" + _YR,
        re.I,
    ),
    # "Minimum 8-year experience", "(at least 8 years)", "4 years' minimum"
    re.compile(r"(?:minimum|at least|\bmin\b\.?)\s+(?:of\s+)?(\d{1,2})\s*\+?\s*[- ]?" + _YR, re.I),
    re.compile(r"(\d{1,2})\s*\+?\s*" + _YR + r"\s+minimum", re.I),
    # "7+ years in technical support", "5+ years building backend services", "with 4+ yrs"
    re.compile(
        r"(\d{1,2})\s*(?:\+|plus)\s*" + _YR + r"(?![a-z])(?!\s+(?:ago|old|of history|in business))",
        re.I,
    ),
]
# A bare range ("3 to 6 years", "8 - 12 years") counts only next to the word experience.
_YOE_RANGE = re.compile(
    r"(?<![\d.])(\d{1,2}(?:\.\d)?)\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*" + _YR, re.I
)
_EXPERIENCE_NEAR = re.compile(r"experien|\bexp\b", re.I)
# A line that is nothing but a span of years ("5 to 8 years" under "Additional
# Information") is how some boards print the experience field.
_YOE_LINE = re.compile(
    r"^\W{0,3}(\d{1,2}(?:\.\d)?)\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?\+?\s*" + _YR + r"\W{0,2}$",
    re.I | re.M,
)
# Company boilerplate, not a requirement: "a 25+ year track record", "the next 2+ years
# of growth", "founded 10+ years ago".
_NOT_YOE_AFTER = re.compile(
    r"\s*(?:track record|of (?:growth|history|innovation|heritage|legacy)|ago\b|old\b|in business)",
    re.I,
)
_NOT_YOE_BEFORE = re.compile(r"(?:\bnext|\bpast|\ba|\bour|\bover the|\bfor over)\s+$", re.I)


def years_of_experience(text: str) -> tuple[float | None, float | None]:
    """The first stated requirement wins: postings lead with the core ask
    ("5+ years of software engineering") before narrower ones ("2+ years of React")."""
    found: list[tuple[int, float, float | None]] = []
    matches = list(_YOE.finditer(text)) + list(_YOE_ALT.finditer(text))
    for pat in _YOE_MORE:
        matches += pat.finditer(text)
    matches += _YOE_LINE.finditer(text)
    matches += [
        m
        for m in _YOE_RANGE.finditer(text)
        if _EXPERIENCE_NEAR.search(text[max(0, m.start() - 120) : m.end() + 60])
    ]
    for m in matches:
        if _NOT_YOE_AFTER.match(text, m.end()) or _NOT_YOE_BEFORE.search(
            text[max(0, m.start() - 12) : m.start()]
        ):
            continue
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
        if lo > 25 or (hi is not None and (hi < lo or hi > 30)):
            continue
        # "1+ years ... 5+ years preferred": a later "preferred" does not override,
        # but a stated overall total does.
        overall = bool(_OVERALL.search(text[max(0, m.start() - 40) : m.start()]))
        found.append((not overall, m.start(), lo, hi))
    if not found:
        return None, None
    _, _, lo, hi = min(found)
    return lo, hi


def seniority(
    title: str, min_yoe: float | None, employment_hint: str | None, text: str = ""
) -> str | None:
    # Some boards join title words with underscores ("Software_Architect_EBH_10+Years"),
    # which would hide them from every \b pattern below.
    title = re.sub(r"[_|]+", " ", title)
    if employment_hint == "intern" or _INTERN.search(title):
        return "intern"
    if _STAFF.search(title):
        return "staff_plus"
    if _SENIOR.search(title):
        return "senior"
    if _NEW_GRAD.search(title) or _LADDER_ONE.search(title):
        return "new_grad" if not re.search(r"junior|jr", title, re.I) else "junior"
    if _MID.search(title):
        return "mid"
    listed = _LISTED_LEVEL.search(text[:3000])
    listed = listed.group(1).lower().replace(" ", "-") if listed else None
    if listed == "director":
        return "staff_plus"
    if listed == "executive":
        return "senior"
    level = None
    if min_yoe is not None:
        if min_yoe <= 1:
            level = "new_grad"
        elif min_yoe <= 2:
            level = "junior"
        elif min_yoe <= 5:
            level = "mid"
        else:
            level = "senior"
    elif re.search(
        r"new grad|recent graduates?|freshers? (?:welcome|can apply)|0-1 years?|no experience required",
        text[:4000],
        re.I,
    ):
        level = "new_grad"
    if listed == "mid-senior" and level in (None, "new_grad", "junior"):
        return "mid"  # the board says experienced hire; a narrow "1+ years of X" does not
    if level is None and listed == "entry":
        return "new_grad"
    if level is None and listed == "internship":
        return "intern"
    return level  # None: no signal, the LLM pass or ranking handles it


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


_SCOPE_US = re.compile(
    r"(?<![A-Za-z])(?:US|USA|U\.S\.)(?:[- ]only|[- ]based|\s+citizen\w*|\s+residents?|\s+work authori[sz]ation|\s+time\s?zones?)"
    r"|(?i:remote)\s*[(\[,:\-–]\s*(?:US|USA|U\.S\.|United States|North America)(?![A-Za-z])"
    r"|(?:located|based|reside|living) in the (?:US|U\.S\.|United States)"
    r"|(?:within|across) the (?:US|United States)\b|must be (?:authori[sz]ed|eligible) to work in the (?:US|United States)"
    r"|\((?:AMER|NA|NORAM)\)|(?:PT|PST|ET|EST) (?:to|-) (?:PT|PST|ET|EST)|overlap with (?:US|PT|PST|ET|EST)",
)
_SCOPE_EU = re.compile(
    r"(?i:remote)\s*[(\[,:\-–]\s*(?:EU|EEA|Europe|EMEA|UK)(?![A-Za-z])|\((?:EMEA|EU|EEA|Europe)\)|"
    r"(?:EU|EEA|Europe|UK)[- ]only|(?:located|based|reside) in (?:the )?(?:EU|EEA|Europe|UK)\b|right to work in the (?:UK|EU)",
)
_SCOPE_APAC = re.compile(r"\((?:APAC|Asia)\)|remote\s*[(\[,:\-–]\s*(?:APAC|Asia)", re.I)
_SCOPE_CANADA = re.compile(r"remote\s*[(\[,:\-–]\s*Canada|(?:located|based) in Canada", re.I)


def remote_scope(text: str) -> tuple[list[str], list[str]]:
    """Who a remote role can hire, from phrases like "REMOTE (US)", "US only", "(EMEA)"."""
    countries: list[str] = []
    regions: list[str] = []
    if _SCOPE_US.search(text):
        countries.append("US")
    if _SCOPE_CANADA.search(text):
        countries.append("CA")
    if _SCOPE_EU.search(text):
        regions.append("EU")
    if _SCOPE_APAC.search(text):
        regions.append("APAC")
    return countries, regions


_CANDIDATE_POST = re.compile(
    r"\b(?:I'?m|I am) (?:a|an)\b[^.]{0,80}\b(?:engineer|developer|programmer|scientist|designer)\b"
    r"|\bhire me\b|\bmy (?:resume|cv|portfolio)\b|\b(?:I'?m|I am) (?:looking|open) (?:for|to)\b",
    re.I,
)


_HN_ROLE = re.compile(
    r"engineer|developer|programmer|\bswe\b|\bsde\b|scientist|\bml\b|devops|\bsre\b|data|"
    r"full[- ]?stack|back[- ]?end|front[- ]?end|founding|intern\b",
    re.I,
)


_NOT_A_JOB = re.compile(
    r"looking for (?:contributors|co-?founders)|revenue[- ]share|equity[- ]only|\bunpaid\b",
    re.I,
)


# A hiring-thread header that names departments, not a role: "engineering, GTM, product,
# sales", "Multiple roles". There is nothing specific to match a resume against.
_DEPARTMENT_LIST = re.compile(
    r"^\W*(?:(?:engineering|product|design|gtm|go-to-market|sales|marketing|ops|operations|"
    r"finance|support|research|multiple roles|various roles|various|all roles|many roles)"
    r"\W*(?:\band\b\W*)?)+$",
    re.I,
)
# A location line in the body ("**Location**: EMEA") that narrows the board's list.
_BODY_LOCATION = re.compile(r"^\W{0,4}location\W{0,4}:\W{0,4}([^\n]{2,80})$", re.I | re.M)


def is_candidate_post(text: str) -> bool:
    return bool(_CANDIDATE_POST.search(text[:400]))


def enrich(job: RawJob) -> Enrichment:
    text = job.description_text or ""
    title = job.title or ""
    skills = extract_skills(f"{title}\n{text}")[:40]
    tech = is_tech_role(title, skills)
    if not tech and job.source_kind in {"hn"}:
        tech = bool(_TECH_TITLE.search(text[:500]))
    tech = tech and is_english(title, text)
    if job.source_kind == "hn" and (is_candidate_post(text) or not _HN_ROLE.search(text[:300])):
        # A job seeker's post in the hiring thread, or a post whose header names no
        # engineering role (sales, GTM, design), is not a job we can match.
        tech = False
    if job.source_kind == "hn" and _DEPARTMENT_LIST.match(title):
        tech = False
    if len(text) < 100 or re.search(r"\bblah blah\b|lorem ipsum", text[:2000], re.I):
        tech = False  # placeholder or empty postings carry nothing to match on
    if _NOT_A_JOB.search(text[:1500]):
        tech = False  # unpaid, equity-only or "looking for contributors" posts
    lo, hi = years_of_experience(text)
    t_lo, t_hi = years_of_experience(re.sub(r"[_|]+", " ", title))
    if t_lo is not None:  # "Software_Architect_EBH_10+Years": the title states it
        lo, hi = t_lo, t_hi
    level = seniority(title, lo, job.employment_hint, text)
    loc = parse_location(job.location_raw, job.countries_hint)
    remote = remote_type(job.remote_hint, job.location_raw or "", title, text)
    countries = list(loc.countries)
    regions = list(loc.regions)
    if remote == "remote" and len(regions) > 1 and not countries:
        # The board offers "Home Based - Americas; APAC; EMEA" but the body says
        # "Location: EMEA": the body is the narrower, later statement.
        for m in _BODY_LOCATION.finditer(text):
            body = parse_location(m.group(1))
            narrowed = [r for r in body.regions if r in regions]
            if narrowed and not body.countries and len(narrowed) < len(regions):
                regions = narrowed
                break
    if remote == "remote" and not countries:
        # "Remote" alone is ambiguous; postings usually say who can be hired.
        r_countries, r_regions = remote_scope(f"{title}\n{job.location_raw or ''}\n{text[:2500]}")
        countries += r_countries
        regions += [r for r in r_regions if r not in regions]
    if (
        remote == "remote"
        and loc.worldwide
        and not countries
        and not regions
        and "WW" not in countries
    ):
        countries.append("WW")
    countries += [f"R:{r}" for r in regions if f"R:{r}" not in countries]
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
