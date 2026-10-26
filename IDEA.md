# OrbitRoute — Idea

**Track:** Push the Frontier

An AI agent that turns a satellite image and a natural-language request into a verified delivery plan.

## How it works

1. **SAM 3.1** segments roads, warehouses and drop points in the image; a graph is built from them.
2. **Muse Spark** translates the request ("40 orders, 3 trucks, by 18:00, avoid the industrial zone") into formal CVRP constraints.
3. A **VRP solver** (OR-Tools / PyVRP) builds the routes.
4. **The agent verifies the solution**, fixes violated constraints and re-solves on its own.
5. Everything is shown on a map. Voice input via **Muse Voice Transcribe** is a bonus.

## Quantum part

QAOA on a simulator for small sub-problems is an option, not the centerpiece of the demo.

## Notes

- Solver code is written from scratch during the hackathon, to stay clear of the "new work only" rule.
- The emphasis is the agent loop (build → verify → fix → re-solve), not image analysis. See the rules in [REQUIREMENTS.md](REQUIREMENTS.md).

## Open question

Which intro to publish: detailed, or without pipeline details. Depends on whether a team is being sought.
