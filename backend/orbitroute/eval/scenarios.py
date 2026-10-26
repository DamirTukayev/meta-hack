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
    zone: tuple[tuple[float, float], ...] = ()  # an avoided zone drawn as a polygon, like a user would on the map


def square(x: float, y: float, size: float = 350) -> tuple[tuple[float, float], ...]:
    return ((x, y), (x + size, y), (x + size, y + size), (x, y + size))


SCENARIOS: list[EvalScenario] = [
    # Zones drawn across the road network (squares of ~340 m, as a user would draw them). The solver does not know
    # about them on its first pass; whether its shortest paths cross them depends on the geometry.
    *[EvalScenario(f"mem-draw-A-{s}", "memphis", 30, 3, "13:00", (), seed=s, zone=square(200, 550)) for s in range(4)],
    *[EvalScenario(f"mem-draw-B-{s}", "memphis", 30, 3, "13:00", (), seed=s, zone=square(550, 200)) for s in range(3)],
    *[EvalScenario(f"col-draw-{s}", "columbus", 30, 3, "13:00", (), seed=s, zone=square(200, 550)) for s in range(3)],
    # Zones found by Muse Spark from the image ("avoid the industrial zone", ...)
    EvalScenario("col-ind-40-3", "columbus", 40, 3, "12:00", ("industrial",), seed=0),
    EvalScenario("col-com-20-2", "columbus", 20, 2, "11:00", ("commercial",), seed=0),
    EvalScenario("mem-ind-30-3", "memphis", 30, 3, "12:00", ("industrial",), seed=0),
    EvalScenario("mem-res-25-2", "memphis", 25, 2, "11:00", ("residential",), seed=1),
    EvalScenario("col-res-30-3", "columbus", 30, 3, "12:00", ("residential",), seed=0, note="the residential zone cuts off most streets"),
    EvalScenario("col-res-30-1-tight", "columbus", 30, 1, "09:00", ("residential",), seed=0, note="cut off, and one truck cannot finish anyway"),
    # Provably infeasible requests
    EvalScenario("inf-time-12-1", "columbus", 12, 1, "08:30", ("residential",), expect="infeasible", note="12 stops x 4 min = 48 min > 30 min"),
    EvalScenario("inf-time-50-3", "memphis", 50, 3, "09:00", ("industrial",), expect="infeasible", note="50 x 4 min / 3 trucks = 67 min > 60 min"),
    EvalScenario("inf-capacity-40", "columbus", 40, 3, "12:00", ("industrial",), capacity=10, expect="infeasible", note="3 trucks x 10 units < 40 orders"),
    EvalScenario("inf-capacity-24", "memphis", 24, 2, "12:00", ("industrial",), capacity=10, expect="infeasible", note="2 trucks x 10 units < 24 orders"),
]
