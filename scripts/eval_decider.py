"""Does Muse Spark choose the repair the rules would? On the scenarios of the large suite whose first plan breaks a rule.

The scenarios are the random ones of `scripts/eval_big_suite.py` (same generator and seed). The first K whose first plan needs a
repair are kept. For each, the agent runs once per model with the model as the repair decider; at every decision point the rules
are asked as well, on the same facts, so the two choices can be compared even when the runs then diverge. The returned plans are
judged by the independent audit. Costs a few cents per model.

Usage:
    uv run python scripts/eval_decider.py --provider meta|baseten [--cases 120] [--seed 7]    -> eval/decider_<provider>.json
    uv run python scripts/eval_decider.py --report                                              -> eval/DECIDER.md
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent))
from eval_big_suite import PHOTOS, draw

import orbitroute.api as api
from orbitroute.agent.loop import run_agent
from orbitroute.agent.repair import DecisionContext, ModelDecider, PolicyDecider, breaks_a_rule
from orbitroute.config import ROOT
from orbitroute.eval.runner import build_scenario, load_world
from orbitroute.llm.client import MetaClient, guard_for
from orbitroute.verifier.independent import audit_plan

LABELS = {"meta": "Muse Spark 1.3 (Meta API)", "baseten": "Muse Spark Open (Baseten)"}


class Recording(ModelDecider):
    """The model decides; the rules are asked on the same facts and both answers are kept."""

    def __init__(self, client, run):
        super().__init__(client, run)
        self.log: list[dict] = []
        self.recs: list[dict] = []

    def decide(self, ctx: DecisionContext):
        d = super().decide(ctx)
        p = PolicyDecider().decide(ctx)
        self.log.append({"kinds": sorted(ctx.report.summary()), "model": d.action, "policy": p.action, "source": d.source, "reason": d.reason})
        return d

    def recommend(self, options, problem):
        r = super().recommend(options, problem)
        p = PolicyDecider().recommend(options, problem)
        self.recs.append({"model": r.index, "policy": p.index, "source": r.source, "unsafe": any(not breaks_a_rule(o) for o in options) and breaks_a_rule(options[r.index])})
        return r


def cases(n: int, seed: int):
    """The first `n` random scenarios of the large suite that need a repair, with what the rules do (free, cached answers only)."""
    cached = api.guard.new_run(3.0)
    worlds = {p: load_world(api.get_client(), p, cached) for p in PHOTOS}
    rng, out, i = random.Random(seed), [], 0
    while len(out) < n and i < 2000:
        sc = draw(rng, i)
        i += 1
        try:
            scenario = build_scenario(worlds[sc.sample], sc)
        except ValueError:
            continue
        base = run_agent(scenario, decider=PolicyDecider(), time_limit_s=1.0)
        if not base.iterations[0].report.ok:
            out.append((sc, worlds[sc.sample], base))
    return out, i


def run_one(provider: str, n: int, seed: int) -> None:
    s = api.settings
    client = api.get_client() if provider == "meta" else MetaClient(s, guard_for(s, provider), provider=provider)
    guard = api.guard if provider == "meta" else guard_for(s, provider)
    spent0 = guard.total_spent()
    run = guard.new_run(4.0)
    chosen, drawn = cases(n, seed)
    print(f"{len(chosen)} scenarios need a repair (drawn {drawn}); asking {LABELS[provider]}", flush=True)
    rows, decisions, recs = [], [], []
    t0 = time.perf_counter()
    for k, (sc, world, base) in enumerate(chosen):
        scenario = build_scenario(world, sc)
        dec = Recording(client, run)
        res = run_agent(scenario, decider=dec, time_limit_s=1.0)
        audit = audit_plan(res.scenario, res.plan, excluded=res.report.excluded)
        returned = res.status in ("verified", "verified_partial")
        rows.append({
            "id": sc.id, "model_status": res.status, "policy_status": base.status, "model_iterations": len(res.iterations), "policy_iterations": len(base.iterations),
            "returned": returned, "returned_fails_audit": returned and not audit.ok, "decisions": len(dec.log),
        })
        decisions += dec.log
        recs += dec.recs
        if (k + 1) % 10 == 0:
            print(f"{k + 1}/{len(chosen)} {time.perf_counter() - t0:.0f}s ${guard.total_spent() - spent0:.3f}", flush=True)
    out = {"provider": provider, "label": LABELS[provider], "cases": len(chosen), "drawn": drawn, "seed": seed, "rows": rows, "decisions": decisions, "recommendations": recs, "cost_usd": round(guard.total_spent() - spent0, 4)}
    (ROOT / "eval" / f"decider_{provider}.json").write_text(json.dumps(out, indent=1))
    print("cost", out["cost_usd"])


def report() -> None:
    lines = [
        "# The model as the repair decider, against the rules", "",
        "Generated by `scripts/eval_decider.py`. The scenarios are the random ones of `eval/BIG_SUITE.md` (same generator and seed) whose first plan breaks a rule, so that the agent has to repair it.",
        "At every decision point the model chose an action and the deterministic rules were asked on the same facts; the plans each run returned were judged by the independent audit.", "",
        "| Model | Scenarios | Decisions | Same action as the rules | Answer came from the model | Ended like the rules did | Returned plans failing the audit | Cost |", "|---|---|---|---|---|---|---|---|",
    ]
    detail = []
    for p in ("meta", "baseten"):
        f = ROOT / "eval" / f"decider_{p}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        dec, rows = d["decisions"], d["rows"]
        same = sum(x["model"] == x["policy"] for x in dec)
        from_model = sum(x["source"] == "model" for x in dec)
        like = sum(r["model_status"] == r["policy_status"] for r in rows)
        returned = [r for r in rows if r["returned"]]
        lines.append(f"| {d['label']} | {d['cases']} | {len(dec)} | {same} ({same / max(len(dec), 1):.0%}) | {from_model} ({from_model / max(len(dec), 1):.0%}) | {like} ({like / max(len(rows), 1):.0%}) | {sum(r['returned_fails_audit'] for r in returned)} of {len(returned)} | ${d['cost_usd']:.2f} |")
        diff = Counter((x["policy"], x["model"]) for x in dec if x["model"] != x["policy"])
        statuses = Counter((r["policy_status"], r["model_status"]) for r in rows if r["policy_status"] != r["model_status"])
        recs = d["recommendations"]
        detail.append(
            f"**{d['label']}.** Where the model chose differently (rules → model): " + (", ".join(f"{a} → {b} ×{n}" for (a, b), n in diff.most_common()) or "never")
            + ". Runs that ended differently (rules → model): " + (", ".join(f"{a} → {b} ×{n}" for (a, b), n in statuses.most_common()) or "none")
            + f". Mean iterations: {mean(r['model_iterations'] for r in rows):.2f} with the model, {mean(r['policy_iterations'] for r in rows):.2f} with the rules."
            + (f" Recommendation among verified alternatives: {sum(r['model'] == r['policy'] for r in recs)} of {len(recs)} the same as the rules, {sum(r['unsafe'] for r in recs)} recommended driving through a forbidden zone although a safe option existed." if recs else "")
        )
    lines += ["", *[x + "\n" for x in detail], "Limits: random scenarios, not real requests; the rules and the audit were written by the same author, so \"same as the rules\" measures agreement, not that either is right; a different choice can still end in a verified plan.", ""]
    (ROOT / "eval" / "DECIDER.md").write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["meta", "baseten"])
    ap.add_argument("--cases", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    report() if a.report else run_one(a.provider, a.cases, a.seed)
