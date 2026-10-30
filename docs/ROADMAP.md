# Product plan

Written code is the cheap part. What decides whether OrbitRoute is used is the value to the person at the other end, and how fast a few of them can get it. This is a plan, not a record: nothing below is built unless the README says so. Where a step depends on a fact that has not been checked (a licence, a price, an organisation's needs) it says so.

## Who it is for and what they get

| User | The situation | What OrbitRoute gives them that they lack today |
|---|---|---|
| Relief logistics coordinator (NGO, civil protection) after a flood or storm | The map is as it was before; a photo exists; trucks and volunteers must be sent now | A plan in minutes that stays out of the water and has been checked, an honest "cannot be met" with checked alternatives, a rough picture of who is exposed and where a crowd could go |
| Municipal emergency or public-works office | A district changed (flood, works, a bridge out); the routing tool still knows the old streets | The map roads the photo confirms, the stretches it cannot confirm, and a plan that prefers the first |
| Last-mile operator in a place that is badly mapped | Dirt roads, new districts | Roads from the map where it has them, from the photo where it has not, with the doubt shown |

The one sentence the product should earn: *a plan you can trust, and a plain list of what it could not confirm.*

## What exists today (built)

The pipeline from photo and sentence to verified plan; roads from OpenStreetMap with the photo as evidence; standing water, buildings and the model's second look; the water card; six interface languages; a recorded demo that needs no account; a shared deployment with caps. See the README for what each was measured at and where it fails.

## Next four weeks: from a demo to something a partner can try (plan)

1. **Their own imagery.** Upload a GeoTIFF or a georeferenced drone orthophoto with its scale instead of choosing a US square; this removes the US-only limit for anyone who has an image, and it is the first thing a partner will ask for. Needs size and format limits, a check of the scale, no storage after the run unless asked.
2. **Their own orders.** Import orders from a CSV (address or coordinates, quantity, time window) and export the plan as CSV and GeoJSON for the people in the trucks.
3. **Before and after.** Compare a photo before an event with one after to show what changed, instead of judging one photo alone.
4. **The agent's words in the user's language.** Ask the model to write the log, the assumptions, the violations and the repair options in the interface language; the structure already carries the texts as data.
5. **Tell the truth about one-way streets.** Enforce the mapped one-way streets in the graph and the verifier (today they are mapped but not enforced).
6. **Labels.** A way to mark a stretch as passable or blocked on the map; stored, they are the first ground truth for the second look and the water card, and they calibrate the thresholds with data instead of by eye.

## Three months: from a tool to a service (plan)

- Accounts, per-organisation budgets and quotas, a run history that can be reopened and shared, and the scaling steps of `docs/ARCHITECTURE.md` (shared state, a tile cache, a queue, a worker pool).
- Imagery from sources outside the US. Which open sources fit (global satellite programmes, open data released after disasters) and under which licences **has to be checked**; each source brings a resolution and an age that change what the photo can confirm.
- Several trips per truck, vehicle types, depots with opening hours, priorities for orders.
- Evacuation as a second problem next to delivery: people to shelters with capacities, by dry roads.
- Reporting back to the map: stretches the photo shows that the map lacks, or the map has and the photo contradicts, offered to mapping communities for review (a possible partner type: humanitarian mapping groups).

## Six to twelve months: reaching the market (plan)

- **Pilots, not marketing, first.** Three to five pilots with relief organisations and municipal emergency offices, each on a real event or an exercise; what is measured: minutes from photo to first accepted plan, share of plans the dispatcher changed, and every case where the plan was wrong on the ground.
- **Packaging.** An API and a plug-in for the tools dispatchers already use, an offline-capable build for places without a connection, and open-weight models on the customer's side where images may not leave.
- **Business model, to be tested in the pilots:** free for emergencies and for mapping communities; paid for operators and agencies who want accounts, history, integrations and a service level. No price is proposed here because none has been tested.
- **Trust.** A published error log of wrong plans, the evaluation suites kept in the open and extended with each pilot, and the same rule as today: nothing is claimed that has not been measured.

## What would change this plan

A model that finds roads under trees reliably would move the weight from the map back to the photo. A model price change would move the cache from an optimisation to a requirement. A pilot saying the water card matters more than the routing would reorder the list above.
