from collections.abc import Iterator
from typing import Any
import json
import time

import httpx

from .config import settings


class OllamaError(RuntimeError):
    """Raised when the local Ollama service cannot complete a request."""


class OllamaClient:
    def __init__(
        self,
        base_url: str = settings.ollama_url,
        timeout: float = 180.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        )

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        with self._client() as client:
            response = client.get("/api/tags")
            response.raise_for_status()
        return {
            "status": "ok",
            "ollama_url": self.base_url,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def list_models(self) -> list[dict[str, Any]]:
        try:
            with self._client() as client:
                response = client.get("/api/tags")
                response.raise_for_status()
                return response.json().get("models", [])
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama 모델 목록 조회 실패: {exc}") from exc

    def _payload(
        self,
        prompt: str,
        model: str | None,
        system: str | None,
        stream: bool,
    ) -> dict[str, Any]:
        selected_model = model or settings.default_model
        user_prompt = prompt
        model_name = selected_model.lower()
        if model_name.split(":", 1)[0] == "qwen3" and "instruct" not in model_name:
            user_prompt = f"{prompt.rstrip()}\n\n/no_think"

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_prompt})
        return {
            "model": selected_model,
            "messages": messages,
            "stream": stream,
            "think": False,
            "options": {
                "num_ctx": settings.num_ctx,
                "num_predict": settings.num_predict,
                "temperature": settings.temperature,
            },
        }

    def chat(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with self._client() as client:
                response = client.post(
                    "/api/chat",
                    json=self._payload(prompt, model, system, stream=False),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama 채팅 요청 실패: {exc}") from exc

        elapsed = time.perf_counter() - started
        eval_count = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 0)
        return {
            "model": data.get("model", model or settings.default_model),
            "answer": data.get("message", {}).get("content", ""),
            "elapsed_seconds": round(elapsed, 3),
            "tokens_per_second": round(eval_count / (eval_duration / 1e9), 2)
            if eval_count and eval_duration
            else None,
            "eval_count": eval_count,
        }

    def stream_chat(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        payload = self._payload(prompt, model, system, stream=True)
        started = time.perf_counter()
        try:
            with self._client() as client:
                with client.stream("POST", "/api/chat", json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if chunk.get("done"):
                            eval_count = chunk.get("eval_count", 0)
                            eval_duration = chunk.get("eval_duration", 0)
                            yield {
                                "done": True,
                                "elapsed_seconds": round(time.perf_counter() - started, 3),
                                "tokens_per_second": round(
                                    eval_count / (eval_duration / 1e9), 2
                                )
                                if eval_count and eval_duration
                                else None,
                                "eval_count": eval_count,
                            }
                        else:
                            yield {
                                "done": False,
                                "content": chunk.get("message", {}).get("content", ""),
                            }
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama 스트리밍 요청 실패: {exc}") from exc
