"""Places named in a search query become a location filter."""

import pytest

from app.search.engine import query_location
from app.search.filters import JobFilters


@pytest.mark.parametrize(
    "query,expected",
    [
        ("RAG intern Bengaluru", {"cities": ["Bengaluru"], "remote_india": True}),
        ("data analyst Pune or Chennai", {"cities": ["Pune", "Chennai"], "remote_india": True}),
        ("backend roles in india", {"countries": ["IN"]}),
        ("remote ml engineer", {"remote_india": True, "remote_global": True}),
    ],
)
def test_query_places_become_filters(query, expected):
    f = query_location(query, JobFilters())
    assert f is not None
    got = {k: v for k, v in f.model_dump().items() if k in expected}
    assert got == expected


@pytest.mark.parametrize("query", ["distributed systems engineer", "go developer", "sre kubernetes"])
def test_queries_without_places_are_untouched(query):
    assert query_location(query, JobFilters()) is None


def test_explicit_location_filters_win():
    chosen = JobFilters(cities=["Hyderabad"])
    assert query_location("ml intern Bengaluru", chosen) is None
