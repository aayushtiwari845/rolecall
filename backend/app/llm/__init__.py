"""Provider-agnostic LLM access over free tiers (and local models)."""

from app.llm.router import LLMError, LLMResult, get_llm

__all__ = ["LLMError", "LLMResult", "get_llm"]
