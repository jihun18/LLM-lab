import json

import httpx

from core.ollama_client import OllamaClient


def test_list_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:1.7b"}]})

    client = OllamaClient(transport=httpx.MockTransport(handler))
    assert client.list_models()[0]["name"] == "qwen3:1.7b"


def test_chat_disables_thinking_and_limits_context():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["think"] is False
        assert payload["options"]["num_ctx"] == 2048
        assert payload["messages"][-1]["content"] == "테스트\n\n/no_think"
        return httpx.Response(
            200,
            json={
                "model": "qwen3:1.7b",
                "message": {"content": "테스트 답변"},
                "eval_count": 10,
                "eval_duration": 2_000_000_000,
            },
        )

    client = OllamaClient(transport=httpx.MockTransport(handler))
    result = client.chat("테스트")
    assert result["answer"] == "테스트 답변"
    assert result["tokens_per_second"] == 5.0


def test_non_qwen3_model_keeps_original_prompt():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][-1]["content"] == "테스트"
        return httpx.Response(
            200,
            json={
                "model": "gemma3:4b",
                "message": {"content": "테스트 답변"},
                "eval_count": 1,
                "eval_duration": 1_000_000_000,
            },
        )

    client = OllamaClient(transport=httpx.MockTransport(handler))
    result = client.chat("테스트", model="gemma3:4b")
    assert result["answer"] == "테스트 답변"


def test_qwen3_instruct_model_keeps_original_prompt():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][-1]["content"] == "테스트"
        return httpx.Response(
            200,
            json={
                "model": "qwen3:4b-instruct",
                "message": {"content": "테스트 답변"},
                "eval_count": 1,
                "eval_duration": 1_000_000_000,
            },
        )

    client = OllamaClient(transport=httpx.MockTransport(handler))
    result = client.chat("테스트", model="qwen3:4b-instruct")
    assert result["answer"] == "테스트 답변"
