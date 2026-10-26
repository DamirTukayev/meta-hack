---
name: living-docs
description: Keep OrbitRoute's English-only living documents in sync with the code — VIDEO_SCRIPT.md (3-minute demo script), PROJECT_CV.md (résumé-style project description), README.md, and IDEA.md. Use after finishing any feature, measuring any metric, or changing the pipeline or demo flow.
---

# Living docs

The user wants the 3-minute video script and the project CV written **as the project progresses**, not at the end. After each meaningful change, update the docs before reporting the task done.

## Language

**Everything is in English**: code, comments, commit messages, docs, README, script, CV, UI strings. Chat replies to the user may be in the user's language (Russian), but files are English.

## When to update what

| Event | Update |
|---|---|
| A pipeline step or UI feature works end-to-end | `VIDEO_SCRIPT.md`: set the segment status to `DONE`, make the voice-over match what the screen really shows; add a row to its update log |
| A metric is measured (accuracy, success rate, latency, cost per run) | `PROJECT_CV.md`: replace `[TBD]` with the real value and how it was measured; update the metrics table |
| A feature is cut or changes | Remove or rewrite it in `VIDEO_SCRIPT.md`, `PROJECT_CV.md` and `README.md` — never leave claims for things that do not exist |
| A data source, model or library is added | `README.md` sources/licenses section and `PROJECT_CV.md` tech stack |
| Direction of the idea changes | `IDEA.md` |

## Rules

- **Truth only.** Document and narrate only what is built and verified. No invented numbers, no "planned" features presented as done. Unknown values stay `[TBD]`.
- **Hackathon-only work.** The README and demo must only describe work done during the hackathon (see the `hackathon-rules` skill).
- **Video script constraints:** total ≤ 3:00 (target 2:50); the agent's verify → repair → re-solve loop is the centerpiece; every segment has screen description + voice-over; segment statuses are `PLANNED`, `DONE` or `CUT`.
- **Judging weights** drive emphasis (see the `judging-focus` skill): Impact 30, Meta AI tooling 25, Demo 25, Technical depth 20.
- **CV style:** short, past-tense, action-verb bullets with a measured result; no filler.
- Keep the update log tables in each doc current (date + one-line change).
- No secrets, keys or private URLs in any doc.

## README must contain (build it up over time)

- What OrbitRoute is, in 2–3 sentences, agent-first
- Architecture / pipeline overview
- How to run locally and the live demo link
- **Data sources and licenses** (including OpenStreetMap ODbL attribution)
- Which Meta models are used and for what
- Honest limitations
