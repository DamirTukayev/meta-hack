# Houston after Hurricane Harvey: keep the trucks out of the flood

Sample `houston-harvey`, request: *"by 14:00, avoid the flooded areas"*, 20 orders, 3 trucks. Recorded answers only: no API key, no model call, so the repair choices and the recommendation come from the deterministic rules; with a key Muse Spark makes them.

## What the agent did

- `  2.1s` **perception**: Road graph: 421 nodes, 15.49 km of road
- `  2.2s` **scene**: 7 zones, 0 warehouses
- `  2.6s` **scene**: 28 flooded areas (20% of the photo)
- `  7.6s` **problem**: 20 orders, 3 trucks, avoiding flooded
- `  7.6s` **scenario**: depot and 20 orders placed, 20 of them at buildings found by SAM 3.1
- ` 10.6s` **solve**: solve #1: 20 orders on 3 trucks in 3.0s
- ` 10.6s` **verify**: verification: 6/6 checks passed
- ` 10.6s` **final**: plan verified
- ` 10.6s` **result**: verified

## Verification of the plan shown

| Check | Result | Detail |
|---|---|---|
| Every order is served exactly once | pass | 20/20 orders served |
| Fleet size is respected | pass | 3/3 trucks used |
| Truck capacity is respected | pass | max load 10/10 |
| Every leg follows real roads | pass | all legs are connected road paths |
| All work finishes before the deadline | pass | last truck back at 08:46 (deadline 14:00) |
| Avoided zones are not entered | pass | no avoided zone entered |

**Outcome: verified.** 20 orders served, last truck back at 08:46, 6.52 km.
