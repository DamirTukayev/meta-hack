# OrbitRoute — Agent Instructions

Read by Codex (and Claude Code via `CLAUDE.md`). Hackathon project: an agent that turns a satellite image + a natural-language request into a verified delivery plan. See `IDEA.md` and `REQUIREMENTS.md`.

## Always

- **Write everything in English**: code, comments, commits, docs, README, UI text. (Chat with the user may be in Russian.)
- Follow the skills in `.agents/skills/` (mirrored at `.claude/skills/`):
  - `hackathon-rules` — new work only, public repo, data licensing, README honesty, deadlines
  - `budget-guard` — `max_tokens`, budget counter, rate limits, secrets in `.env`, backend only
  - `living-docs` — keep `VIDEO_SCRIPT.md`, `PROJECT_CV.md`, `README.md` in sync after every finished feature
  - `judging-focus` — judging weights, bonuses, agent-first design
- After finishing a feature or measuring a metric, update `VIDEO_SCRIPT.md` and `PROJECT_CV.md` before reporting done.
- Never invent metrics or claim unbuilt features.
- Never commit secrets. Never publish, submit or spend money for the user without explicit confirmation.

## Key facts

- Track: Push the Frontier, Indie, solo. Commits only from Oct 26, 2026.
- Build window Oct 27 – Nov 4; deadline **Nov 5, 06:00 (UTC+5)**.
- Models: SAM 3.1 (segmentation), Muse Spark / Spark Open (vision + reasoning), Muse Glimmer (cheap bulk steps).
