from worker.llm import dashscope


class FakeResponse:
    status_code = 200
    is_success = True
    text = ""

    def json(self):
        return {
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "choices": [{"message": {"content": '{"ok": true}'}}],
        }


def test_dashscope_can_disable_thinking_for_deterministic_tasks(monkeypatch) -> None:
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, *, headers, json):
            captured.update(json)
            return FakeResponse()

    monkeypatch.setattr(dashscope.httpx, "Client", FakeClient)
    adapter = dashscope.DashScopeLLM(
        api_key="test-key",
        base_url="https://example.invalid",
        enable_thinking=False,
    )

    parsed, input_tokens, output_tokens = adapter.generate_structured(
        "test",
        {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        model="qwen3.7-max",
    )

    assert parsed == {"ok": True}
    assert (input_tokens, output_tokens) == (3, 2)
    assert captured["enable_thinking"] is False
