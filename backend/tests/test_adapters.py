"""Adapter parsing tests against trimmed real-shaped payloads."""

import asyncio

import httpx

from app.ingest.http import PoliteClient
from app.ingest.sources import aggregators, ashby, greenhouse, hn, jsonld, lever, recruitee, workable


def test_greenhouse_parse():
    payload = {
        "jobs": [
            {
                "id": 123,
                "title": "Software Engineer, New Grad",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                "location": {"name": "Bengaluru, India"},
                "updated_at": "2026-11-01T10:00:00-04:00",
                "content": "&lt;p&gt;Build &lt;strong&gt;APIs&lt;/strong&gt; in Python&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Go&lt;/li&gt;&lt;/ul&gt;",
                "departments": [{"name": "Engineering"}],
            }
        ]
    }
    [job] = greenhouse.parse(payload, "acme", "Acme")
    assert job.source_job_id == "acme:123"
    assert job.company_name == "Acme"
    assert "Build APIs in Python" in job.description_text
    assert "• Go" in job.description_text
    assert job.location_raw == "Bengaluru, India"
    assert job.posted_at.year == 2026


def test_lever_parse():
    payload = [
        {
            "id": "abc",
            "text": "Backend Intern",
            "hostedUrl": "https://jobs.lever.co/acme/abc",
            "applyUrl": "https://jobs.lever.co/acme/abc/apply",
            "categories": {"location": "Mumbai", "commitment": "Internship", "team": "Eng"},
            "createdAt": 1764000000000,
            "descriptionPlain": "Join us.",
            "lists": [{"text": "Requirements", "content": "<li>Python</li><li>SQL</li>"}],
            "workplaceType": "hybrid",
            "salaryRange": {"min": 50000, "max": 70000, "currency": "INR", "interval": "per-month-salary"},
        }
    ]
    [job] = lever.parse(payload, "acme", "Acme")
    assert job.employment_hint == "intern"
    assert job.remote_hint == "hybrid"
    assert job.salary_period == "month" and job.salary_currency == "INR"
    assert "Requirements" in job.description_text and "• Python" in job.description_text


def test_ashby_parse_skips_unlisted():
    payload = {
        "jobs": [
            {"id": "1", "title": "AI Engineer", "isListed": True, "location": "Remote", "isRemote": True,
             "employmentType": "FullTime", "descriptionPlain": "LLMs", "jobUrl": "https://jobs.ashbyhq.com/acme/1",
             "compensation": {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR",
                                                     "currencyCode": "USD", "minValue": 1, "maxValue": 2}]}},
            {"id": "2", "title": "Hidden", "isListed": False},
        ]
    }
    jobs = ashby.parse(payload, "acme", None)
    assert [j.title for j in jobs] == ["AI Engineer"]
    assert jobs[0].remote_hint == "remote" and jobs[0].salary_currency == "USD"


def test_workable_and_recruitee_parse():
    wk = workable.parse(
        {"name": "Acme", "jobs": [{"title": "Data Engineer", "shortcode": "XYZ", "telecommuting": True,
                                     "employment_type": "Full-time", "city": "Pune", "country": "India",
                                     "description": "<p>Spark</p>"}]},
        "acme", None,
    )
    assert wk[0].remote_hint == "remote" and wk[0].location_raw == "Pune, India"
    rc = recruitee.parse(
        {"offers": [{"id": 9, "title": "QA Engineer", "description": "<p>a</p>", "requirements": "<p>b</p>",
                     "location": "Berlin", "remote": False, "employment_type_code": "fulltime"}]},
        "acme", "Acme",
    )
    assert rc[0].employment_hint == "full_time"


def test_hn_header_parsing():
    company, title, loc, remote = hn.parse_header("Acme AI | Senior Backend Engineer | Bangalore, India | REMOTE (India) | https://acme.ai")
    assert company == "Acme AI"
    assert title == "Senior Backend Engineer"
    assert "Bangalore" in loc
    assert remote == "remote"


def test_remoteok_skips_legal_notice():
    jobs = aggregators.parse_remoteok([{"legal": "..."}, {"id": 1, "position": "SRE", "company": "X"}])
    assert len(jobs) == 1 and jobs[0].remote_hint == "remote"


JSONLD_PAGE = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"JobPosting","title":"ML Engineer",
"description":"&lt;p&gt;PyTorch&lt;/p&gt;","datePosted":"2026-11-02",
"hiringOrganization":{"@type":"Organization","name":"Acme"},
"jobLocation":{"@type":"Place","address":{"addressLocality":"Mumbai","addressCountry":"IN"}},
"employmentType":"FULL_TIME","identifier":{"value":"ml-1"},
"baseSalary":{"currency":"INR","value":{"minValue":1500000,"maxValue":2500000,"unitText":"YEAR"}}}]}
</script></head><body>
<a href="/careers/jobs/ml-1">ML</a><a href="/about">About</a><a href="https://other.com/jobs/x">x</a>
</body></html>
"""


def test_jsonld_parse_and_links():
    [job] = jsonld.parse_page(JSONLD_PAGE, "https://acme.com/careers", None)
    assert job.company_name == "Acme" and job.source_job_id == "ml-1"
    assert job.location_raw == "Mumbai, IN" and job.salary_period == "year"
    assert job.description_text == "PyTorch"
    assert jsonld.job_links(JSONLD_PAGE, "https://acme.com/careers") == ["https://acme.com/careers/jobs/ml-1"]


def test_detect_ats():
    html = '<a href="https://boards.greenhouse.io/acme/jobs/1">x</a><iframe src="https://jobs.lever.co/acme-inc"></iframe>'
    assert jsonld.detect_ats(html) == [("greenhouse", "acme"), ("lever", "acme-inc")]


def test_polite_client_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    async def run():
        client = PoliteClient(per_host_delay=0, transport=httpx.MockTransport(handler))
        client._backoff = lambda attempt: 0  # type: ignore[method-assign]
        try:
            return await client.get_json("https://example.com/x")
        finally:
            await client.aclose()

    assert asyncio.run(run()) == {"ok": True}
    assert calls["n"] == 3


def test_polite_client_respects_robots():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(200, text="ok")

    async def run():
        client = PoliteClient(per_host_delay=0, transport=httpx.MockTransport(handler))
        try:
            return await client.allowed("https://example.com/private/x"), await client.allowed("https://example.com/jobs")
        finally:
            await client.aclose()

    assert asyncio.run(run()) == (False, True)
