"""Thin Meta Model API client. Every paid call goes through the budget guard."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetGuard, RunBudget
from orbitroute.llm.pricing import SAM_PER_IMAGE_USD, token_cost, token_price

DEFAULT_MODEL = "muse-spark-1.3"
SAM_MODEL = "sam-3.1"
IMAGE_TOKENS_ESTIMATE = 4000  # conservative per-image input estimate for pre-call budget checks
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 2


class ApiError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"API error {status}: {body[:500]}")
        self.status = status


@dataclass
class ChatResult:
    text: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost_usd: float
    raw: dict[str, Any]


def image_part(data: bytes, mime: str = "image/jpeg") -> dict[str, Any]:
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return {"type": "image_url", "image_url": {"url": url}}


def _count_images(messages: list[dict[str, Any]]) -> int:
    n = 0
    for m in messages:
        if isinstance(m.get("content"), list):
            n += sum(1 for p in m["content"] if p.get("type") == "image_url")
    return n


def _text_chars(messages: list[dict[str, Any]]) -> int:
    chars = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            chars += sum(len(p.get("text", "")) for p in c if p.get("type") == "text")
    return chars


class MetaClient:
    def __init__(self, settings: Settings, guard: BudgetGuard, timeout: float = 120.0):
        if not settings.api_key:
            raise RuntimeError("MODEL_API_KEY is not set (see .env.example)")
        self._http = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=timeout,
        )
        self._guard = guard

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_completion_tokens: int,
        model: str = DEFAULT_MODEL,
        response_format: dict[str, Any] | None = None,
        reasoning_effort: str = "low",
        run: RunBudget | None = None,
        label: str = "chat",
    ) -> ChatResult:
        """max_completion_tokens is required: reasoning tokens count against it."""
        est_input = _text_chars(messages) // 3 + _count_images(messages) * IMAGE_TOKENS_ESTIMATE
        est_cost = token_cost(model, est_input, max_completion_tokens)
        self._guard.check(est_cost, run)

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_completion_tokens,
            "reasoning_effort": reasoning_effort,
        }
        if response_format is not None:
            body["response_format"] = response_format

        data = self._post("/chat/completions", body)
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cached = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        reasoning = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
        cost = token_cost(model, in_tok, out_tok, cached)
        self._guard.record(cost, label, run)

        choice = data["choices"][0]
        return ChatResult(
            text=choice["message"].get("content") or "",
            input_tokens=in_tok,
            output_tokens=out_tok,
            reasoning_tokens=reasoning,
            cost_usd=cost,
            raw=data,
        )

    def chat_json(self, messages: list[dict[str, Any]], schema_name: str, schema: dict[str, Any], **kw: Any) -> tuple[Any, ChatResult]:
        fmt = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema}}
        result = self.chat(messages, response_format=fmt, **kw)
        return json.loads(result.text), result

    def segment_raw(
        self,
        image: bytes,
        concept: str,
        *,
        mime: str = "image/jpeg",
        mask_encoding: str = "one_bit",
        include_confidence: bool = True,
        run: RunBudget | None = None,
        label: str = "sam",
    ) -> tuple[dict[str, Any], float]:
        """Run SAM 3.1 for one concept (short noun phrase). Returns the raw Responses payload."""
        self._guard.check(SAM_PER_IMAGE_USD, run)
        body = {
            "model": SAM_MODEL,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": concept},
                        {"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(image).decode()}"},
                    ],
                }
            ],
            "metadata": {
                "mask_encoding": mask_encoding,
                "include_confidence": "true" if include_confidence else "false",
            },
        }
        data = self._post("/responses", body)
        self._guard.record(SAM_PER_IMAGE_USD, label, run)
        return data, SAM_PER_IMAGE_USD

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(MAX_RETRIES + 1):
            resp = self._http.post(path, json=body)
            if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                time.sleep(2**attempt)
                continue
            if resp.status_code >= 400:
                raise ApiError(resp.status_code, resp.text)
            return resp.json()
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._http.close()
