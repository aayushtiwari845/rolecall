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
        ("Site Reliability Engineer- II", None, "mid"),
        ("Applied Scientist II - Recommendation", 2, "mid"),
        ("Software Engineer-I", None, "new_grad"),
        ("Associate SDE", None, "new_grad"),
        ("Software Engineer Ⅰ", None, "new_grad"),
        ("Medior Fullstack Developer", 1, "mid"),
        ("DevOps Team Leader", 2, "senior"),
        ("SAP Business Data Cloud Architect with AI", 1, "senior"),
        ("Software_Architect_EBH", None, "senior"),
        ("IN_RBAI_Software Automation expert_IN", 1, "senior"),
        ("Embedded Test Engineer (1-year contract)", None, None),
    ],
)
def test_seniority(title, yoe, expected):
    assert rules.seniority(title, yoe, None) == expected


@pytest.mark.parametrize(
    "text,yoe,expected",
    [
        ("Experience level: Executive\nDesign SAP architectures.", None, "senior"),
        ("Experience level: Director", 3, "staff_plus"),
        # The board says experienced hire; a narrow skill ask does not make it new-grad.
        ("Experience level: Mid-Senior level\n1+ years of SQL experience", 1, "mid"),
        ("Experience level: Mid-Senior level", 8, "senior"),
        ("Experience level: Entry level", None, "new_grad"),
        ("Experience level: Entry level", 3, "mid"),
        ("Experience level: Associate", None, None),
    ],
)
def test_board_level_field(text, yoe, expected):
    assert rules.seniority("Data Engineer", yoe, None, text) == expected


def test_board_level_field_does_not_override_the_title():
    text = "Experience level: Mid-Senior level"
    assert rules.seniority("Junior Backend Developer", None, None, text) == "junior"


def test_overall_experience_beats_a_narrower_skill_ask():
    text = (
        "SAP HANA Cloud Mandatory Min 2 yrs. of hands on Exp in this skill\n"
        "SAP AI Preferred Min 1-2 yrs. of hands on Exp in this skill\n"
        "Experience : Overall, 10-14 years of experience in implementation of SAP Analytics."
    )
    assert rules.years_of_experience(text) == (10, 14)


def test_fractional_years():
    assert rules.years_of_experience("1.5 to 3 years of hands-on experience in Data") == (1.5, 3)


def test_title_states_the_experience():
    job = RawJob(
        source_kind="workday",
        source_job_id="1",
        company_name="Bosch",
        title="Software_Architect_EBH_10+Years",
        url="https://example.com/1",
        description_text="Design embedded software for braking systems. " * 5,
    )
    e = rules.enrich(job)
    assert e.min_yoe == 10 and e.seniority == "senior"


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
        description_text="We use Python, FastAPI, PostgreSQL and Kubernetes. 0-1 years of experience. "
        "You will build and run the services behind our payments product with a small, friendly team.",
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


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Great team. #LI-Hybrid #LI-SM4", "hybrid"),
        (
            "Roles that are based in an office are onsite Tuesday, Wednesday, and Thursday.",
            "hybrid",
        ),
        ("We use a hybrid work model of 3 days in the office per week.", "hybrid"),
        ("This is a hybrid role at the intersection of engineering and data science.", "onsite"),
        ("Benefits for remote employees. #LI-Remote", "remote"),
        ("#LI-onsite", "onsite"),
    ],
)
def test_work_mode_from_text(text, expected):
    assert rules.remote_type(None, "Bengaluru", "Engineer", text) == expected


@pytest.mark.parametrize(
    "text,countries,regions",
    [
        ("Acme | Engineer | REMOTE (US Citizenship Required) | Full-time", ["US"], []),
        ("REMOTE (EEA) | Full-time", [], ["EU"]),
        ("Database Support Engineer (AMER)", ["US"], []),
        ("We are a remote-first team. You must be located in the US.", ["US"], []),
        ("Remote (APAC)", [], ["APAC"]),
        ("Fully remote, hire anywhere in the world", [], []),
        ("Tell us about yourself", [], []),
    ],
)
def test_remote_scope(text, countries, regions):
    assert rules.remote_scope(text) == (countries, regions)


def test_candidate_posts_are_not_jobs():
    assert rules.is_candidate_post("I'm a software engineer focused on backend development")
    assert not rules.is_candidate_post("We are hiring a software engineer to join us")


