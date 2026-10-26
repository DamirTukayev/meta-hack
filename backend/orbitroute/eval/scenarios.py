"""The evaluation suite: fixed scenarios over the bundled tiles.

`expect="infeasible"` is used only where infeasibility follows from arithmetic alone (service time or
capacity), so the label does not depend on any model or solver. Everything else is `None`: we report
what happened without claiming a ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalScenario:
    id: str
    sample: str
    n_orders: int
    n_vehicles: int
    deadline: str
    avoid: tuple[str, ...]
    seed: int = 0
    capacity: int | None = None
    shift_start: str = "08:00"
    expect: str | None = None  # "infeasible" when arithmetic proves it
    note: str = ""


SCENARIOS: list[EvalScenario] = [
    # Columbus, OH: avoid residential (the first pass tends to cut through it)
    EvalScenario("col-res-30-3-a", "columbus", 30, 3, "12:00", ("residential",), seed=0),
    EvalScenario("col-res-30-3-b", "columbus", 30, 3, "12:00", ("residential",), seed=1),
    EvalScenario("col-res-30-3-c", "columbus", 30, 3, "12:00", ("residential",), seed=2),
    EvalScenario("col-res-20-2", "columbus", 20, 2, "10:00", ("residential",), seed=3),
    EvalScenario("col-res-45-3", "columbus", 45, 3, "11:00", ("residential",), seed=4),
    EvalScenario("col-res-30-1-tight", "columbus", 30, 1, "09:00", ("residential",), seed=0, note="one truck cannot finish"),
    # Columbus, OH: other zones
    EvalScenario("col-ind-40-3-a", "columbus", 40, 3, "12:00", ("industrial",), seed=0),
    EvalScenario("col-ind-40-3-b", "columbus", 40, 3, "12:00", ("industrial",), seed=1),
    EvalScenario("col-ind-25-2", "columbus", 25, 2, "10:00", ("industrial",), seed=2),
    EvalScenario("col-com-20-2", "columbus", 20, 2, "11:00", ("commercial",), seed=0),
    EvalScenario("col-resind-30-3", "columbus", 30, 3, "12:00", ("residential", "industrial"), seed=0),
    # Memphis, TN: a logistics district where industrial covers ~44% of the tile
    EvalScenario("mem-ind-30-3-a", "memphis", 30, 3, "12:00", ("industrial",), seed=0),
    EvalScenario("mem-ind-30-3-b", "memphis", 30, 3, "12:00", ("industrial",), seed=1),
    EvalScenario("mem-ind-30-3-c", "memphis", 30, 3, "12:00", ("industrial",), seed=2),
    EvalScenario("mem-ind-20-2", "memphis", 20, 2, "09:30", ("industrial",), seed=3),
    EvalScenario("mem-res-25-2", "memphis", 25, 2, "11:00", ("residential",), seed=1),
    # Provably infeasible requests
    EvalScenario("inf-time-12-1", "columbus", 12, 1, "08:30", ("residential",), expect="infeasible", note="12 stops x 4 min = 48 min > 30 min"),
    EvalScenario("inf-time-50-3", "memphis", 50, 3, "09:00", ("industrial",), expect="infeasible", note="50 x 4 min / 3 trucks = 67 min > 60 min"),
    EvalScenario("inf-capacity-40", "columbus", 40, 3, "12:00", ("industrial",), capacity=10, expect="infeasible", note="3 trucks x 10 units < 40 orders"),
    EvalScenario("inf-capacity-24", "memphis", 24, 2, "12:00", ("industrial",), capacity=10, expect="infeasible", note="2 trucks x 10 units < 24 orders"),
]
