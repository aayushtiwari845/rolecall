"""Resume -> profile.

1. Extract text from the PDF (the file itself is never stored).
2. Redact contact details (emails, phone numbers) before anything is persisted.
3. Rules: skills from the shared taxonomy, education end year, work experience
   (date ranges outside the education section, internships counted separately),
   and suggested role families / levels.
4. Optionally an LLM pass for a headline, summary and better role suggestions.
"""

from __future__ import annotations

import io
import logging
import re
from collections import Counter
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.enrich.rules import role_family
from app.enrich.skills import CATEGORIES, canonicalize, rank_skills
from app.llm.router import LLMError, LLMRouter

log = logging.getLogger(__name__)

MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_RANGE = re.compile(
    rf"(?:{_MONTH}\s*)?((?:19|20)\d\d)\s*(?:-|–|—|to)\s*(?:(present|current|now|ongoing)|(?:{_MONTH}\s*)?((?:19|20)\d\d))",
    re.I,
)
_EDU = re.compile(
    r"b\.?\s?tech|b\.?e\.?\b|bachelor|master|m\.?tech|m\.?s\.?\b|university|college|school|cgpa|gpa|degree|expected|diploma|ph\.?d",
    re.I,
)
_INTERN = re.compile(r"\bintern(ship)?\b|trainee", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,16}\d")
_TITLE_LINE = re.compile(
    r"(engineer|developer|intern|scientist|analyst|architect|lead|manager|researcher|consultant)",
    re.I,
)


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    pages = [p.extract_text() or "" for p in reader.pages[:6]]
    return "\n".join(pages).replace(" ", " ").strip()


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    return _PHONE.sub(
        lambda m: "[phone]" if sum(c.isdigit() for c in m.group()) >= 9 else m.group(), text
    )


def _month(tok: str | None, default: int) -> int:
    return MONTHS.get((tok or "")[:3].lower(), default)


def experience_ranges(text: str) -> list[tuple[date, date, bool]]:
    """(start, end, is_internship) for every non-education date range."""
    lines = text.splitlines()
    out = []
    today = datetime.now(UTC).date()
    for i, line in enumerate(lines):
        for m in _RANGE.finditer(line):
            context = " ".join(lines[max(0, i - 2) : i + 2])
            if _EDU.search(line) or (_EDU.search(context) and not _TITLE_LINE.search(context)):
                continue
            start = date(int(m.group(2)), _month(m.group(1), 1), 1)
            end = today if m.group(3) else date(int(m.group(5)), _month(m.group(4), 12), 28)
            if end < start or start > today:
                continue
            end = min(end, today)
            out.append((start, end, bool(_INTERN.search(context))))
    return out


