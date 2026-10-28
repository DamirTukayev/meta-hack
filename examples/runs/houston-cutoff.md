# Houston, flooded streets, orders clicked freely: the water cuts most of them off

Sample `houston-harvey-b`, request: *"by 14:00, avoid the flooded areas"*, 16 orders, 3 trucks. Recorded answers only: no API key, no model call, so the repair choices and the recommendation come from the deterministic rules; with a key Muse Spark makes them.

## What the agent did

- `  1.8s` **perception**: Road graph: 185 nodes, 7.17 km of road
- `  1.8s` **scene**: 7 zones, 0 warehouses
- `  2.6s` **scene**: 63 flooded areas (16% of the photo)
- `  2.6s` **problem**: 16 orders, 3 trucks, avoiding flooded
- `  2.6s` **scenario**: depot and 16 orders placed on the roads (yours)
- `  5.6s` **solve**: solve #1: 16 orders on 2 trucks in 3.0s
- `  5.6s` **verify**: verification: 5/6 checks passed
- `  5.6s` **decision**: ban_violating_edges: Cut exactly the segments that entered the zone and re-solve.
- `  5.6s` **repair**: forbidding 34 road segments that entered the zone
- `  8.6s` **solve**: solve #2: 16 orders on 2 trucks in 3.0s
- `  8.6s` **verify**: verification: 4/6 checks passed
- `  8.6s` **decision**: propose_relaxation: 12 of 16 orders can only be reached through the avoided zone; dropping that many would not be a plan.
- ` 17.6s` **relaxation**: smallest fix: serve the 4 reachable orders now and leave the 12 cut-off ones (#1, #2, #5, #6, #7, #8, #9, #11 ...) for later
- ` 17.6s` **relaxation**: smallest fix: stop avoiding the flooded zone (the plan drives 2449 m through it)
- ` 17.6s` **recommendation**: recommended: serve the 4 reachable orders now and leave the 12 cut-off ones (#1, #2, #5, #6, #7, #8, #9, #11 ...) for later (It breaks no rule and serves the most orders of the options that keep every rule.)
- ` 17.6s` **result**: needs_relaxation

## Verification of the plan shown

| Check | Result | Detail |
|---|---|---|
| Every order is served exactly once | pass | 4/4 orders served, 12 excluded with reasons |
| Fleet size is respected | pass | 1/3 trucks used |
| Truck capacity is respected | pass | max load 4/8 |
| Every leg follows real roads | pass | all legs are connected road paths |
| All work finishes before the deadline | pass | last truck back at 08:20 (deadline 14:00) |
| Avoided zones are not entered | pass | no avoided zone entered |

**Outcome: needs_relaxation.** 4 orders served, last truck back at 08:20, 2.09 km.

Alternatives, each solved and verified:

1. serve the 4 reachable orders now and leave the 12 cut-off ones (#1, #2, #5, #6, #7, #8, #9, #11 ...) for later (recommended)
2. stop avoiding the flooded zone (the plan drives 2449 m through it)

Recommendation (policy): It breaks no rule and serves the most orders of the options that keep every rule.
