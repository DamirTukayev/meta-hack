"""Budget guard: every paid call is reserved before it is sent and recorded after.

The provider's own spend limit only sends an email, so the cap is enforced here.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """Raised before a paid call that would break a cap (or when paid calls are disabled)."""


@dataclass
class BudgetGuard:
    state_path: Path
    hard_cap_usd: float
    paid_calls_enabled: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def summary(self) -> dict:
        """Our own running tally (an estimate from token counts, not the provider's invoice)."""
        state = self._read()
        return {
            "spent_usd": round(state.get("total_usd", 0.0), 4),
            "cap_usd": self.hard_cap_usd,
            "calls": state.get("calls", 0),
            "by_label": {k: round(v, 4) for k, v in sorted(state.get("by_label", {}).items(), key=lambda kv: -kv[1])},
        }

    def total_spent(self) -> float:
        return self._read().get("total_usd", 0.0)

    def check(self, estimated_usd: float, run: "RunBudget | None" = None) -> None:
        """Refuse a call whose worst-case cost would break a cap."""
        if not self.paid_calls_enabled:
            raise BudgetExceeded("paid calls are disabled (DEMO_PAID_CALLS_ENABLED=false)")
        with self._lock:
            total = self._read().get("total_usd", 0.0)
        if total + estimated_usd > self.hard_cap_usd:
            raise BudgetExceeded(
                f"global cap ${self.hard_cap_usd:.2f} would be exceeded "
                f"(spent ${total:.4f}, call needs up to ${estimated_usd:.4f})"
            )
        if run is not None and run.spent + estimated_usd > run.cap_usd:
            raise BudgetExceeded(
                f"run cap ${run.cap_usd:.2f} would be exceeded "
                f"(run spent ${run.spent:.4f}, call needs up to ${estimated_usd:.4f})"
            )

    def record(self, actual_usd: float, label: str, run: "RunBudget | None" = None) -> None:
        with self._lock:
            state = self._read()
            state["total_usd"] = state.get("total_usd", 0.0) + actual_usd
            state["calls"] = state.get("calls", 0) + 1
            by_label = state.setdefault("by_label", {})
            by_label[label] = by_label.get(label, 0.0) + actual_usd
            self._write(state)
        if run is not None:
            run.spent += actual_usd
            run.calls += 1

    def new_run(self, cap_usd: float) -> "RunBudget":
        return RunBudget(cap_usd=cap_usd)

    def _read(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        os.replace(tmp, self.state_path)


@dataclass
class RunBudget:
    """Spend ceiling for a single agent run."""

    cap_usd: float
    spent: float = 0.0
    calls: int = 0
