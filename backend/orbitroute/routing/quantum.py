"""Quantum polishing (experimental, off by default): re-order short stretches of a verified plan by solving a QUBO.

The plan PyVRP built is cut, route by route, into consecutive segments of at most `m_seg` stops. Each segment keeps its two ends
fixed (the stop before it, or the depot, and the stop after it, or the depot), the "anchored segmentation" of section 4.6.4 of the
author's master's thesis, and the order of the stops in between is the solution of a path QUBO: one-hot "stop x position",
m^2 binary variables. The QUBO is solved by QAOA, simulated on CPU with an exact state vector, by simulated annealing, or by
brute force as the reference. A segment is replaced only when its travel cost goes down.

This stage does not check deadlines, zones or anything else: it compares only the objective (travel time or distance). Whether
the polished plan is still valid is decided by the same verifier that checked the classical plan.

QAOA here is simulated on CPU (state vector), not run on quantum hardware. The QUBO, the simulator and the annealer are ported
from the thesis experiment script (hybrid_experiment.py) with the same formulas; only names and interfaces changed.
"""

from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, field, replace
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

from orbitroute.routing.matrix import CostMatrix
from orbitroute.routing.scenario import Scenario
from orbitroute.routing.solver import Plan, rebuild_route

HARDWARE_NOTE = "QAOA simulated on CPU (state vector), not quantum hardware"
SOLVERS = ("qaoa_p1", "qaoa_p2", "sa", "exact")
MAX_M_SEG = 4  # 16 qubits; 5 stops would be 25 qubits, a 512 MB state vector per copy
TOL = 1e-9
GAMMA_GRID = np.linspace(0.5, 20.0, 12)
BETA_GRID = np.linspace(0.1, np.pi / 2, 8)


# ---------------------------------------------------------------------------------------------------------------------------------
# QUBO model
# ---------------------------------------------------------------------------------------------------------------------------------
class QUBO:
    """E(x) = const + sum_i a_i x_i + sum_{i<j} b_ij x_i x_j over binary x."""

    def __init__(self, n: int):
        self.n = n
        self.const = 0.0
        self.lin = np.zeros(n)
        self.quad: dict[tuple[int, int], float] = {}

    def add_linear(self, i: int, a: float) -> None:
        self.lin[i] += a

    def add_pair(self, i: int, j: int, b: float) -> None:
        if i == j:  # x_i * x_i = x_i
            self.lin[i] += b
            return
        key = (i, j) if i < j else (j, i)
        self.quad[key] = self.quad.get(key, 0.0) + b

    def add_square(self, terms: Sequence[tuple[int, float]], const: float, weight: float) -> None:
        """Add weight * (const + sum w_i x_i)^2, expanded with x_i^2 = x_i (how the one-hot penalties are written)."""
        agg: dict[int, float] = {}
        for i, w in terms:
            agg[i] = agg.get(i, 0.0) + w
        items = [(i, w) for i, w in agg.items() if w != 0.0]
        self.const += weight * const * const
        for i, w in items:
            self.lin[i] += weight * (2.0 * const * w + w * w)
        for (i, wi), (j, wj) in itertools.combinations(items, 2):
            self.add_pair(i, j, 2.0 * weight * wi * wj)

    def energy(self, x) -> float:
        x = np.asarray(x, dtype=float)
        e = self.const + float(self.lin @ x)
        for (i, j), b in self.quad.items():
            e += b * x[i] * x[j]
        return e

    def all_energies(self) -> np.ndarray:
        """Energies of all 2^n bit strings; bit v of the index z is x_v. Built by doubling, O(2^n)."""
        if self.n > 26:
            raise ValueError(f"{self.n} variables: enumerating all energies is not possible")
        lower: list[list[tuple[int, float]]] = [[] for _ in range(self.n)]
        for (i, j), b in self.quad.items():
            lower[j].append((i, b))  # i < j
        E = np.array([self.const])
        for v in range(self.n):
            S = np.full(1 << v, self.lin[v])  # a_v + sum_{u<v} b_uv x_u over all strings of v bits
            for u, b in lower[v]:
                S.reshape(-1, 2, 1 << u)[:, 1, :] += b
            E = np.concatenate([E, E + S])
        return E

    def sym_matrix(self) -> np.ndarray:
        B = np.zeros((self.n, self.n))
        for (i, j), b in self.quad.items():
            B[i, j] += b
            B[j, i] += b
        return B


