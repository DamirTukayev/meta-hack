# Quantum polishing on the evaluation scenarios

**QAOA simulated on CPU (state vector), not quantum hardware.** Every QAOA number below comes from an exact state-vector simulation on a CPU; no quantum hardware and no cloud
service was used. Simulated annealing and brute force run on the same CPU.

What was run: the verified plans of the fixed evaluation suite (`orbitroute/eval/scenarios.py`, the 62 scenarios of
`scripts/run_eval.py`, built by the same code) are cut into anchored segments of at most 4 stops (16 qubits); each segment is re-ordered by a path QUBO and replaced only when its
travel cost goes down; the polished plan then goes through the same verifier and the independent audit.

- Scenarios with a verified plan: 42 of 62 as stated (`min_time`), 42 with the objective switched to `min_distance`. The others end without a verified plan (mostly `needs_relaxation`), so there is nothing to polish.
- Starting plans: **strong** = the agent's verified plan (PyVRP, 3 s); **weak** = the same trucks with the same stops, each route re-ordered by nearest neighbour from the depot (a PyVRP run with a 0.05 s limit was tried first and returned the same plan as the 3 s run, so it gave nothing to improve).
- Solvers: `exact` (brute force over the m! orders, the quality ceiling), `sa` (100 reads × 1000 sweeps), `qaoa_p1`, `qaoa_p2` (1000 shots; angles by a 12 × 8 grid + COBYLA, optimised once per segment size per plan and reused for the other segments of that size). Penalty A = 2.0 × the largest arc cost of the segment.
- Seeds 0, 1, 2 for `sa` and QAOA (QAOA angles are deterministic; the seed changes the measurement samples). Values are mean ± standard deviation over the seeds.
- Total run time: 51.6 min on arm64 (Python 3.13.5), single process.

## Objective `min_time` (cost = travel time)

| solver | initial | segments | qubits/segment | P_feas | optimum found, % | accepted swaps | cost change, % | verifier reverts | s/segment |
|---|---|---|---|---|---|---|---|---|---|
| exact | strong | 312 | 13.8 | — (no sampling) | 100.0 | 0.0 | 0.000 | 0.0 | 0.0000 |
| sa | strong | 312 ± 0 | 13.8 ± 0.0 | 1.000 ± 0.000 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.000 ± 0.000 | 0.0 ± 0.0 | 0.1609 ± 0.0016 |
| qaoa_p1 | strong | 312 ± 0 | 13.8 ± 0.0 | 0.061 ± 0.001 | 69.0 ± 2.5 | 0.0 ± 0.0 | 0.000 ± 0.000 | 0.0 ± 0.0 | 0.1051 ± 0.0012 |
| qaoa_p2 | strong | 312 ± 0 | 13.8 ± 0.0 | 0.099 ± 0.000 | 79.3 ± 3.0 | 0.0 ± 0.0 | 0.000 ± 0.000 | 0.0 ± 0.0 | 0.2256 ± 0.0021 |
| exact | weak | 312 | 13.8 | — (no sampling) | 100.0 | 76.0 | -0.783 | 0.0 | 0.0000 |
| sa | weak | 312 ± 0 | 13.8 ± 0.0 | 1.000 ± 0.000 | 100.0 ± 0.0 | 76.0 ± 0.0 | -0.782 ± 0.001 | 0.0 ± 0.0 | 0.1615 ± 0.0057 |
| qaoa_p1 | weak | 312 ± 0 | 13.8 ± 0.0 | 0.061 ± 0.001 | 68.3 ± 1.6 | 57.0 ± 0.0 | -0.673 ± 0.038 | 0.0 ± 0.0 | 0.1046 ± 0.0021 |
| qaoa_p2 | weak | 312 ± 0 | 13.8 ± 0.0 | 0.100 ± 0.001 | 82.4 ± 0.5 | 66.0 ± 1.6 | -0.707 ± 0.015 | 0.0 ± 0.0 | 0.2282 ± 0.0036 |

## Objective `min_distance` (cost = distance)

