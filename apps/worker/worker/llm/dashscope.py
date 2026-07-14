"""DashScope / Qwen LLM adapter (OpenAI-compatible REST API).

Uses the DashScope MaaS endpoint with json_object response format and a
schema-in-system-prompt approach — mirrors the GeminiLLM interface so the
two are interchangeable at runtime.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

_TIMEOUT = 200.0


def _strip_json_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -len("```")]
    return s.strip()


def _schema_hint(schema: dict[str, Any]) -> str:
    """Turn the response schema into a compact, complete nested contract."""

    def describe(node: dict[str, Any]) -> str:
        node_type = node.get("type", "any")
        nullable = "|null" if node.get("nullable") else ""
        enum = node.get("enum")
        if enum:
            values = ",".join(json.dumps(value, ensure_ascii=False) for value in enum)
            return f"enum({values}){nullable}"
        if node_type == "array":
            return f"array<{describe(node.get('items') or {})}>{nullable}"
        if node_type == "object":
            required = set(node.get("required") or [])
            fields = []
            for key, child in (node.get("properties") or {}).items():
                suffix = "!" if key in required else "?"
                fields.append(f"{key}{suffix}:{describe(child)}")
            return "object{" + ",".join(fields) + "}" + nullable
        return f"{node_type}{nullable}"

    return (
        "Respond ONLY with one valid JSON object matching this complete schema. "
        "Keys marked ! are required; keys marked ? are optional. Do not rename keys.\n"
        f"Schema: {describe(schema)}"
    )


class DashScopeLLM:
    provider = "dashscope"

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        from worker.settings import settings

        self.api_key = api_key or settings.DASHSCOPE_API_KEY.get_secret_value()
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not set")
        # Use the configured MaaS URL + compatible-mode path.
        raw_base = base_url or settings.DASHSCOPE_BASE_URL
        if not raw_base:
            raw_base = "https://dashscope.aliyuncs.com"
        self.base_url = raw_base.rstrip("/") + "/compatible-mode/v1"

    def generate_structured(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        model: str,
        temperature: float = 0.2,
    ) -> tuple[dict[str, Any], int, int]:
        system_msg = _schema_hint(response_schema)

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if resp.status_code == 429:
            raise RuntimeError("429 RESOURCE_EXHAUSTED: DashScope rate limit")
        if resp.status_code == 503:
            raise RuntimeError("503 UNAVAILABLE: DashScope service unavailable")
        if not resp.is_success:
            raise RuntimeError(
                f"{resp.status_code} DashScope API error: {resp.text[:500]}"
            )

        data = resp.json()
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("DashScope returned no choices")
        text = (choices[0].get("message") or {}).get("content", "").strip()
        if not text:
            raise RuntimeError("DashScope returned an empty response")

        try:
            parsed = json.loads(_strip_json_fences(text))
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"DashScope returned invalid JSON: {e}; raw={text[:200]!r}"
            ) from None
        if not isinstance(parsed, dict):
            raise RuntimeError(f"DashScope response is not an object: {str(parsed)[:200]!r}")

        logger.debug("DashScope {} tokens in={} out={}", model, in_tok, out_tok)
        return parsed, in_tok, out_tok
