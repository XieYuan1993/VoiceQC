"""LLM provider registry — mirrors the ASR factory shape."""

from __future__ import annotations

from worker.llm.base import LLMAdapter
from worker.llm.dashscope import DashScopeLLM
from worker.llm.fallback import FallbackLLM
from worker.llm.gemini import GeminiLLM

PROVIDERS = {
    "gemini": GeminiLLM,
    "dashscope": DashScopeLLM,
}


def create(provider: str = "gemini", **kwargs) -> LLMAdapter:
    try:
        cls = PROVIDERS[provider]
    except KeyError as e:
        raise ValueError(f"unknown LLM provider {provider!r}; known: {sorted(PROVIDERS)}") from e
    return cls(**kwargs)


def create_with_fallback(primary: str, fallback: str, fallback_model: str) -> FallbackLLM:
    """Return a FallbackLLM that tries `primary` and switches to `fallback` on errors."""
    return FallbackLLM(
        create(primary),
        create(fallback),
        fallback_model=fallback_model,
    )
