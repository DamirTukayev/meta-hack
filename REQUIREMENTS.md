# Meta Hackathon — Requirements & Notes

## Project

**OrbitRoute** — an agent that turns a satellite image plus a natural-language request into a verified delivery plan.

- Track: Push the Frontier
- Category: Indie (solo)

## Models

| Model | Used for |
|---|---|
| Muse Spark / Spark Open | vision, reasoning |
| SAM 3.1 | segmentation |
| Muse Glimmer | cheap bulk steps |

## Timeline (UTC+5)

- Development: Oct 27 – Nov 4
- **Deadline: Nov 5, 06:00** (Nov 4, 21:00 ET)
- Finals: Nov 9, 21:00

## Rules

- [ ] New work only; commits from Oct 26
- [ ] Public repository
- [ ] README and demo show only what was built during the hackathon
- [ ] Data and assets only with usage rights
- [ ] Must not look like a "simple image analyzer" — emphasize the agent
- [ ] Participant: 18+, not an employee of Meta / Cerebral Valley / government bodies

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

## Judging criteria

| Criterion | Weight |
|---|---|
| Impact | 30% |
| Use of Meta AI tooling | 25% |
| Demo | 25% |
| Technical depth | 20% |

**Bonuses targeted:**
- Open Weight — 10k
- Agentic — 5k
- Most Viral — $20k (X post before Nov 8)

## Credits

| Service | Status |
|---|---|
| Meta API | $150 — received ✅ |
| Baseten | $100 + 2M TPM — application submitted, model `meta-models/muse-spark-open-1026` |
| Modal | $100 — application submitted (workspace `tukaevdamirg`) |
| Fireworks | optional |

## Budget protection

- Meta spend limit only sends an email — it does **not** stop spending
- Virtual card with a spend limit
- `max_tokens` on every call, budget counter in code, rate limiting in the demo
- Keys in `.env` + `.gitignore`, backend only
- Do not add a card to Modal for now

## Submission

- [ ] Public repository
- [ ] 3-minute video (link opens)
- [ ] Working live demo
- [ ] X post → link in the submission form

Submission form: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit
