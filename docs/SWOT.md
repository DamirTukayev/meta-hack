# SWOT, with the models in the middle

How OrbitRoute stands, looked at through the way it uses models. Every point rests on something measured in this repository (the file is named) or is marked as a judgement.

## Strengths

- **The model is never the judge of its own work.** Muse Spark and SAM propose; a verifier written as plain code decides, and a second implementation of the checks audits the evaluation. A plain solver's first plan broke a rule in 56% of the plans it called feasible; none of the 243 plans the agent returned failed the audit, over 924 plans with no disagreement between the two checkers (`eval/BIG_SUITE.md`, `eval/RESULTS.md`).
- **SAM sees what no map has.** Standing water, the buildings that stand today and whether a mapped road can still be seen: all from the photo, with no training (`eval/FLOOD.md`, `eval/TRACKS.md`). On the second Houston photo 34% of the named streets of the map (9.1 of 27 km) lie under water.
- **Models in the roles they are good at.** Muse Spark reads a sentence in six languages as well as in English (7–9 of 10 requests exactly, English 8–9, `eval/PARSING_LANGUAGES.md`), draws zones (63% of the OpenStreetMap-labelled pixels right against 39% for a model that ignores the photo, `eval/SCENE_OSM.md`) and takes a second look at a stretch; routing and verification stay in code.
- **Not tied to one provider.** The text and vision steps run on open-weight Muse Spark Open at Baseten, then Modal, then the Meta API, each with its own budget; a keyless recorded demo works from a fresh clone.
- **Honest by construction.** Doubt is shown as doubt: what the photo does not confirm is listed with its share of the driving, the model's look can make a stretch costly but never forbids it, and the water card gives ranges, never counts.

## Weaknesses

- **SAM does not read roads well where it matters most.** From the photo alone it finds 47% of the named streets over twelve US places (4% in downtown Chicago) and 3%, 69% and 0% of the mapped dirt track on three forest squares. That is why the roads now come from OpenStreetMap and the photo is only evidence (`eval/HYBRID.md`), which brings its own limits: the map is as old and as complete as its contributors, and on one Houston photo it is thinner than the photo.
- **The model's second look has no ground truth.** In a dry city it says "no road visible" about stretches a person sees as lanes, and in a flooded one it may see water that is not there; it is a second opinion, so it cannot overrule the map except on a positive sign (water, debris).
- **Open-weight answers are less steady.** Muse Spark Open follows a prompt's field rules less closely than Muse Spark 1.3 (11/20 against 20/20 with the first prompt), sometimes answers with nothing, and a vision question phrased as yes/no was answered "no" every time until it became a choice between named conditions.
- **Cost sits in one place.** A new map area costs about $0.5 of SAM calls, so the product is cheap to demonstrate and expensive to open to everyone without a cache.
- **Language reaches the buttons, not the agent's words.** The interface is in six languages; the agent's log, its assumptions, a violation's message and the repair options are still English.
- **Narrow data.** US imagery only; two photos of a disaster; random scenarios, not real requests; no human labels for most of the vision outputs.

## Opportunities

- **Photo as evidence on top of any map.** The same pattern (map says it was passable, photo says whether it still is) works for any region that has a base map and a fresh image; the data sources, not the method, are what limit it today (`docs/ROADMAP.md`).
- **Better models arrive on their own.** A SAM that finds roads under trees, or a vision model that is steadier about water, improves the product without a redesign, because the verifier does not change.
- **Open weights.** Running Muse Spark Open on a customer's own hardware or a partner's would remove the per-call cost of the text and vision steps and fit organisations that cannot send images out.
- **A loop back to the map.** Stretches the photo shows that the map lacks, or the map has and the photo contradicts, are exactly what mapping communities want to review.
- **Localisation of the agent's own words** by asking the model to write its explanations in the user's language, which the interface structure already allows.

## Threats

- **Dependence on one model API and its credits.** SAM 3.1 is reached only through the Meta Model API; the hackathon credits end around 4 November and the live path then costs real money. Mitigation built: caps, a deadline for live calls, the recorded demo, a kill switch. Not mitigated: a change of the API or its price.
- **Wrong confidence in a plan.** A verified plan is valid by the map; a road that is gone, a one-way street (mapped, not enforced) or water the photo missed can still make it wrong on the ground. The interface says so, but a user who does not read it could trust it too much. The imagery is not meant for navigation and the product is a decision aid, not an emergency system.
- **Data terms.** OpenStreetMap needs attribution and share-alike care, NOAA imagery is not intended for navigation, and any imagery source added later (see the roadmap) needs its licence read first.
- **Model drift and non-determinism.** The same crop can be answered differently on another day; recorded answers make the demo stable and also hide this, which is why the README measures repeats where it can.
- **A free demo is a target.** Public live paths cost money; the access code, caps and rate limits address it, and a determined user could still spend a shared copy's caps.
