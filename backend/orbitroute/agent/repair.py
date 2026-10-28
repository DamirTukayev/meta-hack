"""Repair actions and the policy that picks one: Muse Spark decides, a deterministic policy backs it up."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from orbitroute import prompts
from orbitroute.llm.budget import BudgetExceeded, RunBudget
from orbitroute.llm.client import ApiError, MetaClient
from orbitroute.verifier.checks import Report

MAX_EXCLUDED_SHARE = 0.2  # leaving out more than this share of the orders is not a plan, it is a refusal

ACTIONS = {
    "ban_violating_edges": "Forbid exactly the road segments that entered an avoided zone, then re-solve.",
    "ban_all_zone_edges": "Forbid every road segment inside the avoided zones, then re-solve.",
    "exclude_unreachable": "Leave out the orders that cannot be reached without entering an avoided zone, and report them.",
    "resolve_longer": "Re-run the solver with a longer time limit and a different random seed.",
    "propose_relaxation": "Stop repairing: the request cannot be met as stated. Compute the smallest relaxation that works.",
}


@dataclass
class Decision:
    action: str
    reason: str
    source: str  # "model" | "policy"


@dataclass
class Recommendation:
    index: int  # which relaxation option the agent recommends
    reason: str
    source: str  # "model" | "policy"


def breaks_a_rule(option) -> bool:
    """Options that stop avoiding the zone drive through what was forbidden; the others only change what is served or how."""
    return option.kind.startswith("allow_zone")


def policy_recommendation(options) -> Recommendation:
    """Rules first: keep every rule, serve the most orders; drive through the zone only when nothing else is left."""
    safe = [i for i, o in enumerate(options) if not breaks_a_rule(o)]
    if not safe:
        return Recommendation(0, "Every option drives through the avoided zone; this one does it the least.", "policy")
    best = max(safe, key=lambda i: (sum(len(r.stops) for r in options[i].plan.routes), -i))
    return Recommendation(best, "It breaks no rule and serves the most orders of the options that keep every rule.", "policy")


@dataclass
class DecisionContext:
    report: Report
    iteration: int
    history: list[str]  # actions already taken, oldest first
    unreachable_orders: list[int] = field(default_factory=list)
    all_zone_edges_banned: bool = False
    total_orders: int = 0


def allowed_actions(ctx: DecisionContext) -> list[str]:
    kinds = set(ctx.report.summary())
    allowed: list[str] = []
    if ctx.unreachable_orders:
        allowed.append("exclude_unreachable")
        allowed.append("propose_relaxation")
    if "zones" in kinds:
        allowed.append("ban_violating_edges")
        if not ctx.all_zone_edges_banned:
            allowed.append("ban_all_zone_edges")
    if kinds & {"deadline", "capacity", "fleet", "coverage"}:
        allowed += ["resolve_longer", "propose_relaxation"]
    if "paths" in kinds and not ctx.unreachable_orders:
        allowed.append("resolve_longer")
    return allowed or ["propose_relaxation"]


class Decider(Protocol):
    def decide(self, ctx: DecisionContext) -> Decision: ...

    def recommend(self, options, problem) -> Recommendation: ...


class PolicyDecider:
    """Deterministic rules; also the fallback whenever the model's answer cannot be used."""

    def recommend(self, options, problem) -> Recommendation:
        return policy_recommendation(options)

    def decide(self, ctx: DecisionContext) -> Decision:
        allowed = allowed_actions(ctx)
        kinds = set(ctx.report.summary())
        if "exclude_unreachable" in allowed:
            if ctx.total_orders and len(ctx.unreachable_orders) > MAX_EXCLUDED_SHARE * ctx.total_orders:
                return Decision(
                    "propose_relaxation",
                    f"{len(ctx.unreachable_orders)} of {ctx.total_orders} orders can only be reached through the avoided zone; dropping that many would not be a plan.",
                    "policy",
                )
            return Decision("exclude_unreachable", "Some orders cannot be reached without entering an avoided zone.", "policy")
        if "zones" in kinds:
            tried = ctx.history.count("ban_violating_edges")
            if tried < 2 or "ban_all_zone_edges" not in allowed:
                return Decision("ban_violating_edges", "Cut exactly the segments that entered the zone and re-solve.", "policy")
            return Decision("ban_all_zone_edges", "Targeted cuts keep finding new crossings; forbid the whole zone.", "policy")
        if "capacity" in kinds:  # more search time cannot create capacity
            return Decision("propose_relaxation", "The trucks cannot carry all orders; look for the smallest relaxation.", "policy")
        if ctx.history.count("resolve_longer") < 1 and "resolve_longer" in allowed:
            return Decision("resolve_longer", "The solver may simply need more search time.", "policy")
        return Decision("propose_relaxation", "The constraints appear contradictory; look for the smallest relaxation.", "policy")


