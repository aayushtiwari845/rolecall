"""Skill taxonomy and extractor.

Canonical skill -> regex alternatives. Matching is word-boundary based and
case-insensitive, except for ambiguous short names (Go, R) which need context.
Shared by job enrichment and resume parsing so both sides speak the same vocabulary.
"""

from __future__ import annotations

import re
from functools import lru_cache

# (canonical, category, [patterns])
_TAXONOMY: list[tuple[str, str, list[str]]] = [
    # Languages
    ("Python", "language", [r"python"]),
    ("Java", "language", [r"java(?!\s*script)"]),
    ("JavaScript", "language", [r"javascript", r"\bjs\b(?!\s*on)", r"ecmascript", r"es6"]),
    ("TypeScript", "language", [r"typescript", r"\bts\b(?=\s*[,/)])"]),
    ("Go", "language", [r"golang", r"(?-i:\bGo\b)(?=\s*(?:[,/)]|and\b|or\b|developer|programming|language|lang\b|services|backend|microservices))"]),
    ("Rust", "language", [r"rust(?!\s*belt)"]),
    ("C++", "language", [r"c\+\+", r"\bcpp\b"]),
    ("C#", "language", [r"c#", r"\.net\b", r"dotnet", r"asp\.net"]),
    ("C", "language", [r"(?-i:\bC\b)(?=\s*(?:/C\+\+|,\s*C\+\+|and C\+\+|programming))"]),
    ("Kotlin", "language", [r"kotlin"]),
    ("Swift", "language", [r"(?-i:\bSwift\b)(?=\s*[,/).;]|\s+(?:and|or|programming|language|developer|code)\b|\s*$)"]),
    ("Scala", "language", [r"scala\b"]),
    ("Ruby", "language", [r"ruby"]),
    ("PHP", "language", [r"\bphp\b"]),
    ("R", "language", [r"(?-i:\bR\b)(?=\s*(?:[,/)]|and\b|programming|language|studio|shiny))"]),
    ("SQL", "language", [r"\bsql\b"]),
    ("Bash", "language", [r"\bbash\b", r"shell scripting"]),
    ("Elixir", "language", [r"elixir"]),
    ("Dart", "language", [r"\bdart\b"]),
    ("Solidity", "language", [r"solidity"]),
    # Backend
    ("Node.js", "backend", [r"node\.?js", r"\bnode\b(?=\s*(?:[,/)]|and\b|backend|services))"]),
    ("Express", "backend", [r"express\.?js", r"\bexpress\b(?=\s*[,/)])"]),
    ("NestJS", "backend", [r"nest\.?js"]),
    ("FastAPI", "backend", [r"fast\s?api"]),
    ("Django", "backend", [r"django"]),
    ("Flask", "backend", [r"flask"]),
    ("Spring Boot", "backend", [r"spring\s?boot", r"\bspring\b(?=\s*(?:framework|mvc|[,/)]))"]),
    ("Rails", "backend", [r"ruby on rails", r"\brails\b"]),
    ("GraphQL", "backend", [r"graphql"]),
    ("gRPC", "backend", [r"\bgrpc\b"]),
    ("REST APIs", "backend", [r"rest(?:ful)?\s*apis?", r"restful", r"api design"]),
    ("Microservices", "backend", [r"micro-?services?"]),
    ("Distributed Systems", "backend", [r"distributed systems?"]),
    ("System Design", "backend", [r"system design", r"systems design"]),
    # Frontend / mobile
    ("React", "frontend", [r"react(?:\.?js)?(?!\s*native)"]),
    ("Next.js", "frontend", [r"next\.?js"]),
    ("Vue", "frontend", [r"vue(?:\.?js)?"]),
    ("Angular", "frontend", [r"angular"]),
    ("Svelte", "frontend", [r"svelte"]),
    ("HTML/CSS", "frontend", [r"\bhtml5?\b", r"\bcss3?\b"]),
    ("Tailwind CSS", "frontend", [r"tailwind"]),
    ("Redux", "frontend", [r"redux"]),
    ("React Native", "mobile", [r"react\s?native"]),
    ("Flutter", "mobile", [r"flutter"]),
    ("Android", "mobile", [r"android"]),
    ("iOS", "mobile", [r"\bios\b"]),
    ("SwiftUI", "mobile", [r"swiftui"]),
    # Data stores
    ("PostgreSQL", "database", [r"postgres(?:ql)?", r"\bpsql\b"]),
    ("MySQL", "database", [r"mysql"]),
    ("MongoDB", "database", [r"mongo(?:db)?"]),
    ("Redis", "database", [r"redis"]),
    ("Elasticsearch", "database", [r"elastic\s?search", r"opensearch"]),
    ("Cassandra", "database", [r"cassandra"]),
    ("DynamoDB", "database", [r"dynamo\s?db"]),
    ("SQLite", "database", [r"sqlite"]),
    ("ClickHouse", "database", [r"clickhouse"]),
    ("Snowflake", "database", [r"snowflake"]),
    ("BigQuery", "database", [r"big\s?query"]),
    ("Redshift", "database", [r"redshift"]),
    ("Vector Databases", "database", [r"vector (?:database|db|store)s?", r"pgvector", r"pinecone", r"weaviate", r"qdrant", r"milvus", r"chroma\s?db"]),
    # Data engineering
    ("Apache Spark", "data", [r"spark", r"pyspark"]),
    ("Kafka", "data", [r"kafka"]),
    ("Airflow", "data", [r"airflow"]),
    ("dbt", "data", [r"\bdbt\b"]),
    ("Hadoop", "data", [r"hadoop", r"\bhive\b"]),
    ("Flink", "data", [r"\bflink\b"]),
    ("ETL", "data", [r"\betl\b", r"\belt\b", r"data pipelines?"]),
    ("Data Warehousing", "data", [r"data warehous\w*", r"data lake\w*", r"lakehouse"]),
    ("Pandas", "data", [r"pandas"]),
    ("NumPy", "data", [r"numpy"]),
    ("Tableau", "data", [r"tableau"]),
    ("Power BI", "data", [r"power\s?bi"]),
    ("Excel", "data", [r"(?:microsoft|ms)\s+excel", r"excel(?=\s*(?:[,/)]|spreadsheets?|sheets))"]),
    ("Statistics", "data", [r"statistic(?:s|al)", r"a/b test\w*", r"hypothesis test\w*"]),
    # ML / AI
    ("Machine Learning", "ml", [r"machine learning", r"\bml\b"]),
    ("Deep Learning", "ml", [r"deep learning", r"neural networks?"]),
    ("PyTorch", "ml", [r"pytorch", r"\btorch\b"]),
    ("TensorFlow", "ml", [r"tensorflow", r"\bkeras\b"]),
    ("JAX", "ml", [r"\bjax\b"]),
    ("scikit-learn", "ml", [r"scikit[- ]learn", r"sklearn"]),
    ("XGBoost", "ml", [r"xgboost", r"lightgbm", r"catboost"]),
    ("NLP", "ml", [r"\bnlp\b", r"natural language processing"]),
    ("Computer Vision", "ml", [r"computer vision", r"\bopencv\b", r"image (?:recognition|segmentation)"]),
    ("Recommender Systems", "ml", [r"recommend(?:er|ation) (?:systems?|engines?)", r"personali[sz]ation", r"ranking systems?"]),
    ("Search / Information Retrieval", "ml", [r"information retrieval", r"semantic search", r"search (?:ranking|relevance|infrastructure)", r"\bbm25\b"]),
    ("LLMs", "ai", [r"\bllms?\b", r"large language models?", r"gpt-?\d?", r"generative ai", r"\bgenai\b", r"foundation models?"]),
    ("RAG", "ai", [r"\brag\b", r"retrieval[- ]augmented"]),
    ("Embeddings", "ai", [r"embeddings?"]),
    ("Prompt Engineering", "ai", [r"prompt(?:ing| engineering)"]),
    ("AI Agents", "ai", [r"\bai agents?\b", r"agentic", r"tool[- ]use", r"function calling", r"langgraph", r"multi-agent"]),
    ("LangChain", "ai", [r"langchain", r"llama\s?index"]),
    ("Hugging Face", "ai", [r"hugging\s?face", r"transformers library"]),
    ("Fine-tuning", "ai", [r"fine[- ]tun\w+", r"\blora\b", r"\brlhf\b"]),
    ("LLM Evals", "ai", [r"\bevals?\b", r"llm evaluation", r"evaluation (?:harness|framework)s?"]),
    ("MLOps", "ml", [r"mlops", r"mlflow", r"kubeflow", r"model serving", r"sagemaker", r"vertex ai"]),
    # Infra / cloud
    ("AWS", "cloud", [r"\baws\b", r"amazon web services", r"\bec2\b", r"\bs3\b", r"\blambda\b"]),
    ("GCP", "cloud", [r"\bgcp\b", r"google cloud"]),
    ("Azure", "cloud", [r"\bazure\b"]),
    ("Docker", "infra", [r"docker", r"containeri[sz]\w+"]),
    ("Kubernetes", "infra", [r"kubernetes", r"\bk8s\b", r"\beks\b", r"\bgke\b", r"\bhelm\b"]),
    ("Terraform", "infra", [r"terraform", r"infrastructure as code", r"\biac\b", r"pulumi"]),
    ("CI/CD", "infra", [r"ci\s?/\s?cd", r"continuous (?:integration|delivery|deployment)", r"github actions", r"jenkins", r"gitlab ci"]),
    ("Linux", "infra", [r"linux", r"unix"]),
    ("Observability", "infra", [r"prometheus", r"grafana", r"observability", r"opentelemetry", r"datadog", r"\belk\b"]),
    ("Networking", "infra", [r"tcp/ip", r"networking", r"\bdns\b", r"load balanc\w+"]),
    ("Git", "tools", [r"\bgit\b", r"github", r"gitlab"]),
    # Practices / CS
    ("Testing", "practice", [r"unit test\w*", r"integration test\w*", r"\btdd\b", r"pytest", r"jest", r"junit", r"test automation"]),
    ("Selenium", "practice", [r"selenium", r"playwright", r"cypress"]),
    ("Data Structures & Algorithms", "cs", [r"data structures", r"algorithms", r"\bdsa\b"]),
    ("OOP", "cs", [r"object[- ]oriented", r"\boop\b"]),
    ("Concurrency", "cs", [r"concurren\w+", r"multi-?thread\w*", r"asyncio"]),
    ("Security", "security", [r"owasp", r"application security", r"penetration testing", r"threat model\w*", r"cryptograph\w*"]),
    ("OAuth / Auth", "security", [r"oauth\s?2?", r"\bjwt\b", r"\bsso\b", r"\brbac\b", r"authentication"]),
    ("Embedded C", "embedded", [r"embedded c", r"rtos", r"microcontrollers?", r"firmware"]),
    ("Blockchain", "web3", [r"blockchain", r"web3", r"smart contracts?", r"ethereum"]),
]

