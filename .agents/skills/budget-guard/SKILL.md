---
name: budget-guard
description: Spend and secret protection for OrbitRoute — API credit limits, max_tokens, budget counter, rate limiting, model routing, .env handling. Use whenever writing or changing code that calls an LLM/vision/compute API, handles API keys, or touches deployment config.
---

# Budget and secrets guard

Credits are limited and the provider spend limit **only sends an email — it does not stop spending**. Protection must live in our code.

## Credits

| Service | Credit | Notes |
|---|---|---|
| Meta API | $150 | received |
| Baseten | $100 + 2M TPM | application submitted; model `meta-models/muse-spark-open-1026` |
| Modal | $100 | application submitted; **do not add a card for now** |
| Fireworks | optional | |

## Required in code

1. **`max_tokens` on every model call.** No call without an explicit cap.
2. **Budget counter.** A single module wraps all paid calls, records estimated cost per call (tokens × price), persists the running total, and **refuses calls once a hard cap is reached**. Set the cap well below the credit (e.g. 80%). Log spend per run.
3. **Rate limiting for the public demo.** Per-IP / per-session limits, a global daily ceiling, and a kill switch (env flag) that disables paid calls.
4. **Model routing.** Muse Glimmer for cheap, bulk steps; Muse Spark / Spark Open only for vision and reasoning. Prefer caching results of identical inputs.
5. **Bounded agent loop.** The verify → repair → re-solve loop has a max iteration count and a per-run cost ceiling. Never an unbounded loop that calls a paid model.
6. **No retries without backoff and a cap.**

## Secrets

- Keys live in `.env` only; `.env` is in `.gitignore`; commit `.env.example` with placeholder values.
- Keys are used on the **backend only** — never in frontend code, bundles, logs, error messages, screenshots or the demo video.
- Never print, echo or commit key values. If a key may have leaked, tell the user to rotate it immediately.
- The public repo must contain no secrets: check `git diff --staged` and history before pushing.

## User-side protections (remind, do not perform)

- Use a virtual card with a spend limit for any paid account.
- Do not add a card to Modal for now.
- Do not make purchases, upgrade plans, or enter payment details for the user.

## Before adding any new paid call

State the model, expected tokens per call, expected calls per demo run, and the resulting cost. If a typical demo run costs more than ~$0.50, propose a cheaper route first.
