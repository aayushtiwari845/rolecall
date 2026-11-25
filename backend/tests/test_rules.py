import pytest

from app.enrich import rules
from app.enrich.locations import parse_location
from app.enrich.skills import extract_skills
from app.ingest.types import RawJob


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Software Engineer, Backend", True),
        ("Machine Learning Engineer Intern", True),
        ("Data Scientist II", True),
        ("Senior Account Executive", False),
        ("Technical Recruiter", False),
        ("Mechanical Engineer", False),
        ("Sales Engineer", False),
        ("Product Manager, AI", False),
        ("SRE - Platform", True),
        ("Data Entry Operator", False),
    ],
)
def test_tech_filter(title, expected):
    assert rules.looks_tech_title(title) is expected


@pytest.mark.parametrize(
    "title,family",
    [
        ("Backend Engineer (Go)", "backend"),
        ("Senior Frontend Engineer", "frontend"),
        ("Full Stack Developer", "fullstack"),
        ("AI Engineer - LLM Agents", "ai_llm"),
        ("Machine Learning Engineer, Ranking", "ml"),
        ("Data Engineer", "data_eng"),
        ("Data Scientist", "data_science"),
        ("Site Reliability Engineer", "infra"),
        ("Android Developer", "mobile"),
        ("Security Engineer", "security"),
        ("SDET", "qa"),
        ("Software Engineer", "swe"),
        ("Firmware Engineer", "embedded"),
    ],
)
def test_role_family(title, family):
    assert rules.role_family(title) == family


@pytest.mark.parametrize(
    "title,yoe,expected",
    [
        ("Software Engineering Intern, Summer 2027", None, "intern"),
        ("Software Engineer - New Grad (2026)", None, "new_grad"),
        ("SDE 1", None, "new_grad"),
        ("Junior Backend Developer", None, "junior"),
        ("Software Engineer II", None, "mid"),
        ("Senior Software Engineer", None, "senior"),
        ("Staff Engineer, Infrastructure", None, "staff_plus"),
        ("Engineering Manager", None, "staff_plus"),
        ("Backend Engineer", 0, "new_grad"),
        ("Backend Engineer", 3, "mid"),
        ("Backend Engineer", 8, "senior"),
    ],
)
def test_seniority(title, yoe, expected):
    assert rules.seniority(title, yoe, None) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("You have 3+ years of experience building APIs", (3, None)),
        ("Requires 2-4 years of professional experience", (2, 4)),
        ("minimum of 5 years of relevant industry experience", (5, None)),
        ("Experience: 1 to 3 years", (1, 3)),
        ("We are a company with a 100 year history", (None, None)),
        ("1+ years of experience with Python. 5+ years experience preferred", (1, None)),
    ],
)
def test_years_of_experience(text, expected):
    assert rules.years_of_experience(text) == expected


def test_salary_inr_lpa():
    lo, hi, cur, period = rules.salary("CTC: 12 - 18 LPA plus ESOPs")
    assert (lo, hi, cur, period) == (12e5, 18e5, "INR", "year")


def test_salary_inr_stipend():
    lo, hi, cur, period = rules.salary("Stipend: ₹40,000 - ₹60,000 per month")
    assert (lo, hi, cur, period) == (40000, 60000, "INR", "month")


def test_salary_usd_k():
    lo, hi, cur, period = rules.salary("The base pay range is $150k - $200k.")
    assert (lo, hi, cur, period) == (150000, 200000, "USD", "year")


def test_salary_ignores_small_numbers():
    assert rules.salary("We spend $5-10 on coffee")[0] is None


def test_annual_inr():
    assert rules.annual_inr(50000, "INR", "month") == 600000
    assert rules.annual_inr(100000, "USD", "year") == 8_500_000


def test_locations():
    loc = parse_location("Bangalore, India; Remote - India")
    assert loc.cities == ["Bengaluru"]
    assert loc.countries == ["IN"]
    assert loc.remote

    assert parse_location("San Francisco, CA").countries == ["US"]
    assert parse_location("Remote").worldwide
    assert parse_location("Remote (EMEA)").regions == ["EU"]
    assert parse_location("Indianapolis, IN").countries == ["US"]
    assert parse_location("Gurgaon").cities == ["Gurugram"]


def test_skills_disambiguation():
    skills = extract_skills(
        "Python, Go and PostgreSQL. The rest of the team will excel at node graphs."
    )
    assert skills == ["Python", "Go", "PostgreSQL"]
    assert "Java" not in extract_skills("JavaScript and TypeScript")
    assert extract_skills("C/C++ programming")[:2] == ["C", "C++"]


def test_enrich_end_to_end():
    job = RawJob(
        source_kind="greenhouse",
        source_job_id="x:1",
        company_name="Acme",
        title="Backend Engineer, New Grad",
        url="https://example.com/1",
        location_raw="Bengaluru, India (Hybrid)",
        description_text="We use Python, FastAPI, PostgreSQL and Kubernetes. 0-1 years of experience.",
    )
    e = rules.enrich(job)
    assert e.is_tech and e.role_family == "backend" and e.seniority == "new_grad"
    assert e.remote_type == "hybrid" and e.cities == ["Bengaluru"] and e.countries == ["IN"]
    assert {"Python", "FastAPI", "PostgreSQL", "Kubernetes"} <= set(e.skills)
    assert e.employment_type == "full_time"


def test_enrich_remote_worldwide_flag():
    job = RawJob(
        "remotive", "1", "Acme", "ML Engineer", "u", location_raw="Worldwide", remote_hint="remote"
    )
    e = rules.enrich(job)
    assert "WW" in e.countries and e.remote_type == "remote"


@pytest.mark.parametrize(
    "title,text,expected",
    [
        ("Simulation Engineer", "CAD, FEA and ANSYS for vehicle structures.", False),
        ("Hardware Engineer", "PCB layout and analog circuits.", False),
        (
            "Engineer, Payments",
            "We build services in Python and Go on AWS with PostgreSQL and Kafka.",
            True,
        ),
        ("Backend Developer", "", True),
    ],
)
def test_tech_role_needs_software_evidence_for_generic_titles(title, text, expected):
    from app.enrich.skills import extract_skills

    assert rules.is_tech_role(title, extract_skills(f"{title} {text}")) is expected


def test_language_filter():
    de = "Wir suchen für unser Team einen Entwickler (m/w/d) mit Erfahrung in Java und Python. Sie arbeiten mit der Cloud und die Kollegen."
    en = "You will join our team and work with Python. The role is for engineers with experience in cloud and data."
    assert not rules.is_english("Softwareentwickler (m/w/d)", de)
    assert rules.is_english("Software Engineer", en)
    assert not rules.is_english("Praktikum Softwareentwicklung", "")


def test_first_stated_years_requirement_wins():
    text = "5+ years of software engineering experience in Java. 2+ years of experience with React."
    assert rules.years_of_experience(text) == (5, None)


def test_presales_roles_are_not_tech():
    assert not rules.looks_tech_title("Solutions Engineer, Okta")
    assert not rules.looks_tech_title("Senior Solutions Architect")
    assert rules.looks_tech_title("Forward Deployed Engineer")
