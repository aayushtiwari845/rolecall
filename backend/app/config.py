"""Application settings, loaded from environment variables (and a local .env file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://rolecall:rolecall@localhost:5433/rolecall"

    # Public URLs
    web_url: str = "http://localhost:3000"
    api_public_url: str = "http://localhost:3000/api"

    # Auth
    jwt_secret: str = "dev-only-secret-change-me-in-production-please"
    jwt_ttl_days: int = 30
    session_cookie: str = "rolecall_session"
    google_client_id: str = ""
    google_client_secret: str = ""
    admin_emails: list[str] = Field(default_factory=list)

    # Embeddings / reranking (run locally on CPU through ONNX)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_enabled: bool = True
    model_cache_dir: str = "../data/cache/models"

    # LLM providers (all have free tiers or run locally). Order = fallback order.
    llm_provider_order: list[str] = Field(
        default_factory=lambda: ["groq", "gemini", "cerebras", "openrouter", "ollama"]
    )
    groq_api_key: str = ""
    gemini_api_key: str = ""
    cerebras_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = ""
    llm_timeout_s: float = 45.0
    # provider -> {"fast": model, "smart": model}. Override with LLM_MODELS='{"groq": {...}}'
    llm_models: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "groq": {"fast": "llama-3.1-8b-instant", "smart": "llama-3.3-70b-versatile"},
            "gemini": {"fast": "gemini-2.5-flash-lite", "smart": "gemini-2.5-flash"},
            "cerebras": {"fast": "llama3.1-8b", "smart": "llama-3.3-70b"},
            "openrouter": {
                "fast": "meta-llama/llama-3.3-70b-instruct:free",
                "smart": "meta-llama/llama-3.3-70b-instruct:free",
            },
            "ollama": {"fast": "qwen2.5:3b", "smart": "qwen2.5:7b"},
        }
    )

    # Budgets / quotas
    enrich_llm_daily_budget: int = 400
    agent_daily_messages_per_user: int = 40

    # Crawling
    # Set CRAWL_USER_AGENT in production to include a contact URL for site owners.
    crawl_user_agent: str = "RolecallBot/0.1 (job search for students; polite crawler)"
    crawl_concurrency: int = 8
    crawl_per_host_delay_s: float = 1.0
    aggregator_ttl_days: int = 30
    close_after_missed_runs: int = 2

    # Email (any SMTP: Gmail app password, Brevo, etc.)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @property
    def is_dev(self) -> bool:
        return self.env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
