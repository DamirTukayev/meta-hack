import json

import httpx
import pytest

from orbitroute.config import Settings
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient


def settings(**kw) -> Settings:
    base = dict(
        api_key="meta-key", base_url="https://api.meta.ai/v1", budget_hard_cap_usd=100, run_cap_usd=1, paid_calls_enabled=True,
        budget_state_path=None, baseten_api_key="bt-key", baseten_base_url="https://inference.baseten.co/v1",
        baseten_model="meta-models/muse-spark-open-1026", reasoning_provider="baseten",
    )
    return Settings(**{**base, **kw})


def make(tmp_path, provider, seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    guard = BudgetGuard(tmp_path / "b.json", 100.0)
    return MetaClient(settings(budget_state_path=tmp_path / "b.json"), guard, provider=provider, transport=httpx.MockTransport(handler))


def test_baseten_client_uses_open_weight_model_and_openai_style_parameters(tmp_path):
    seen: list = []
    make(tmp_path, "baseten", seen).chat([{"role": "user", "content": "hi"}], max_completion_tokens=100)
    url, auth, body = seen[0]
    assert url == "https://inference.baseten.co/v1/chat/completions" and auth == "Bearer bt-key"
    assert body["model"] == "meta-models/muse-spark-open-1026"
    assert body["max_tokens"] == 100 and "max_completion_tokens" not in body and "reasoning_effort" not in body


def test_meta_client_keeps_its_own_parameters(tmp_path):
    seen: list = []
    make(tmp_path, "meta", seen).chat([{"role": "user", "content": "hi"}], max_completion_tokens=100)
    url, auth, body = seen[0]
    assert url == "https://api.meta.ai/v1/chat/completions" and auth == "Bearer meta-key"
    assert body["model"] == "muse-spark-1.3" and body["max_completion_tokens"] == 100 and body["reasoning_effort"] == "low"


def test_missing_baseten_key_is_a_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="BASETEN_API_KEY"):
        MetaClient(settings(baseten_api_key="", budget_state_path=tmp_path / "b.json"), BudgetGuard(tmp_path / "b.json", 1.0), provider="baseten")
