"""The whole product as one call: image + request -> agent run, streamed as events for the UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orbitroute.agent.events import Emit, Event
from orbitroute.agent.loop import AgentResult, run_agent
from orbitroute.agent.repair import Decider, ModelDecider, PolicyDecider
from orbitroute.config import ROOT
from orbitroute.custom import CustomInputs, apply_custom
from orbitroute.llm.budget import BudgetGuard, RunBudget
from orbitroute.llm.client import ApiError, MetaClient
from orbitroute.perception.buildings import building_points, segment_buildings
from orbitroute.perception.flood import flood_zones, segment_floods
from orbitroute.perception.graph import build_road_graph
from orbitroute.perception.segment import segment_roads
from orbitroute.routing.scenario import make_scenario
from orbitroute.serialize import graph_json, mask_png, plan_json, report_json, scenario_json, scene_json
from orbitroute.understanding.request import parse_request, parse_request_cached
from orbitroute.understanding.scene import Scene, analyze_scene

SAMPLES_DIR = ROOT / "data" / "samples"


@dataclass
class Sample:
    name: str
    path: Path
    meta: dict

    @property
    def image_bytes(self) -> bytes:
        return self.path.read_bytes()


def list_samples() -> list[Sample]:
    out = []
    for jpg in sorted(SAMPLES_DIR.glob("*.jpg")):
        meta_path = jpg.with_suffix(".json")
        if meta_path.exists():
            out.append(Sample(jpg.stem, jpg, json.loads(meta_path.read_text())))
    return out


def get_sample(name: str) -> Sample:
    """A bundled sample, or an area the user picked on the map (stored under data/areas)."""
    for s in list_samples():
        if s.name == name:
            return s
    from orbitroute.areas import AREAS_DIR, PREFIX

    if name.startswith(PREFIX) and name.replace("-", "").isalnum():
        jpg = AREAS_DIR / f"{name}.jpg"
        meta = AREAS_DIR / f"{name}.json"
        if jpg.exists() and meta.exists():
            return Sample(name, jpg, json.loads(meta.read_text()))
    raise KeyError(name)


def request_text(request: str, custom: CustomInputs | None, auto_orders: int | None, trucks: int | None = None) -> str:
    """The text sent to the parser. The order count comes from the user's clicks (or the "place for me" count) and the
    truck count from its own field, so both are stated up front; any other number in the sentence is overridden later
    and reported."""
    head = []
    if custom is not None and custom.orders:
        head.append(f"{len(custom.orders)} orders.")
    elif auto_orders:
        head.append(f"{auto_orders} orders.")
    if trucks:
        head.append(f"{trucks} trucks.")
    return " ".join([*head, request])


def run_pipeline(
    sample: Sample,
    request: str,
    *,
    client: MetaClient,
    guard: BudgetGuard,
    text_client: MetaClient | None = None,
    run_cap_usd: float,
    seed: int = 0,
    use_model_decider: bool = True,
    custom: CustomInputs | None = None,
    auto_orders: int | None = None,
    trucks: int | None = None,
    emit: Emit,
) -> AgentResult:
    run: RunBudget = guard.new_run(run_cap_usd)
    text = text_client or client  # text-only reasoning can run on the open-weight model
    image_bytes = sample.image_bytes

    emit(Event("stage", "Segmenting roads with SAM 3.1 (tiled)", {"stage": "perception"}))
    mask = segment_roads(client, image_bytes, run=run)
    graph = build_road_graph(mask, sample.meta["m_per_px"])
    emit(Event("perception", f"Road graph: {graph.stats['nodes']} nodes, {graph.stats['road_km']} km of road", {"mask": mask_png(mask), "graph": graph_json(graph)}))

    emit(Event("stage", "Reading land use and warehouses with Muse Spark", {"stage": "scene"}))
    scene = analyze_scene(client, image_bytes, run=run)
    emit(Event("scene", f"{len(scene.zones)} zones, {len(scene.warehouses)} warehouses", scene_json(scene)))

    emit(Event("stage", "Turning the request into routing constraints", {"stage": "request"}))
    has_custom = custom is not None and not custom.empty
    full_text = request_text(request, custom, auto_orders, trucks)
    n_head = len(custom.orders) if custom is not None and custom.orders else auto_orders
    if n_head or trucks:  # the counts come from the interface, so the answer for this sentence can be remembered and reused
        problem = parse_request_cached(text, request, full_text, n_orders=n_head, n_vehicles=trucks, run=run)
    else:
        problem = parse_request(text, full_text, run=run)
    flood_note = None
    if "flooded" in problem.avoid_zone_kinds and not any(z.kind == "flooded" for z in scene.zones):
        emit(Event("stage", "Finding flooded areas with SAM 3.1", {"stage": "scene"}))
        found = flood_zones(segment_floods(client, image_bytes, run=run), sample.meta["m_per_px"])
        scene = Scene(scene.width, scene.height, [*scene.zones, *found], scene.warehouses)
        covered = sum(z.polygon.area for z in found) / (scene.width * scene.height)
        emit(Event("scene", f"{len(found)} flooded areas ({covered:.0%} of the photo)" if found else "no flooded areas found", scene_json(scene)))
        if not found:
            flood_note = "No flooded areas were found in this photo, so nothing is avoided on that account."
    notes: list[str] = [flood_note] if flood_note else []
    if trucks and problem.n_vehicles != trucks:
        notes.append(f"Using {trucks} truck{'s' if trucks != 1 else ''} from the Trucks field instead of the {problem.n_vehicles} in the text.")
    if trucks:
        from orbitroute.understanding.constraints import with_vehicle_count

        problem = with_vehicle_count(problem, trucks)
    if auto_orders and not (custom and custom.orders):
        from orbitroute.understanding.constraints import with_order_count

        problem = with_order_count(problem, auto_orders)

    targets = None
    if not (custom and custom.orders):  # the agent places the orders: at buildings, not at random points of the road
        emit(Event("stage", "Finding buildings with SAM 3.1 (delivery addresses)", {"stage": "scene"}))
        try:
            targets = building_points(segment_buildings(client, image_bytes, run=run), sample.meta["m_per_px"])
        except ApiError:  # not essential: without it the orders go on road points
            notes.append("Buildings could not be read from the photo, so the orders were placed on road points.")
    if has_custom:
        scenario, problem, scene2, custom_notes = apply_custom(graph, scene, problem, custom, seed=seed, targets=targets)
        notes += custom_notes
        if scene2 is not scene:
            emit(Event("scene", f"{len(scene2.zones)} zones including the one you drew", scene_json(scene2)))
        problem = problem.model_copy(update={"assumptions": [*problem.assumptions, *notes]})
        scenario.problem = problem
    else:
        problem = problem.model_copy(update={"assumptions": [*problem.assumptions, *notes]})
        scenario = make_scenario(graph, scene, problem, seed=seed, prefer_connected=True, targets=targets)
    emit(Event("problem", f"{problem.n_orders} orders, {problem.n_vehicles} trucks, avoiding {', '.join(problem.avoid_zone_kinds) or 'nothing'}", {"problem": problem.model_dump(), "assumptions": problem.assumptions}))
    emit(Event("scenario", (f"depot and {len(scenario.order_nodes)} orders placed on the roads (yours)" if has_custom and custom.orders else f"depot and {len(scenario.order_nodes)} orders placed" + (f", {sum(t is not None for t in scenario.order_targets)} of them at buildings found by SAM 3.1" if scenario.order_targets else " on road points")), scenario_json(scenario)))

    def agent_emit(e: Event) -> None:
        data = dict(e.data)
        if e.type == "solve":
            plan, matrix = e.obj
            data["plan"] = plan_json(scenario, plan, matrix)
        elif e.type == "verify":
            data["report"] = report_json(scenario, e.obj)
            data.pop("checks", None)
            data.pop("violations", None)
        emit(Event(e.type, e.message, data, e.t))

    decider: Decider = ModelDecider(text, run) if use_model_decider else PolicyDecider()
    result = run_agent(scenario, decider=decider, emit=agent_emit)

    emit(
        Event(
            "result",
            result.status,
            {
                "status": result.status,
                "plan": plan_json(result.scenario, result.plan, result.matrix),
                "report": report_json(result.scenario, result.report),
                "excluded": {str(k): v for k, v in result.excluded.items()},
                "relaxations": [
                    {"kind": o.kind, "amount": o.amount, "description": o.description, "plan": plan_json(o.scenario, o.plan), "report": report_json(o.scenario, o.report), "depot": scenario_json(o.scenario)["depot"]}
                    for o in result.relaxations
                ],
                "recommendation": {"index": result.recommendation.index, "reason": result.recommendation.reason, "source": result.recommendation.source} if result.recommendation else None,
                "seconds": round(result.seconds, 1),
                "cost_usd": round(run.spent, 4),
                "paid_calls": run.calls,
            },
        )
    )
    return result
