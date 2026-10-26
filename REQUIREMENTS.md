# Meta Global AI Developer Hackathon — Requirements & Notes

Source: official Participant Guide (Cerebral Valley). If this file and the platform disagree, the platform wins.

## Project

**OrbitRoute** — an agent that turns a satellite image plus a natural-language request into a verified delivery plan.

- Problem statement: **Push the Frontier** (use Meta's models to give a machine a new capability / better understand and control a physical system)
- Track: **Indie Developer** (solo)
- **Ambition: we are NOT building a simple project.** See "Anti-projects" below and the `judging-focus` skill.

## Models

Must incorporate Meta's models (Stage One is pass/fail on this): Muse Spark series, Muse Wonder, Muse Image, Muse Voice Transcribe and SAM 3.1 via Meta Model API; open weights Muse Glimmer and Muse Spark Open; Muse Code coding agent.

| Model | Used for |
|---|---|
| Muse Spark / Spark Open | vision, reasoning |
| SAM 3.1 | segmentation |
| Muse Glimmer | cheap bulk steps |
| Muse Voice Transcribe | voice input (bonus) |

## Timeline

Official times are Eastern Time. DST ends Nov 1, so UTC+5 = ET + 9 h before Nov 1 and ET + 10 h from Nov 1.

| Event | ET | UTC+5 |
|---|---|---|
| Kickoff | Mon Oct 26, 12:00 | Oct 26, 21:00 |
| Building period | Oct 27 – Nov 4 | |
| **Submission deadline** | **Wed Nov 4, 21:00** | **Thu Nov 5, 07:00** |
| Judging period | Nov 5 – Nov 8 | |
| Closing ceremony, top 10 announced (5 per track) | Mon Nov 9, 12:00 | Nov 9, 22:00 |
| Community vote winner | Nov 16 | |

> My earlier notes had the deadline at Nov 5, 06:00 (UTC+5) and the finals at Nov 9, 21:00 (UTC+5). By the ET → UTC+5 conversion above the deadline is 07:00 and the finals 22:00. **Treat Nov 5, 06:00 (UTC+5) as the personal hard deadline** (one hour of safety margin) and verify against the countdown on the submission platform.

Live sessions (ET, streamed):
- Tue Oct 27, 12:00 — Agents 101: Build a Multimodal AI Agent
- Wed Oct 28, 12:00 — **Agents 102: Best Practices for Verifiable Agents** (directly relevant to our verifier)
- Fri Oct 30, 12:00 — Fireworks: from inference to training with Muse open models
- Daily Discord office hours (#office-hours), 10–11 AM ET, except weekends
- Tue Nov 3 — last full day for submission questions; Wed Nov 4, 21:00 — final office hours

## Rules

- [ ] Open source: repository must be **public**
- [ ] **New work only** — everything presented must be built during the event; commits from Oct 26
- [ ] The demo must highlight **only** what was built during the hackathon; judges must be able to clearly identify the original contributions — **failure = immediate disqualification**
- [ ] Code, data and assets only with rights to use them (otherwise disqualification)
- [ ] Project must not violate legal, ethical or platform policies
- [ ] Team max 4; solo allowed (we are solo)
- [ ] Participant: 18+, not an employee of Meta / Cerebral Valley / government bodies *(from personal notes — confirm on the platform)*

### Anti-projects (generic or banned — avoid)

AI medical advice (mental-health advisor, skin blemish detector, etc.); basic RAG apps; **simple image analyzers**; simple "AI for Education" chatbots; AI job application screeners; AI nutrition coaches; personality analyzers; sports analyzers/coaches; **anything political or involving war**.

Consequences for OrbitRoute:
- It must be visibly an **agent** with planning, tools, verification and self-repair — not an image analyzer.
- Keep scenarios civilian and neutral: commercial delivery, logistics, disaster *relief*. No military, conflict-zone or political framing in the demo, README, video or X post.

## Data

**Allowed:**
- Sentinel-2
- NAIP / USGS
- OpenStreetMap (ODbL — attribution required)
- SpaceNet / DeepGlobe (check license first)

**Not allowed:**
- Screenshots from Google / Yandex / Bing
- Maxar / Planet without a license

List all sources and licenses in the README.

## Judging

**Stage 1 (pass/fail):** project reasonably fits the theme and reasonably used Meta Model API and/or Meta open-weight models.
**Stage 2 (0–10 per criterion):**

| Criterion | Weight | What judges ask |
|---|---|---|
| Impact | 30% | Real-world potential; who benefits; could people actually use it; fits a problem statement |
| Use of Meta AI tooling | 25% | Creative use, beyond a basic integration; capabilities that surprise Meta |
| Demo | 25% | Working, impressive; holds up live; video is genuinely cool to watch |
| Technical depth & execution | 20% | Sound, thoughtfully refined engineering; real craft |

**Stage 3:** top 5 per track; judges watch the demo videos live and rank them with the same rubric. The 3-minute video is a primary judging artifact, along with the code and the live product.

## Prizes

Indie track: 1st $150K · 2nd $100K · 3rd $75K · 4th $50K · 5th $25K.

**Bonuses targeted:**
- **Best Build on Meta Open Weight Models — $10K:** must be built on Muse Glimmer or Muse Spark Open, on own hardware or partner inference (Baseten / Modal / Fireworks); the infrastructure partner verifies it
- **Best Agentic Use-Case — $5K:** judged on autonomy, effectiveness at the task, practical usefulness
- **Most Viral — $20K:** post the project demo on X and **submit the post link through the platform**; ranked by likes + reposts + comments until **Nov 8 EOD**
- Community Vote — $10K: most votes in the public gallery (one per verified account); announced Nov 16
- (Not targeted: Best Creative Build — Muse Image / Muse Wonder)

## Credits

| Service | Status |
|---|---|
| Meta API | $150 — received ✅ (a card on file is required to make API calls; pre-authorization is released in a few days) |
| Baseten | $100 + 2M TPM — application submitted; **use `meta-models/muse-spark-open-1026`** (the docs say `muse-spark-open` — wrong for this event) |
| Modal | $100 — application submitted (workspace `tukaevdamirg`) |
| Fireworks | $25 for shortlisted teams only — optional |

Credits are not guaranteed and are granted at each partner's discretion.

## Budget protection

- Meta spend limit only sends an email — it does **not** stop spending
- Virtual card with a spend limit
- `max_tokens` on every call, budget counter in code, rate limiting in the demo
- Keys in `.env` + `.gitignore`, backend only
- Do not add a card to Modal for now

## Submission (due Nov 4, 21:00 ET)

- [ ] Public repository (double-check it opens while logged out)
- [ ] 3-minute demo video highlighting only what was built during the hackathon (link opens)
- [ ] Working live demo / live product
- [ ] X post → post link submitted through the platform
- [ ] Everyone who worked on the project is listed on the submission page
- [ ] Late submissions are not considered

Submission form: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit
