"""Pluggable LLM adapter contract (requirement: "Gemini first")."""

from __future__ import annotations

from typing import Any, Protocol


class LLMAdapter(Protocol):
    provider: str

    def generate_structured(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.2,
    ) -> tuple[dict[str, Any], int, int]:
        """One structured-output call.

        Returns (parsed_json, input_tokens, output_tokens). Raises on
        transport failure or unparseable output.
        """
        ...
