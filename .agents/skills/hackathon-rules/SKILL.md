---
name: hackathon-rules
description: Meta AI Developer Hackathon (OrbitRoute) compliance rules — new-work-only, public repo, README honesty, data licensing and attribution, eligibility, deadlines. Use before adding code, data, assets, dependencies or README/demo claims, and before any submission step.
---

# Hackathon rules (OrbitRoute, Push the Frontier / Indie)

Full notes: `REQUIREMENTS.md`. If a rule here is unclear or looks outdated, tell the user to check the official hackathon page instead of guessing.

## Work and repo

- **New work only.** All commits must be dated Oct 26, 2026 or later. Write the solver, graph builder and agent code from scratch in this repo. Do not paste in code from earlier personal projects. Open-source libraries used as dependencies (OR-Tools, PyVRP, etc.) are fine — declare them.
- **Public repository.** Never commit secrets, private data, or anything not meant to be public.
- **README and demo claim only what was built during the hackathon.** No aspirational features, no pre-existing work, no invented metrics. If it is not working, it is not in the README or the video.
- **Emphasize the agent.** The project must not read as a "simple image analyzer". Every feature should serve the agent loop: plan → solve → verify → repair → re-solve.

## Data and assets

Allowed: Sentinel-2, NAIP / USGS, OpenStreetMap (ODbL), SpaceNet / DeepGlobe (**check the license before use**).
Forbidden: screenshots from Google / Yandex / Bing; Maxar / Planet imagery without a license.

- Only use data and assets (images, fonts, icons, music, voice) the project has the right to use.
- Every data source and license is listed in the README.
- OpenStreetMap data requires visible attribution ("© OpenStreetMap contributors", ODbL) in the README and wherever OSM-derived data is shown in the UI/video.
- Record the source URL and license of each dataset or image file next to it (e.g. `data/SOURCES.md`).
- If a source's license is unclear, do not use it — ask the user.

## Eligibility (user-side, do not act on it)

Participant must be 18+, and not an employee of Meta, Cerebral Valley, or a government body. Solo entry, Indie category.

## Dates (UTC+5)

- Build window: Oct 27 – Nov 4.
- **Submission deadline: Nov 5, 06:00** (Nov 4, 21:00 ET). Finals: Nov 9, 21:00.
- Most Viral bonus: X post before Nov 8.

## Submission checklist

- [ ] Public repo
- [ ] 3-minute video, link opens without login
- [ ] Working live demo
- [ ] X post, with its link added to the submission form
- Form: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit

Never submit forms, publish posts, or make anything public on the user's behalf without explicit confirmation.