class ModelDecider:
    """Asks Muse Spark to pick the repair action; falls back to the policy if the answer is unusable."""

    def __init__(self, client: MetaClient, run: RunBudget | None = None, fallback: Decider | None = None):
        self._client, self._run = client, run
        self._fallback = fallback or PolicyDecider()

    def decide(self, ctx: DecisionContext) -> Decision:
        allowed = allowed_actions(ctx)
        schema = {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": allowed}, "reason": {"type": "string"}},
            "required": ["action", "reason"],
        }
        facts = {
            "iteration": ctx.iteration,
            "violations": [{"kind": v.kind, "message": v.message} for v in ctx.report.violations][:8],
            "actions_already_taken": ctx.history,
            "orders_unreachable_without_entering_the_zone": ctx.unreachable_orders[:10],
            "total_orders": ctx.total_orders,
            "rule": f"Leaving out more than {int(MAX_EXCLUDED_SHARE * 100)}% of the orders is not acceptable; choose propose_relaxation then.",
            "allowed_actions": {a: ACTIONS[a] for a in allowed},
        }
        import json

        messages = [{"role": "system", "content": prompts.load("repair")[1]}, {"role": "user", "content": json.dumps(facts)}]
        try:
            raw, _ = self._client.chat_json(
                messages, "RepairDecision", schema, max_completion_tokens=3000, reasoning_effort="low", run=self._run, label="repair_decision"
            )
            if raw.get("action") in allowed and str(raw.get("reason", "")).strip():
                return Decision(raw["action"], raw["reason"].strip(), "model")
        except (ApiError, BudgetExceeded, ValueError, KeyError):
            pass
        fb = self._fallback.decide(ctx)
        return Decision(fb.action, fb.reason + " (model answer unusable; policy used)", "policy")

    def recommend(self, options, problem) -> Recommendation:
        """Asks Muse Spark which verified alternative to recommend; a rule keeps it from recommending to drive through a forbidden zone."""
        import json

        fallback = policy_recommendation(options)
        if len(options) < 2:
            return fallback
        schema = {
            "type": "object",
            "properties": {"index": {"type": "integer", "enum": list(range(len(options)))}, "reason": {"type": "string"}},
            "required": ["index", "reason"],
        }
        facts = {
            "avoided_zone_kinds": list(problem.avoid_zone_kinds),
            "orders_in_the_request": problem.n_orders,
            "options": [
                {
                    "index": i,
                    "change": o.description,
                    "orders_served": sum(len(r.stops) for r in o.plan.routes),
                    "orders_left_out": len(o.report.excluded),
                    "drives_through_avoided_zone": breaks_a_rule(o),
                    "trucks_used": sum(1 for r in o.plan.routes if r.stops),
                    "last_truck_back": o.report.metrics.get("last_return"),
                }
                for i, o in enumerate(options)
            ],
        }
        messages = [{"role": "system", "content": prompts.load("recommend")[1]}, {"role": "user", "content": json.dumps(facts)}]
        try:
            raw, _ = self._client.chat_json(messages, "Recommendation", schema, max_completion_tokens=3000, reasoning_effort="low", run=self._run, label="recommendation")
            index = raw.get("index")
            reason = str(raw.get("reason", "")).strip()
            safe_exists = any(not breaks_a_rule(o) for o in options)
            if isinstance(index, int) and 0 <= index < len(options) and reason and not (safe_exists and breaks_a_rule(options[index])):
                return Recommendation(index, reason, "model")
        except (ApiError, BudgetExceeded, ValueError, KeyError):
            pass
        return Recommendation(fallback.index, fallback.reason + " (model answer unusable; policy used)", "policy")