def bits_of(z: int, n: int) -> np.ndarray:
    return (int(z) >> np.arange(n)) & 1


def path_qubo(nodes: Sequence[int], start: int, end: int, C: np.ndarray, A: float) -> QUBO:
    """Path start -> (nodes in some order) -> end with both ends fixed. Variable x_{i,t} (stop nodes[i] at position t) has index
    i*m + t. Cost terms: C[start, a] at position 0, C[a, b] between neighbouring positions, C[b, end] at position m-1. Penalties
    A * (1 - sum_t x_it)^2 per stop and A * (1 - sum_i x_it)^2 per position make every low-energy string a permutation matrix."""
    m = len(nodes)
    q = QUBO(m * m)
    for i, a in enumerate(nodes):
        q.add_linear(i * m, float(C[start, a]))
        q.add_linear(i * m + m - 1, float(C[a, end]))
    for t in range(m - 1):
        for i, a in enumerate(nodes):
            for j, b in enumerate(nodes):
                if i != j:
                    q.add_pair(i * m + t, j * m + t + 1, float(C[a, b]))
    for i in range(m):  # each stop at exactly one position
        q.add_square([(i * m + t, -1.0) for t in range(m)], 1.0, A)
    for t in range(m):  # each position holds exactly one stop
        q.add_square([(i * m + t, -1.0) for i in range(m)], 1.0, A)
    return q


def decode_path(x, nodes: Sequence[int]) -> tuple[list[int], bool]:
    """Bit string -> (stops in position order, True) when the m x m "stop x position" matrix is a permutation, else ([], False).
    No repair: an infeasible string is reported as such."""
    m = len(nodes)
    M = np.asarray(x).reshape(m, m)
    if (M.sum(axis=0) == 1).all() and (M.sum(axis=1) == 1).all():
        return [nodes[int(np.argmax(M[:, t]))] for t in range(m)], True
    return [], False


def path_cost(order: Sequence[int], start: int, end: int, C: np.ndarray) -> int:
    seq = [start, *order, end]
    return int(sum(int(C[a, b]) for a, b in zip(seq, seq[1:])))


def path_arc_max(nodes: Sequence[int], start: int, end: int, C: np.ndarray) -> float:
    arcs = [C[start, a] for a in nodes] + [C[a, b] for a in nodes for b in nodes if a != b] + [C[a, end] for a in nodes]
    return float(max(arcs)) if arcs else 0.0


# ---------------------------------------------------------------------------------------------------------------------------------
# QAOA, simulated exactly with a state vector on CPU
# ---------------------------------------------------------------------------------------------------------------------------------
class QAOASimulator:
    """Exact state-vector simulation of QAOA for a diagonal cost Hamiltonian given by its 2^n energies (normalised to [0, 1])."""

    GROUP = 5  # the mixer is applied to blocks of up to 5 qubits at once (RX(beta)^{x5}, a 32 x 32 matrix)

    def __init__(self, energies: np.ndarray):
        size = energies.size
        self.n = size.bit_length() - 1
        e_min, e_max = float(energies.min()), float(energies.max())
        span = e_max - e_min if e_max - e_min > TOL else 1.0
        self.e_norm = (energies - e_min) / span
        self.levels, inv = np.unique(self.e_norm, return_inverse=True)  # one phase factor per distinct energy level
        self.inv = inv.ravel().astype(np.int32)
        self._psi = np.empty(size, dtype=np.complex128)
        self._buf = np.empty(size, dtype=np.complex128)
        self.nfev = 0

    def _mix(self, src: np.ndarray, dst: np.ndarray, beta: float) -> tuple[np.ndarray, np.ndarray]:
        """Mixer e^{-i beta H_M} = prod_k RX_k(beta), applied g neighbouring qubits at a time. Returns (result, free buffer)."""
        c, s = math.cos(beta), -1j * math.sin(beta)
        r = np.array([[c, s], [s, c]], dtype=np.complex128)
        k = 0
        while k < self.n:
            g = min(self.GROUP, self.n - k)
            M = r
            for _ in range(g - 1):
                M = np.kron(M, r)
            G = 1 << g
            if k == 0:
                np.matmul(src.reshape(-1, G), M, out=dst.reshape(-1, G))  # M is symmetric
            else:
                np.matmul(M, src.reshape(-1, G, 1 << k), out=dst.reshape(-1, G, 1 << k))
            src, dst = dst, src
            k += g
        return src, dst

    def state(self, params) -> np.ndarray:
        """|gamma, beta> = prod_l e^{-i beta_l H_M} e^{-i gamma_l H_C} |+>^n (returns an internal buffer)."""
        params = np.asarray(params, dtype=float)
        p = len(params) // 2
        psi, free = self._psi, self._buf
        psi.fill((1 << self.n) ** -0.5)
        for gamma, beta in zip(params[:p], params[p:]):
            psi *= np.exp(-1j * gamma * self.levels)[self.inv]
            psi, free = self._mix(psi, free, beta)
        return psi

    def probabilities(self, params) -> np.ndarray:
        psi = self.state(params)
        prob = psi.real**2 + psi.imag**2
        return prob / prob.sum()

    def expectation(self, params) -> float:
        """F_p(gamma, beta) = sum_z |psi(z)|^2 * E_norm(z)."""
        self.nfev += 1
        psi = self.state(params)
        return float(np.vdot(psi, self.e_norm * psi).real)