def _merged_years(ranges: list[tuple[date, date]]) -> float:
    if not ranges:
        return 0.0
    ranges = sorted(ranges)
    total, (cs, ce) = 0, ranges[0]
    for s, e in ranges[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            total += (ce - cs).days
            cs, ce = s, e
    total += (ce - cs).days
    return round(total / 365.25, 1)


def graduation_year(text: str) -> int | None:
    years = []
    for line in text.splitlines():
        if _EDU.search(line):
            for m in _RANGE.finditer(line):
                if m.group(5):
                    years.append(int(m.group(5)))
            for y in re.findall(
                r"(?:expected|class of|graduat\w*)\D{0,20}((?:19|20)\d\d)", line, re.I
            ):
                years.append(int(y))
    return max(years) if years else None


_FAMILY_FROM_CATEGORY = {
    "ml": "ml",
    "ai": "ai_llm",
    "data": "data_eng",
    "backend": "backend",
    "frontend": "frontend",
    "mobile": "mobile",
    "infra": "infra",
    "cloud": "infra",
    "security": "security",
    "embedded": "embedded",
}


def suggest_families(skills: list[str], titles: list[str]) -> list[str]:
    scores: Counter[str] = Counter()
    for s in skills:
        fam = _FAMILY_FROM_CATEGORY.get(CATEGORIES.get(s, ""))
        if fam:
            scores[fam] += 1
    for t in titles:
        scores[role_family(t)] += 2
    if scores["backend"] and scores["frontend"]:
        scores["fullstack"] += min(scores["backend"], scores["frontend"])
    if scores["ml"] or scores["ai_llm"]:
        scores["data_science"] += 1
    scores["swe"] += 2  # generalist SWE roles fit almost every engineering profile
    return [f for f, _ in scores.most_common(5) if f != "other"]


def suggest_levels(years_fulltime: float, grad_year: int | None) -> list[str]:
    this_year = datetime.now(UTC).year
    if grad_year and grad_year >= this_year:
        levels = ["intern", "new_grad"]
    elif years_fulltime < 1:
        levels = ["new_grad", "junior"]
    elif years_fulltime < 3:
        levels = ["junior", "mid"]
    elif years_fulltime < 6:
        levels = ["mid", "senior"]
    else:
        levels = ["senior", "staff_plus"]
    return levels


class LLMProfile(BaseModel):
    headline: str = Field(description="e.g. 'Final-year AI/DS student, backend + ML internships'")
    summary: str = Field(description="2-3 sentences on strengths, written for a recruiter")
    target_titles: list[str] = Field(
        default_factory=list, description="5 job titles this person should apply for"
    )
    top_skills: list[str] = Field(
        default_factory=list, description="Up to 15 strongest technical skills"
    )


def parse_resume(text: str, llm: LLMRouter | None = None) -> dict:
    text = redact(text)
    skills = rank_skills(text)
    ranges = experience_ranges(text)
    fulltime = _merged_years([(s, e) for s, e, intern in ranges if not intern])
    intern_years = _merged_years([(s, e) for s, e, intern in ranges if intern])
    grad = graduation_year(text)
    titles = [ln.strip() for ln in text.splitlines() if _TITLE_LINE.search(ln) and len(ln) < 80][
        :12
    ]
    profile = {
        "headline": None,
        "summary": None,
        "skills": skills,
        "years_experience": fulltime,
        "internship_years": intern_years,
        "graduation_year": grad,
        "is_student": bool(grad and grad >= datetime.now(UTC).year),
        "titles": titles,
        "suggested_role_families": suggest_families(skills, titles),
        "suggested_seniorities": suggest_levels(fulltime, grad),
        "target_titles": [],
        "parsed_by": "rules",
    }
    if llm is not None and llm.available:
        try:
            p = llm.structured(
                [
                    {
                        "role": "user",
                        "content": "Build a job-search profile from this resume:\n\n" + text[:7000],
                    }
                ],
                LLMProfile,
                tier="smart",
                purpose="resume",
            )
            profile.update(
                headline=p.headline, summary=p.summary, target_titles=p.target_titles[:6]
            )
            extra = [canonicalize(s) for s in p.top_skills]
            profile["skills"] = list(dict.fromkeys([*skills, *(s for s in extra if s)]))
            profile["parsed_by"] = "rules+llm"
        except (LLMError, ValueError):
            log.warning("LLM resume pass failed; using rules only", exc_info=True)
    if not profile["headline"]:
        fam = profile["suggested_role_families"][0] if profile["suggested_role_families"] else "swe"
        who = "Student" if profile["is_student"] else f"{fulltime:g} yrs experience"
        profile["headline"] = f"{who} · {fam.replace('_', '/')} · {', '.join(skills[:4])}"
    return profile


def profile_text(profile: dict, raw_text: str) -> str:
    """Text used to embed a resume for retrieval."""
    parts = [
        profile.get("headline") or "",
        profile.get("summary") or "",
        "Target roles: "
        + ", ".join(profile.get("target_titles") or profile.get("suggested_role_families") or []),
        "Skills: " + ", ".join((profile.get("skills") or [])[:30]),
        raw_text[:1500],
    ]
    return "\n".join(p for p in parts if p.strip())
