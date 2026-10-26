"""Repair actions and the policy that picks one: Muse Spark decides, a deterministic policy backs it up."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from orbitroute.llm.budget import BudgetExceeded, RunBudget
from orbitroute.llm.client import ApiError, MetaClient
from orbitroute.verifier.checks import Report

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
class DecisionContext:
    report: Report
    iteration: int
    history: list[str]  # actions already taken, oldest first
    unreachable_orders: list[int] = field(default_factory=list)
    all_zone_edges_banned: bool = False


def allowed_actions(ctx: DecisionContext) -> list[str]:
    kinds = set(ctx.report.summary())
    allowed: list[str] = []
    if ctx.unreachable_orders:
        allowed.append("exclude_unreachable")
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


class PolicyDecider:
    """Deterministic rules; also the fallback whenever the model's answer cannot be used."""

    def decide(self, ctx: DecisionContext) -> Decision:
        allowed = allowed_actions(ctx)
        kinds = set(ctx.report.summary())
        if "exclude_unreachable" in allowed:
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


DECIDE_SYSTEM = (
    "You are the repair planner of a delivery-routing agent. A verifier found violations in the current plan. "
    "Choose exactly one action from the allowed list. Prefer cheap, targeted fixes before broad ones, never repeat a "
    "fix that already failed twice, and choose propose_relaxation only when the constraints look contradictory. "
    "Answer with the action and a one-sentence reason a dispatcher can read."
)


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
            "allowed_actions": {a: ACTIONS[a] for a in allowed},
        }
        import json

        messages = [{"role": "system", "content": DECIDE_SYSTEM}, {"role": "user", "content": json.dumps(facts)}]
        try:
            raw, _ = self._client.chat_json(
                messages, "RepairDecision", schema, max_completion_tokens=1500, reasoning_effort="low", run=self._run, label="repair_decision"
            )
            if raw.get("action") in allowed and str(raw.get("reason", "")).strip():
                return Decision(raw["action"], raw["reason"].strip(), "model")
        except (ApiError, BudgetExceeded, ValueError, KeyError):
            pass
        fb = self._fallback.decide(ctx)
        return Decision(fb.action, fb.reason + " (model answer unusable; policy used)", "policy")
