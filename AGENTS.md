# OrbitRoute — Agent Instructions

Read by Codex (and Claude Code via `CLAUDE.md`). Hackathon project: an agent that turns a satellite image + a natural-language request into a verified delivery plan. See `IDEA.md` and `REQUIREMENTS.md`.

## Always

- **We are NOT building a simple project.** Aim for a deep, agent-first system (plan → solve → verify → repair → re-solve), not a "simple image analyzer" or thin model wrapper — the organizers list those as generic/banned. Flag any change that moves toward that and propose the deeper alternative. Keep scenarios civilian (no war/political framing). See `hackathon-rules` and `judging-focus`.
- **Write everything in English**: code, comments, commits, docs, README, UI text. (Chat with the user may be in Russian.)
- **Before adding any file to the repo, decide whether it belongs there** (`repo-hygiene`): the repo is public, so plans, notes, personal and generated files stay local and git-ignored. If unsure, ask.
- Follow the skills in `.agents/skills/` (mirrored at `.claude/skills/`):
  - `hackathon-rules` — new work only, public repo, data licensing, README honesty, deadlines
  - `budget-guard` — `max_tokens`, budget counter, rate limits, secrets in `.env`, backend only
  - `living-docs` — keep `VIDEO_SCRIPT.md`, `PROJECT_CV.md`, `README.md` in sync after every finished feature
  - `judging-focus` — judging weights, bonuses, agent-first design
  - `repo-hygiene` — what may go into the public repo and what must stay local
- After finishing a feature or measuring a metric, update `VIDEO_SCRIPT.md` and `PROJECT_CV.md` before reporting done. These two files are **local-only** (git-ignored, never commit or publish them).
- Never invent metrics or claim unbuilt features.
- Never commit secrets. Never publish, submit or spend money for the user without explicit confirmation.

## Key facts

- Track: Push the Frontier, Indie, solo. Commits only from Oct 26, 2026.
- Build window Oct 27 – Nov 4; official deadline Nov 4, 21:00 ET = Nov 5, 07:00 UTC+5; personal hard deadline **Nov 5, 06:00 (UTC+5)**.
- The demo may show only what was built during the hackathon, clearly identifiable — otherwise disqualification.
- Models: SAM 3.1 (segmentation), Muse Spark / Spark Open (vision + reasoning), Muse Glimmer (cheap bulk steps).