def optimize_qaoa(sim: QAOASimulator, p_list: Sequence[int], maxiter: int = 200) -> dict[int, np.ndarray]:
    """p = 1: a 12 x 8 grid over (gamma, beta), then COBYLA. p > 1: start from depth p-1 with its last angles repeated, then COBYLA."""
    out: dict[int, np.ndarray] = {}
    for p in range(1, max(p_list) + 1):
        if p == 1:
            best = min(((sim.expectation([g, b]), np.array([g, b])) for g in GAMMA_GRID for b in BETA_GRID), key=lambda fb: fb[0])
            f0, x0 = best
        else:
            prev = out[p - 1]
            g, b = prev[: p - 1], prev[p - 1 :]
            x0 = np.concatenate([g, g[-1:], b, b[-1:]])
            f0 = sim.expectation(x0)
        res = minimize(sim.expectation, x0, method="COBYLA", options={"maxiter": maxiter})
        out[p] = np.asarray(res.x, dtype=float) if res.fun <= f0 else x0
    return out


@dataclass
class QAOAResult:
    samples: np.ndarray  # shots x n bits
    params: dict[int, np.ndarray]  # angles per depth
    optimized: bool  # False when the angles were transferred from an earlier segment of the same size
    prob: np.ndarray  # |psi(z)|^2 of the final state: the caller sums it over the valid strings for the exact P_feas


def solve_qaoa(
    q: QUBO, p_list: Sequence[int], shots: int, seed: int, maxiter: int = 200, params: dict[int, np.ndarray] | None = None
) -> QAOAResult:
    """Optimise the angles for the depths in `p_list` (or reuse `params`, parameter transfer), then draw `shots` measurement
    samples from the state of the deepest one."""
    sim = QAOASimulator(q.all_energies())
    optimized = params is None or max(p_list) not in params
    if optimized:
        params = optimize_qaoa(sim, p_list, maxiter)
    prob = sim.probabilities(params[max(p_list)])
    rng = np.random.default_rng(seed)
    z = rng.choice(prob.size, size=shots, p=prob)
    samples = ((z[:, None] >> np.arange(q.n)[None, :]) & 1).astype(np.int8)
    return QAOAResult(samples, params, optimized, prob)


# ---------------------------------------------------------------------------------------------------------------------------------
# Simulated annealing on the same QUBO
# ---------------------------------------------------------------------------------------------------------------------------------
def sa_temperatures(q: QUBO) -> tuple[float, float]:
    """T_hot = 0.5 * max_i(|a_i| + sum_j |b_ij|), T_cold = 0.05 * the smallest non-zero |coefficient|."""
    a, absB = q.lin, np.abs(q.sym_matrix())
    t_hot = 0.5 * float(np.max(np.abs(a) + absB.sum(axis=1)))
    coefs = np.concatenate([np.abs(a), absB[np.triu_indices(q.n, 1)]])
    coefs = coefs[coefs > TOL]
    t_cold = 0.05 * float(coefs.min()) if coefs.size else 1e-3
    return max(t_hot, t_cold), t_cold


