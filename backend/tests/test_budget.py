import pytest

from orbitroute.llm.budget import BudgetExceeded, BudgetGuard
from orbitroute.llm.pricing import SAM_PER_IMAGE_USD, token_cost


def make_guard(tmp_path, cap=1.0, enabled=True):
    return BudgetGuard(state_path=tmp_path / "state.json", hard_cap_usd=cap, paid_calls_enabled=enabled)


def test_record_persists_across_instances(tmp_path):
    make_guard(tmp_path).record(0.25, "chat")
    assert make_guard(tmp_path).total_spent() == pytest.approx(0.25)


def test_global_cap_blocks_call_that_would_exceed(tmp_path):
    guard = make_guard(tmp_path, cap=1.0)
    guard.record(0.9, "chat")
    with pytest.raises(BudgetExceeded, match="global cap"):
        guard.check(0.2)
    guard.check(0.1)  # exactly at the cap is allowed


def test_run_cap_blocks_even_when_global_budget_is_left(tmp_path):
    guard = make_guard(tmp_path, cap=100.0)
    run = guard.new_run(cap_usd=0.10)
    guard.record(0.08, "chat", run)
    with pytest.raises(BudgetExceeded, match="run cap"):
        guard.check(0.05, run)
    assert run.calls == 1


def test_kill_switch_blocks_all_calls(tmp_path):
    with pytest.raises(BudgetExceeded, match="disabled"):
        make_guard(tmp_path, enabled=False).check(0.0)


def test_spend_is_tracked_per_label(tmp_path):
    guard = make_guard(tmp_path)
    guard.record(0.1, "sam")
    guard.record(0.2, "sam")
    guard.record(0.3, "chat")
    by_label = guard._read()["by_label"]
    assert by_label["sam"] == pytest.approx(0.3)
    assert by_label["chat"] == pytest.approx(0.3)


def test_token_cost_matches_published_spark_1_3_rates():
    # 1M fresh input + 1M output = $1.25 + $4.25
    assert token_cost("muse-spark-1.3", 1_000_000, 1_000_000) == pytest.approx(5.50)
    # cached input is billed at $0.15 per 1M
    assert token_cost("muse-spark-1.3", 1_000_000, 0, cached_tokens=1_000_000) == pytest.approx(0.15)


def test_sam_price_is_per_image():
    assert SAM_PER_IMAGE_USD == pytest.approx(0.0025)


def test_summary_reports_the_running_tally_largest_label_first(tmp_path):
    guard = make_guard(tmp_path, cap=50.0)
    guard.record(0.01, "chat")
    guard.record(0.5, "sam")
    guard.record(0.25, "sam")
    s = guard.summary()
    assert s["spent_usd"] == pytest.approx(0.76) and s["cap_usd"] == 50.0 and s["calls"] == 3
    assert list(s["by_label"]) == ["sam", "chat"]