CATEGORIES: dict[str, str] = {name: cat for name, cat, _ in _TAXONOMY}
ALL_SKILLS: list[str] = [name for name, _, _ in _TAXONOMY]

# Skills too generic to count much as evidence of fit
WEAK_SKILLS = {"Git", "Excel", "Linux", "REST APIs", "SQL", "Data Structures & Algorithms", "OOP", "HTML/CSS"}


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for name, _cat, patterns in _TAXONOMY:
        alt = "|".join(f"(?:{p})" for p in patterns)
        out.append((name, re.compile(rf"(?<![\w.+#-])(?:{alt})(?![\w+#])", re.I)))
    return out


def extract_skills(text: str) -> list[str]:
    """Return canonical skills mentioned in ``text``, ordered by first mention."""
    if not text:
        return []
    hits: list[tuple[int, str]] = []
    for name, pat in _compiled():
        m = pat.search(text)
        if m:
            hits.append((m.start(), name))
    hits.sort()
    return [name for _, name in hits]


def canonicalize(skill: str) -> str | None:
    """Map a free-form skill (e.g. from an LLM) onto the taxonomy, if possible."""
    s = skill.strip()
    for name in ALL_SKILLS:
        if name.lower() == s.lower():
            return name
    found = extract_skills(s)
    return found[0] if found else None