def solve_sa(q: QUBO, reads: int = 100, sweeps: int = 1000, seed: int = 0) -> np.ndarray:
    """Single-flip Metropolis annealing on a geometric schedule, `reads` independent runs at once. Returns final states (reads x n)."""
    rng = np.random.default_rng(seed)
    n = q.n
    a, B = q.lin, q.sym_matrix()
    t_hot, t_cold = sa_temperatures(q)
    X = rng.integers(0, 2, size=(reads, n)).astype(float)
    H = a[None, :] + X @ B  # local fields h_i = a_i + sum_j b_ij x_j
    for T in np.geomspace(t_hot, t_cold, sweeps):
        order = rng.permutation(n)
        U = rng.random((n, reads))
        for step in range(n):
            i = order[step]
            d = 1.0 - 2.0 * X[:, i]
            dE = d * H[:, i]
            acc = (dE <= 0.0) | (U[step] < np.exp(-np.maximum(dE, 0.0) / T))
            if acc.any():
                idx = np.flatnonzero(acc)
                X[idx, i] += d[idx]
                H[idx] += d[idx, None] * B[i][None, :]
    return X.astype(np.int8)


# ---------------------------------------------------------------------------------------------------------------------------------
# Polishing a plan
# ---------------------------------------------------------------------------------------------------------------------------------
@dataclass
class SegmentResult:
    vehicle: int
    orders: list[int]  # matrix rows of the segment, in PyVRP's order
    start: int  # matrix row of the fixed start (0 = depot)
    end: int  # matrix row of the fixed end (0 = depot)
    qubits: int
    solver: str  # "qaoa_p1" | "qaoa_p2" | "sa" | "exact"
    feasible_share: float  # share of samples that encode a valid permutation (P_feas); 1.0 for "exact", which does not sample
    found_optimum: bool  # the best feasible sample is the brute-force optimum (m! <= 24)
    cost_before: int
    cost_after: int  # the cost kept: the new one when accepted, else cost_before
    accepted: bool  # whether the segment was replaced
    seconds: float
    orders_after: list[int] = field(default_factory=list)  # the order kept (equal to `orders` when not accepted)
    best_found_cost: int | None = None  # cost of the best feasible sample, None when no sample was feasible
    optimum_cost: int = 0
    p_feasible_exact: float | None = None  # QAOA only: total probability of the valid strings in the final state
    params_transferred: bool = False  # QAOA only: the angles came from an earlier segment of the same size


@dataclass
class QuantumReport:
    solver: str
    m_seg: int
    segments: list[SegmentResult]
    cost_before: int
    cost_after: int
    objective: str = "min_time"  # what the costs measure: travel seconds for min_time, metres for min_distance
    shots: int = 0
    sa_reads: int = 0
    sa_sweeps: int = 0
    params_transfer: bool = False  # QAOA angles optimised once per segment size and reused for the other segments of that size
    reverted: bool = False  # the verifier rejected the polished plan and the classical plan was kept
    failed_checks: list[str] = field(default_factory=list)
    seconds: float = 0.0
    note: str = HARDWARE_NOTE

    @property
    def accepted(self) -> int:
        return sum(s.accepted for s in self.segments)

    @property
    def unit(self) -> str:
        return "s" if self.objective == "min_time" else "m"


def segments_of(stops: list[int], m_seg: int) -> list[tuple[int, int]]:
    """(first index, length) of consecutive chunks of at most m_seg stops."""
    return [(k, min(m_seg, len(stops) - k)) for k in range(0, len(stops), m_seg)]