| solver | initial | segments | qubits/segment | P_feas | optimum found, % | accepted swaps | cost change, % | verifier reverts | s/segment |
|---|---|---|---|---|---|---|---|---|---|
| exact | strong | 312 | 13.9 | — (no sampling) | 100.0 | 0.0 | 0.000 | 0.0 | 0.0000 |
| sa | strong | 312 ± 0 | 13.9 ± 0.0 | 1.000 ± 0.000 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.000 ± 0.000 | 0.0 ± 0.0 | 0.1636 ± 0.0046 |
| qaoa_p1 | strong | 312 ± 0 | 13.9 ± 0.0 | 0.058 ± 0.001 | 67.6 ± 1.6 | 0.0 ± 0.0 | 0.000 ± 0.000 | 0.0 ± 0.0 | 0.1238 ± 0.0014 |
| qaoa_p2 | strong | 312 ± 0 | 13.9 ± 0.0 | 0.095 ± 0.001 | 82.6 ± 0.8 | 0.0 ± 0.0 | 0.000 ± 0.000 | 0.0 ± 0.0 | 0.2774 ± 0.0056 |
| exact | weak | 312 | 13.9 | — (no sampling) | 100.0 | 69.0 | -1.053 | 0.0 | 0.0000 |
| sa | weak | 312 ± 0 | 13.9 ± 0.0 | 1.000 ± 0.000 | 100.0 ± 0.0 | 69.0 ± 0.0 | -1.053 ± 0.000 | 0.0 ± 0.0 | 0.1638 ± 0.0031 |
| qaoa_p1 | weak | 312 ± 0 | 13.9 ± 0.0 | 0.062 ± 0.001 | 67.4 ± 0.6 | 47.7 ± 0.5 | -0.878 ± 0.033 | 0.0 ± 0.0 | 0.1183 ± 0.0016 |
| qaoa_p2 | weak | 312 ± 0 | 13.9 ± 0.0 | 0.102 ± 0.001 | 82.7 ± 2.5 | 60.0 ± 2.4 | -0.970 ± 0.040 | 0.0 ± 0.0 | 0.2654 ± 0.0047 |

## What the verifier rejected

None: all 1680 polished plans whose starting plan passed the verifier passed it again.

This was expected to differ under `min_distance`, where a segment that is shorter in metres can take longer and push a truck past the deadline; on these scenarios it never did. The revert path (verifier rejects the polished plan, the agent keeps the classical one and logs `revert_quantum`) is therefore exercised only by a unit test (`test_failed_polish_is_reverted_to_the_classical_plan`), not by this evaluation.

## Verifier vs. independent audit

On all 1680 polished plans the verifier and the independent audit (`verifier/independent.py`) disagreed on 0.

## QAOA: probability of a valid order, by segment size

| solver | qubits | segments | P_feas (samples) | P_feas (exact, from the state) | optimum found, % |
|---|---|---|---|---|---|
| qaoa_p1 | 4 | 294 | 0.439 | 0.435 | 100.0 |
| qaoa_p1 | 9 | 636 | 0.091 | 0.089 | 100.0 |
| qaoa_p1 | 16 | 2814 | 0.014 | 0.014 | 57.5 |
| qaoa_p2 | 4 | 294 | 0.668 | 0.665 | 100.0 |
| qaoa_p2 | 9 | 636 | 0.153 | 0.149 | 100.0 |
| qaoa_p2 | 16 | 2814 | 0.027 | 0.027 | 75.7 |

A random 16-bit string is a valid 4 × 4 permutation matrix with probability 24/65536 ≈ 0.0004, 3 × 3: 6/512 ≈ 0.012, 2 × 2: 2/16 = 0.125.

## Limits

- QAOA is simulated exactly on a CPU (state vector); a real device adds noise and readout error, so these P_feas values are an upper bound for the same circuits.
- Segments are at most 4 stops (16 qubits) with both ends fixed: polishing can only re-order stops inside a segment, never move a stop between segments or trucks, so it cannot fix what the segmentation does not see.
- The scenarios are synthetic: fixed random orders on four bundled aerial tiles (two USGS NAIP, two NOAA flood imagery), road graphs read from recorded SAM 3.1 masks; the deadline is shared by all orders.
- One author built the scenarios, the solvers and this evaluation; nothing was tuned on these numbers, and every scenario with a verified plan is reported.

Reproduce: `uv run python scripts/eval_quantum.py` (CPU only, no API key needed). Raw per-segment records: `eval/quantum.json`.
