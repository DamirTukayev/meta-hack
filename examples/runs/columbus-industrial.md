# Columbus, OH: the plan crosses the industrial zone, the agent repairs it

Sample `columbus`, request: *"by 12:00, avoid the industrial zone"*, 20 orders, 3 trucks. Recorded answers only: no API key, no model call, so the repair choices and the recommendation come from the deterministic rules; with a key Muse Spark makes them.

## What the agent did

- `  2.6s` **perception**: Road graph: 518 nodes, 19.18 km of road
- `  2.6s` **scene**: 6 zones, 4 warehouses
- `  5.8s` **problem**: 20 orders, 3 trucks, avoiding industrial
- `  5.8s` **scenario**: depot and 20 orders placed, 20 of them at buildings found by SAM 3.1
- `  8.8s` **solve**: solve #1: 20 orders on 2 trucks in 3.0s
- `  8.8s` **verify**: verification: 5/6 checks passed
- `  8.8s` **decision**: ban_violating_edges: Cut exactly the segments that entered the zone and re-solve.
- `  8.8s` **repair**: forbidding 3 road segments that entered the zone
- ` 11.8s` **solve**: solve #2: 20 orders on 2 trucks in 3.0s
- ` 11.8s` **verify**: verification: 6/6 checks passed
- ` 11.8s` **final**: plan verified
- ` 11.8s` **result**: verified

## Verification of the plan shown

| Check | Result | Detail |
|---|---|---|
| Every order is served exactly once | pass | 20/20 orders served |
| Fleet size is respected | pass | 2/3 trucks used |
| Truck capacity is respected | pass | max load 10/10 |
| Every leg follows real roads | pass | all legs are connected road paths |
| All work finishes before the deadline | pass | last truck back at 09:00 (deadline 12:00) |
| Avoided zones are not entered | pass | no avoided zone entered |

**Outcome: verified.** 20 orders served, last truck back at 09:00, 18.5 km.
