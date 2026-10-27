"""Run the evaluation suites and write eval/results.json.

Usage: uv run python scripts/run_eval.py [--scenarios] [--parse]   (both when no flag is given)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from orbitroute.config import Settings
from orbitroute.eval.runner import run_parse_eval, run_scenarios, summarize_scenarios
from orbitroute.llm.budget import BudgetGuard
from orbitroute.llm.client import MetaClient, guard_for

OUT = Path("eval/results.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", action="store_true")
    ap.add_argument("--parse", action="store_true")
    ap.add_argument("--prompt-version", default=None, help="request prompt version to test (default: the active one)")
    ap.add_argument("--provider", choices=["meta", "baseten"], default="meta", help="which endpoint answers the request-parsing cases")
    a = ap.parse_args()
    both = not (a.scenarios or a.parse)

    s = Settings.load()
    guard = BudgetGuard(s.budget_state_path, s.budget_hard_cap_usd, s.paid_calls_enabled)
    client = MetaClient(s, guard)
    spent0 = guard.total_spent()
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    if a.scenarios or both:
        rows = run_scenarios(client, guard)
        out["scenarios"] = {"summary": summarize_scenarios(rows), "rows": rows}
    if a.parse or both:
        parse_client = MetaClient(s, guard, provider="baseten") if a.provider == "baseten" else client
        from orbitroute.prompts import active_version

        version = a.prompt_version or active_version("request")
        key = ("parsing_baseten" if a.provider == "baseten" else "parsing") + ("" if version == "v1" else f"_{version}")
        out[key] = run_parse_eval(parse_client, parse_guard, prompt_version=a.prompt_version)
    out["eval_cost_usd"] = round(guard.total_spent() - spent0, 4)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=list))
    print(json.dumps({k: v["summary"] if k == "scenarios" else {x: y for x, y in v.items() if x != "failures"} for k, v in out.items() if isinstance(v, dict)}, indent=1))


if __name__ == "__main__":
    main()
