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
        baseten_budget_cap_usd=60.0, baseten_state_path=None,
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


def test_each_provider_has_its_own_budget_counter_and_cap(tmp_path):
    from orbitroute.llm.client import guard_for

    st = settings(budget_state_path=tmp_path / "meta.json", baseten_state_path=tmp_path / "bt.json", baseten_budget_cap_usd=7.0, budget_hard_cap_usd=100.0)
    meta, bt = guard_for(st, "meta"), guard_for(st, "baseten")
    bt.record(1.5, "chat")
    assert bt.total_spent() == 1.5 and meta.total_spent() == 0.0
    assert bt.hard_cap_usd == 7.0 and meta.hard_cap_usd == 100.0


def test_failover_uses_the_secondary_when_the_open_weight_side_fails_or_runs_out_of_budget(tmp_path):
    from orbitroute.llm.budget import BudgetExceeded
    from orbitroute.llm.client import ApiError, FailoverClient

    class Side:
        def __init__(self, result=None, error=None):
            self.result, self.error, self.calls = result, error, 0

        def chat_json(self, *a, **kw):
            self.calls += 1
            if self.error:
                raise self.error
            return self.result, None

    ok = Side(result={"v": "primary"})
    assert FailoverClient(ok, Side(result={"v": "backup"})).chat_json("m")[0] == {"v": "primary"}
    for err in (ApiError(429, "rate limited"), ApiError(402, "no credits"), BudgetExceeded("cap")):
        backup = Side(result={"v": "backup"})
        assert FailoverClient(Side(error=err), backup).chat_json("m")[0] == {"v": "backup"} and backup.calls == 1
