---
name: hackathon-rules
description: Meta Global AI Developer Hackathon (OrbitRoute) compliance rules — we do NOT build a simple project, new-work-only, public repo, demo honesty, banned/anti-projects, data licensing and attribution, deadlines, submission. Use before adding code, data, assets, dependencies or README/demo claims, before scoping features, and before any submission step.
---

# Hackathon rules (OrbitRoute — Push the Frontier, Indie Developer track, solo)

Full notes: `REQUIREMENTS.md` (from the official Participant Guide). If a rule is unclear or looks outdated, tell the user to check the official page instead of guessing.

## Ambition: we are NOT building a simple project

This is a standing rule for every scoping, design and coding decision.

- The goal is a technically deep, impressive, agent-first system — not a demo-grade wrapper around one model call. Weights: Impact 30, Meta tooling 25, Demo 25, Technical depth 20; Stage 3 judges watch the video live against top-5 competitors.
- **Anti-projects the organizers call generic or banned:** AI medical advice; basic RAG apps; **simple image analyzers**; simple "AI for Education" chatbots; AI job application screeners; AI nutrition coaches; personality analyzers; sports analyzers/coaches; **anything political or involving war**.
- OrbitRoute must read as an **agent**: multi-step plan → tool use (SAM 3.1, Muse Spark, solver) → independent verification → explicit self-repair → re-solve, with an observable agent log. Image segmentation is only step 1.
- Do not ship a feature set that would be describable as "upload an image, get a description/detection". If a change moves the project toward that, flag it and propose the deeper alternative.
- Prefer depth in the core loop (verifier, repair strategies, evaluation on scenarios, budget guard) over breadth of shallow features.
- Keep every scenario **civilian and neutral**: commercial delivery, logistics, disaster *relief*. No military, conflict-zone, surveillance or political framing in code, data, README, video or the X post.
- When proposing work, say how it raises Technical depth, Demo, or Meta-tooling use. Cut what does not.

## Work and repo

- **New work only.** Everything presented must be built during the event; all commits dated Oct 26, 2026 or later. Write the solver, graph builder and agent code from scratch in this repo. Do not paste code from earlier personal projects. Open-source libraries used as dependencies (OR-Tools, PyVRP, etc.) are fine — declare them.
- **Public repository** (open source). Never commit secrets, private data or anything not meant to be public.
- **Demo, video and README show only what was built during the hackathon**, and judges must be able to clearly identify the original contributions — otherwise immediate disqualification. No aspirational features, no pre-existing work, no invented metrics. Make the new work easy to see: commit history, a short "what we built" list in the README.
- Code, data and assets only with rights to use them.
- Must incorporate Meta's models (Stage One pass/fail): SAM 3.1, Muse Spark / Spark Open, Muse Glimmer, optionally Muse Voice Transcribe, via Meta Model API or open weights.

## Data and assets

Allowed: Sentinel-2, NAIP / USGS, OpenStreetMap (ODbL), SpaceNet / DeepGlobe (**check the license before use**).
Forbidden: screenshots from Google / Yandex / Bing; Maxar / Planet imagery without a license.

- Only use images, fonts, icons, music, voice and data the project has the right to use.
- Every data source and license is listed in the README.
- OpenStreetMap data requires visible attribution ("© OpenStreetMap contributors", ODbL) in the README and wherever OSM-derived data is shown in the UI/video.
- Record the source URL and license of each dataset or image next to it (e.g. `data/SOURCES.md`).
- If a source's license is unclear, do not use it — ask the user.

## Dates

Official times are Eastern Time (DST ended Nov 1). UTC+5 = ET + 10 h from Nov 1.

- Building period: Oct 27 – Nov 4.
- **Submission deadline: Nov 4, 21:00 ET = Nov 5, 07:00 UTC+5.** Personal hard deadline: **Nov 5, 06:00 UTC+5**. Late submissions are not considered.
- Judging Nov 5–8. Closing ceremony Nov 9, 12:00 ET (22:00 UTC+5).
- Most Viral: engagement counted until Nov 8 EOD; the X post link is submitted through the platform.
- Meta credits must be claimed by Nov 4, 21:00 ET (already received).

## Bonus eligibility

- **Open Weight ($10K):** must run on Muse Glimmer or Muse Spark Open via own hardware or partner inference (Baseten model id `meta-models/muse-spark-open-1026`, not the id in the docs). The partner verifies it.
- **Agentic ($5K):** judged on autonomy, effectiveness, practical usefulness.
- **Most Viral ($20K):** demo post on X.

## Eligibility (user-side, do not act on it)

18+; not an employee of Meta, Cerebral Valley or a government body (from the user's notes). Solo, Indie track.

## Submission checklist

- [ ] Public repo, opens while logged out
- [ ] 3-minute video highlighting only hackathon-built work; link opens without login
- [ ] Working live demo
- [ ] X post, link submitted through the platform
- [ ] Everyone who worked on the project listed
- Form: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit

Never submit forms, publish posts or make anything public on the user's behalf without explicit confirmation.
