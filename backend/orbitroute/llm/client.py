"""Thin Meta Model API client. Every paid call goes through the budget guard."""

from __future__ import annotations

import base64
import io
import json
import wave
import time
from dataclasses import dataclass
from typing import Any

import httpx

from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetExceeded, BudgetGuard, RunBudget
from orbitroute.llm.pricing import ASR_PER_HOUR_USD, SAM_PER_IMAGE_USD, token_cost, token_price

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


def guard_for(settings: Settings, provider: str = "meta") -> BudgetGuard:
    """Each provider has its own credits, so each gets its own persistent spend counter and cap."""
    if provider == "baseten":
        return BudgetGuard(settings.baseten_state_path, settings.baseten_budget_cap_usd, settings.paid_calls_enabled)
    if provider == "modal":
        return BudgetGuard(settings.modal_state_path, settings.modal_budget_cap_usd, settings.paid_calls_enabled)
    return BudgetGuard(settings.budget_state_path, settings.budget_hard_cap_usd, settings.paid_calls_enabled)


class FailoverClient:
    """Text calls go to the first client; if it fails (rate limit, no credits left, outage) or its budget is used up, the next one answers."""

    def __init__(self, *clients: "MetaClient"):
        if not clients:
            raise ValueError("FailoverClient needs at least one client")
        self.clients = clients
        self.primary, self.secondary = clients[0], clients[-1]  # kept for callers that name the ends of the chain

    def _call(self, method: str, *args: Any, **kw: Any) -> Any:
        last: Exception | None = None
        for client in self.clients:
            try:
                return getattr(client, method)(*args, **kw)
            except (ApiError, httpx.HTTPError, BudgetExceeded, json.JSONDecodeError) as exc:
                last = exc
        assert last is not None
        raise last

    def chat_json(self, *args: Any, **kw: Any) -> tuple[Any, ChatResult]:
        return self._call("chat_json", *args, **kw)

    def chat(self, *args: Any, **kw: Any) -> ChatResult:
        return self._call("chat", *args, **kw)


class MetaClient:
    """Chat / segmentation client for an OpenAI-compatible endpoint.

    `provider="meta"` is the Meta Model API. `provider="baseten"` and `provider="modal"` serve the open-weight Muse Spark Open
    through Baseten and through a Modal shared Endpoint (text steps only; neither has SAM).
    """

    def __init__(
        self,
        settings: Settings,
        guard: BudgetGuard,
        timeout: float = 120.0,
        *,
        provider: str = "meta",
        transport: httpx.BaseTransport | None = None,
    ):
        self.provider = provider
        if provider == "baseten":
            key, base_url, self.default_model = settings.baseten_api_key, settings.baseten_base_url, settings.baseten_model
            if not key:
                raise RuntimeError("BASETEN_API_KEY is not set (see .env.example)")
        elif provider == "modal":
            key, base_url, self.default_model = settings.modal_endpoint_token, settings.modal_endpoint_url, settings.modal_model
            if not (key and base_url):
                raise RuntimeError("MODAL_ENDPOINT_URL and MODAL_ENDPOINT_TOKEN are not set (see .env.example)")
        else:
            key, base_url, self.default_model = settings.api_key, settings.base_url, DEFAULT_MODEL
            if not key:
                raise RuntimeError("MODEL_API_KEY is not set (see .env.example)")
        self._http = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, transport=transport)
        self._guard = guard

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_completion_tokens: int,
        model: str | None = None,
        response_format: dict[str, Any] | None = None,
        reasoning_effort: str = "low",
        run: RunBudget | None = None,
        label: str = "chat",
    ) -> ChatResult:
        """max_completion_tokens is required: reasoning tokens count against it."""
        model = model or self.default_model
        est_input = _text_chars(messages) // 3 + _count_images(messages) * IMAGE_TOKENS_ESTIMATE
        est_cost = token_cost(model, est_input, max_completion_tokens)
        self._guard.check(est_cost, run)

        body: dict[str, Any] = {"model": model, "messages": messages}
        if self.provider in ("baseten", "modal"):  # plain OpenAI-style parameters
            body["max_tokens"] = max_completion_tokens
        else:
            body["max_completion_tokens"] = max_completion_tokens
            body["reasoning_effort"] = reasoning_effort
        if response_format is not None:
            body["response_format"] = response_format

        data = self._post("/chat/completions", body)
        usage = data.get("usage") or {}
        in_tok = usage.get("prompt_tokens") or 0
        out_tok = usage.get("completion_tokens") or 0
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0  # some providers send null instead of omitting the field
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
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

    def transcribe(self, wav: bytes, *, max_seconds: float = 60.0, run: RunBudget | None = None, label: str = "asr") -> str:
        """Speech to text with Muse Voice Transcribe. `wav` must be a PCM WAV file (the endpoint accepts WAV only)."""
        try:
            with wave.open(io.BytesIO(wav)) as w:
                seconds = w.getnframes() / float(w.getframerate())
        except (wave.Error, EOFError) as exc:
            raise ValueError(f"not a valid WAV file: {exc}") from exc
        if seconds > max_seconds:
            raise ValueError(f"the recording is {seconds:.0f} s long; the limit is {max_seconds:.0f} s")
        cost = seconds / 3600 * ASR_PER_HOUR_USD
        self._guard.check(cost, run)
        request = json.dumps({"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"})
        resp = self._http.post(
            "/asr/transcribe",
            files={"request": (None, request, "application/json"), "audio": ("speech.wav", wav, "audio/wav")},
            headers={"Accept": "application/json"},
        )
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        self._guard.record(cost, label, run)
        return str(resp.json().get("transcript", "")).strip()

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