def test_junk_postings_are_dropped():
    raw = RawJob(
        "greenhouse",
        "1",
        "Acme",
        "Software Engineer, Backend",
        "u",
        description_text="Blah Blah Blah. Qualifications Blah Blah Blah " * 5,
    )
    assert not rules.enrich(raw).is_tech
    assert not rules.looks_tech_title("Hydraulics Component Design Engineer, Mobile Control valve")
    assert not rules.looks_tech_title("Content Developer")
    assert not rules.looks_tech_title("Developer Engagement Representative - LATAM")
    assert not rules.looks_tech_title("QA Tester (Remote): Test Real Apps, Flexible Hours")
    assert not rules.looks_tech_title("Developer Engagement Team (Contract)")
    assert not rules.looks_tech_title("Specialist Seller, Enterprise Core (AI Products)")
    assert not rules.looks_tech_title("2026/02: HW Developer for Electronic Control Unit")
    not_a_job = RawJob(
        "hn",
        "2",
        "Sparcle",
        "Software Engineer",
        "u",
        description_text="Remote | Equity, full-time, part-time, fractional, project, "
        "partnership or revenue share. We build an AI workspace in Python. " * 3,
    )
    assert not rules.enrich(not_a_job).is_tech


@pytest.mark.parametrize(
    "raw,country",
    [
        ("Remote US", "US"),
        ("US - Remote", "US"),
        ("US-TX-Remote", "US"),
        ("US Based Candidates Only", "US"),
        ("Remote - California", "US"),
        ("Remote - Washington D.C.", "US"),
        ("Ontario - Remote", "CA"),
        ("Remote, KSA", "SA"),
        ("Argentina", "AR"),
        ("Remote Finland", "FI"),
        ("NZ-New Zealand-Remote", "NZ"),
        ("Remote - Estonia", "EE"),
        ("Taiwan (Remote)", "TW"),
    ],
)
def test_remote_locations_name_their_country(raw, country):
    assert country in parse_location(raw).countries


def test_us_word_is_not_a_country():
    assert parse_location("Remote, join us").countries == []
    assert parse_location("Remote-NAMER").regions == ["AMER"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Requirements: Experience: 6+ years in software engineering", (6, None)),
        ("Typical experience level: 6-8 yrs Mandatory Skills", (6, 8)),
        ("You have 7+ years in technical support or databases", (7, None)),
        ("4 years’ minimum Python experience in finance", (4, None)),
        ("Experience : 18+ years Mandatory skills", (18, None)),
        ("5+ years building and operating backend services", (5, None)),
        ("Tech CSE with 4+ yrs. Solid understanding of design", (4, None)),
        ("Minimum 8-year experience working as a support engineer", (8, None)),
        ("Experience as an on call SRE (at least 8 years)", (8, None)),
        ("Experience level: Associate. Tasks: CI/CD pipelines. 3 to 6 years", (3, 6)),
        ("Founded 10+ years ago, we build payments", (None, None)),
        ("Our 2-3 year roadmap is ambitious", (None, None)),
    ],
)
def test_years_of_experience_phrasings(text, expected):
    assert rules.years_of_experience(text) == expected


def test_unpaid_posts_are_not_jobs():
    assert rules._NOT_A_JOB.search("This is an unpaid role for now")


@pytest.mark.parametrize(
    "text",
    [
        "We have a 25+ year track record of innovation and profitability.",
        "Help evolve it for the next 2+ years of growth.",
    ],
)
def test_company_boilerplate_is_not_an_experience_requirement(text):
    assert rules.years_of_experience(text) == (None, None)


def test_a_bare_years_line_is_the_experience_field():
    text = "Expected skill set: Linux internals, C.\n\nAdditional Information\n5 to 8 years\n"
    assert rules.years_of_experience(text) == (5, 8)


def _remote_job(location_raw, body):
    return RawJob(
        source_kind="greenhouse",
        source_job_id="1",
        company_name="Canonical",
        title="Software Engineer - Python - Container Images",
        url="https://example.com/1",
        remote_hint="remote",
        location_raw=location_raw,
        description_text="Build and maintain container images with Python. " * 5 + body,
    )


def test_body_location_narrows_a_multi_region_board_listing():
    raw = "Home Based - Americas; Home Based - APAC; Home based - EMEA"
    assert rules.enrich(_remote_job(raw, "\n**Location**: EMEA\n")).countries == ["R:EU"]
    # Without a narrower line the board's list stands.
    assert set(rules.enrich(_remote_job(raw, "")).countries) == {"R:EU", "R:AMER", "R:APAC"}


@pytest.mark.parametrize("title", ["engineering, GTM, product, sales", "Multiple roles"])
def test_hiring_thread_department_lists_are_not_roles(title):
    job = RawJob(
        source_kind="hn",
        source_job_id="1",
        company_name="Rootly",
        title=title,
        url="https://example.com/1",
        description_text=f"Rootly | {title} | Remote\nOn-call and incident response. " * 4,
    )
    assert not rules.enrich(job).is_tech


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer, 2031 Start",
        "SDE - 2026 Batch",
        "Backend Developer (2027 passouts)",
        "Graduate Engineer - Class of 2034",
    ],
)
def test_cohort_years_are_new_grad_in_any_year(title):
    assert rules.seniority(title, None, None) == "new_grad"