def polish_plan(
    plan: Plan,
    scenario: Scenario,
    matrix: CostMatrix,
    *,
    solver: str = "qaoa_p1",
    m_seg: int = 4,
    penalty_factor: float = 2.0,
    shots: int = 1000,
    seed: int = 0,
    sa_reads: int = 100,
    sa_sweeps: int = 1000,
    maxiter: int = 200,
) -> tuple[Plan, QuantumReport]:
    if solver not in SOLVERS:
        raise ValueError(f"unknown polishing solver {solver!r}; expected one of {', '.join(SOLVERS)}")
    if m_seg > MAX_M_SEG:
        raise ValueError(
            f"segment size {m_seg} needs {m_seg * m_seg} qubits; the CPU state-vector simulation is limited to "
            f"m_seg <= {MAX_M_SEG} ({MAX_M_SEG * MAX_M_SEG} qubits): {m_seg * m_seg} qubits would need a 2^{m_seg * m_seg}-amplitude state vector"
        )
    if m_seg < 2:
        raise ValueError("segment size must be at least 2: a single stop has only one order")
    t_all = time.perf_counter()
    objective = scenario.problem.objective
    C = matrix.time_s if objective == "min_time" else matrix.dist_m
    p_depth = int(solver[len("qaoa_p") :]) if solver.startswith("qaoa_p") else 0
    transfer: dict[int, dict[int, np.ndarray]] = {}  # segment size -> QAOA angles per depth
    seg_counter = 0
    results: list[SegmentResult] = []
    routes = []
    total_before = total_after = 0
    for r in plan.routes:
        order = [s.order for s in r.stops]
        before_route = path_cost(order, 0, 0, C) if order else 0
        changed = False
        for k, m in segments_of(order, m_seg):
            if m < 2:
                continue
            t0 = time.perf_counter()
            nodes = order[k : k + m]
            start = order[k - 1] if k > 0 else 0
            end = order[k + m] if k + m < len(order) else 0
            cost_before = path_cost(nodes, start, end, C)
            perms = list(itertools.permutations(nodes))
            costs = [path_cost(o, start, end, C) for o in perms]
            opt_cost = min(costs)
            seg_seed = seed * 100_003 + seg_counter
            seg_counter += 1
            p_exact = None
            transferred = False
            if solver == "exact":
                best, share = list(perms[int(np.argmin(costs))]), 1.0
            else:
                q = path_qubo(nodes, start, end, C, penalty_factor * path_arc_max(nodes, start, end, C))
                if solver == "sa":
                    samples = solve_sa(q, sa_reads, sa_sweeps, seg_seed)
                else:
                    prev = transfer.get(m)
                    res = solve_qaoa(q, list(range(1, p_depth + 1)), shots, seg_seed, maxiter, params=prev)
                    transferred = not res.optimized
                    transfer.setdefault(m, res.params)
                    feas_idx = [sum(1 << (i * m + t) for t, i in enumerate(pi)) for pi in itertools.permutations(range(m))]
                    p_exact = float(res.prob[feas_idx].sum())
                    samples = res.samples
                decoded = [decode_path(x, nodes) for x in samples]
                feasible = [o for o, ok in decoded if ok]
                share = len(feasible) / len(samples)
                best = min(feasible, key=lambda o: path_cost(o, start, end, C)) if feasible else None
            best_cost = path_cost(best, start, end, C) if best is not None else None
            accepted = best_cost is not None and best_cost < cost_before
            if accepted:
                order[k : k + m] = best
                changed = True
            results.append(
                SegmentResult(
                    vehicle=r.vehicle, orders=list(nodes), start=start, end=end, qubits=m * m, solver=solver,
                    feasible_share=share, found_optimum=best_cost is not None and best_cost <= opt_cost,
                    cost_before=cost_before, cost_after=best_cost if accepted else cost_before, accepted=accepted,
                    seconds=time.perf_counter() - t0, orders_after=list(best) if accepted else list(nodes),
                    best_found_cost=best_cost, optimum_cost=opt_cost, p_feasible_exact=p_exact, params_transferred=transferred,
                )
            )
        after_route = path_cost(order, 0, 0, C) if order else 0
        total_before += before_route
        total_after += after_route
        routes.append(rebuild_route(r, order, scenario, matrix) if changed else r)
    new_plan = replace(
        plan,
        routes=routes,
        feasible=all(r.time_warp_s == 0 for r in routes),
        cost=plan.cost - (total_before - total_after) if plan.cost >= 0 else plan.cost,  # PyVRP's cost moves by the travel saved
    )
    report = QuantumReport(
        solver=solver, m_seg=m_seg, segments=results, cost_before=total_before, cost_after=total_after, objective=objective,
        shots=shots if p_depth else 0, sa_reads=sa_reads if solver == "sa" else 0, sa_sweeps=sa_sweeps if solver == "sa" else 0,
        params_transfer=bool(p_depth), seconds=time.perf_counter() - t_all,
    )
    return new_plan, report


def summary(rep: QuantumReport) -> dict:
    """The numbers the agent log and the UI show."""
    segs = rep.segments
    sampled = [s for s in segs if s.solver != "exact"]
    return {
        "solver": rep.solver,
        "m_seg": rep.m_seg,
        "segments": len(segs),
        "qubits_max": max((s.qubits for s in segs), default=0),
        "qubits": sorted({s.qubits for s in segs}),
        "p_feas": round(float(np.mean([s.feasible_share for s in sampled])), 3) if sampled else None,
        "optimum_found": sum(s.found_optimum for s in segs),
        "accepted": rep.accepted,
        "cost_before": rep.cost_before,
        "cost_after": rep.cost_after,
        "objective": rep.objective,
        "unit": rep.unit,
        "params_transfer": rep.params_transfer,
        "reverted": rep.reverted,
        "failed_checks": rep.failed_checks,
        "seconds": round(rep.seconds, 2),
        "note": rep.note,
    }
