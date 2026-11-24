"""Hard filters shared by search, feed, alerts and the agent's tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, and_, false, or_, select, true

from app.enrich.rules import FX_TO_INR
from app.models import Company, Job

PERIOD_MULT = {"year": 1, "month": 12, "hour": 2000}


class JobFilters(BaseModel):
    seniorities: list[str] = Field(default_factory=list)
    include_unknown_level: bool = True  # postings that never state a level
    role_families: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    remote_india: bool = False
    remote_global: bool = False
    onsite_anywhere: bool = False
    countries: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    exclude_companies: list[str] = Field(default_factory=list)
    company_tags: list[str] = Field(default_factory=list)
    posted_within_days: int | None = None
    min_salary_inr: float | None = None
    salary_disclosed: bool = False
    skills: list[str] = Field(default_factory=list)

    def is_location_free(self) -> bool:
        return not (self.cities or self.remote_india or self.remote_global or self.countries) or self.onsite_anywhere


def _remote_ok_global() -> ColumnElement[bool]:
    # Remote roles not restricted to some other country: worldwide, unspecified, India or APAC.
    return or_(
        Job.countries.any("WW"), Job.countries.any("IN"), Job.countries.any("R:APAC"),
        Job.countries == [],  # type: ignore[comparison-overlap]
    )


def location_clause(f: JobFilters) -> ColumnElement[bool]:
    if f.is_location_free():
        return true()
    parts = []
    if f.cities:
        parts.append(and_(Job.cities.overlap(f.cities), Job.remote_type != "remote"))
        parts.append(and_(Job.cities.overlap(f.cities), Job.remote_type == "remote"))
    if f.countries:
        parts.append(Job.countries.overlap([c.upper() for c in f.countries]))
    if f.remote_india:
        parts.append(and_(Job.remote_type == "remote", Job.countries.any("IN")))
    if f.remote_global:
        parts.append(and_(Job.remote_type == "remote", _remote_ok_global()))
    return or_(*parts) if parts else false()


def salary_clause(min_inr: float) -> ColumnElement[bool]:
    """Annualised INR pay >= min (using the top of the range); unknown pay passes."""
    conds = []
    for cur, rate in FX_TO_INR.items():
        for period, mult in PERIOD_MULT.items():
            conds.append(and_(
                Job.salary_currency == cur,
                Job.salary_period == period,
                func_coalesce(Job.salary_max, Job.salary_min) * rate * mult >= min_inr,
            ))
    return or_(Job.salary_min.is_(None) & Job.salary_max.is_(None), *conds)


def func_coalesce(a, b):
    from sqlalchemy import func

    return func.coalesce(a, b)


def build_where(f: JobFilters, exclude_ids: list | None = None) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = [
        Job.status == "open",
        Job.is_tech.is_(True),
        Job.duplicate_of.is_(None),
    ]
    if f.seniorities:
        level = Job.seniority.in_(f.seniorities)
        where.append(or_(level, Job.seniority.is_(None)) if f.include_unknown_level else level)
    if f.role_families:
        where.append(Job.role_family.in_(f.role_families))
    if f.employment_types:
        where.append(Job.employment_type.in_(f.employment_types))
    where.append(location_clause(f))
    if f.companies:
        where.append(Job.company_name.in_(f.companies))
    if f.exclude_companies:
        where.append(Job.company_name.not_in(f.exclude_companies))
    if f.company_tags:
        where.append(Job.company_id.in_(select(Company.id).where(Company.tags.overlap(f.company_tags))))
    if f.posted_within_days:
        where.append(Job.posted_at >= datetime.now(UTC) - timedelta(days=f.posted_within_days))
    if f.min_salary_inr:
        where.append(salary_clause(f.min_salary_inr))
    if f.salary_disclosed:
        where.append(or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None)))
    if f.skills:
        where.append(Job.skills.overlap(f.skills))
    if exclude_ids:
        where.append(Job.id.not_in(exclude_ids))
    return where
