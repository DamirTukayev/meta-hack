---
name: repo-hygiene
description: Decide whether a file belongs in the public OrbitRoute repository before creating, staging or committing it. Use whenever adding a new file or directory, running git add/commit/push, or writing planning, notes, personal, credential, data or generated files.
---

# Repo hygiene — should this file be in the repo?

The repository is **public** and is judged. Default stance: **publish only what a judge or a user of the project needs.** Think about each new file before it is staged; do not `git add -A` blindly.

## Decide for every new file

Ask in order:

1. **Secret or credential?** (keys, tokens, `.env`, cookies, account/workspace identifiers, payment info) → never commit. Add to `.gitignore`.
2. **Personal or private?** (user's notes, finances, credit/budget details, contact info, drafts of posts) → never commit; keep local under `personal/` or a `*.private.*` name (already git-ignored).
3. **Working/planning artifact?** (plans, schedules, risk lists, TODOs, video script, CV, scratch output, debug dumps) → local only; add to `.gitignore`. The user has chosen to keep `PROJECT_CV.md` and `VIDEO_SCRIPT.md` local and does not want the plan published.
4. **Generated or heavy?** (build output, caches, large datasets, model weights, logs, raw imagery) → ignore; record where it came from instead (`data/SOURCES.md`).
5. **Licensed third-party material?** → only if the license allows redistribution and the source and license are listed in the README / `data/SOURCES.md`.
6. **Useful to a judge or user?** (source code, tests, evaluation scripts, small licensed sample data, README, LICENSE, run/deploy instructions, architecture notes) → commit.

If unsure, **do not commit — ask the user** with one short question (file, why it is doubtful).

## Rules

- Before every commit, run `git status` and read the staged list; unstage anything that fails the checks above. Check content too, not just names (no keys, no personal data, no internal-only notes).
- Never commit without the user's request; never push without it. Do not rewrite or force-push history unless the user asks.
- A file that was already committed stays in history after it is removed. If a secret or personal data was committed, tell the user immediately and recommend rotating the secret; do not claim removal is enough.
- When a new local-only file type appears, add it to `.gitignore` in the same change and tell the user.
- Keep the commit history honest and clear: small commits with plain English messages; all work dated Oct 26, 2026 or later (see `hackathon-rules`).
- Everything committed is in English (see `living-docs`).
