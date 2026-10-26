---
name: judging-focus
description: Judging criteria, bonus targets and agent-design priorities for OrbitRoute. Use when planning features, prioritizing work, designing the agent loop, choosing what goes in the demo, or deciding what to cut.
---

# Judging focus

**Standing goal: we are not building a simple project.** The organizers explicitly list "simple image analyzers" and basic wrappers as generic/banned. Aim for a deep, agent-first system that competes for the top 5 of the track (Stage 3: judges watch the video live). Before adding a feature, ask: does it raise Technical depth, Demo quality, Meta-tooling use or Impact? If not, cut it. See `hackathon-rules`.

| Criterion | Weight | What it means for OrbitRoute |
|---|---|---|
| Impact | 30% | A concrete, real use case (routing where maps are missing or outdated: new districts, disaster response, logistics). Back claims with real evidence, never invented stats. |
| Use of Meta AI tooling | 25% | Visibly use SAM 3.1 (segmentation), Muse Spark / Spark Open (vision + reasoning), Muse Glimmer (cheap bulk steps); Muse Voice Transcribe as bonus. Say what each does in README and video. |
| Demo | 25% | Works live, reliably, in 3 minutes. Prefer a smaller feature set that never fails over a large one that sometimes does. |
| Technical depth | 20% | Real agent loop, independent constraint verifier, graph extraction from masks, budget guard, evaluation on test scenarios. |

## Bonuses

- **Open Weight** (10k): prefer Spark Open / Glimmer on Baseten or Modal where quality allows (partner-verified); document it.
- **Agentic** (5k): judged on autonomy, effectiveness at the task and practical usefulness — the plan → solve → verify → repair → re-solve loop, with a visible agent log.
- **Most Viral** ($20k): a short, striking visual (image → masks → graph → routes) and an X post before Nov 8.

## Agent design principles

1. **Agent, not analyzer.** The image analysis is step 1 of many. The product is a *verified plan*.
2. **Verifier is independent of the solver.** It recomputes constraints from the output (time windows, capacities, forbidden zones, coverage of all orders) and does not trust the solver or the LLM.
3. **Repair is explicit.** On violation: diagnose → change constraints or inputs → re-solve → re-verify, with a bounded number of iterations, and a clear log line per step.
4. **Return only verified plans**, or an honest report of what could not be satisfied and why.
5. **Quantum (QAOA on a simulator) is optional** for tiny sub-problems. Do not let it take time from the core loop or the demo.
6. **Observable.** Every step emits structured events the UI can show (masks, graph, constraints, solver result, violations, fixes) — this feeds the demo and the video.

## Prioritization

1. Core path end-to-end first, even if crude: image → graph → constraints → solve → verify → map.
2. Then the repair loop with a reliable, reproducible violation case for the demo.
3. Then polish, evaluation numbers, README.
4. Then bonuses (voice, QAOA) — only if everything above is solid.

Cut anything that does not improve the 3-minute demo or a judged criterion.
