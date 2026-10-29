export type XY = [number, number]

export interface Sample {
  name: string
  label: string
  width: number
  height: number
  m_per_px: number
  examples: string[]
  image: string
  credit: string
  event?: string | null // disaster imagery: the storm or flood the photo was taken during
  captured?: string | null
}

export interface Zone { kind: string; polygon: XY[] }
export interface Stop { order: number; xy: XY; arrive_s: number }
export interface RoutePlan { vehicle: number; polyline: XY[]; legs: XY[][]; stops: Stop[]; start_s: number; end_s: number; distance_m: number }
export interface PlanGeo { routes: RoutePlan[]; served: number; unserved: number[] }
export interface Check { kind: string; title: string; passed: boolean; detail: string }
export interface Violation { kind: string; message: string; route: number | null; segments?: [XY, XY][] }
export interface ReportGeo {
  ok: boolean
  checks: Check[]
  violations: Violation[]
  metrics: { total_km: number; last_return: string; unconfirmed_m?: number; unconfirmed_share?: number; risk_m?: Record<string, number>; flagged_m?: number; flagged_share?: number }
  excluded: Record<string, string>
  unconfirmed?: [XY, XY][] // driven links the graph drew across a gap: the photo does not show a road there
  flagged?: [XY, XY, string][] // driven map roads the photo does not confirm (unseen, blocked) or that lie under water
}
export interface Problem {
  n_orders: number
  n_vehicles: number
  capacity: number
  avoid_zone_kinds: string[]
  shift_start_s?: number
  deadline_s?: number
  assumptions: string[]
  notes: string[]
}
export interface Relaxation { kind: string; amount: number; description: string; plan: PlanGeo; report: ReportGeo; depot?: XY }
export interface Recommendation { index: number; reason: string; source: string }
export interface Result {
  status: string
  plan: PlanGeo
  report: ReportGeo
  excluded: Record<string, string>
  relaxations: Relaxation[]
  recommendation?: Recommendation | null
  seconds: number
  cost_usd: number
  paid_calls: number
}
export interface Iteration {
  n: number
  plan: PlanGeo
  report?: ReportGeo
  action?: string
  reason?: string
  source?: string
}
export interface LogEntry { id: number; type: string; text: string; t: number; source?: string }
export interface Shelter { xy: XY; area_m2: number; capacity: number; minutes: number; kind: string | null; name: string | null; guess?: string }
export interface Exposure {
  buildings: number; in_water: number; surrounded: number; dry: number; people_low: number; people_high: number; assumption: string
  shelters: Shelter[]; shelter_candidates: number; not_shelters: Record<string, number>; cut_off_by_water: number
}
export interface RunState {
  status: 'idle' | 'running' | 'done' | 'error'
  stage: string
  mask?: string
  graph?: { nodes: XY[]; edges: [number, number, number, number, string?][]; stats: Record<string, number> }
  roadSource?: 'osm' | 'sam' // the graph comes from the map (the photo is evidence) or was read from the photo
  edgeRisk?: string[] // per graph edge: seen, unseen, clear, blocked or water
  evidenceKm?: Record<string, number>
  exposure?: Exposure // buildings in or beside standing water, and large dry buildings reachable by dry roads
  inspections?: { verdict: string; condition: string; confidence: number; length_m: number; segments: [XY, XY][] }[] // what the model found when it looked at stretches the photo does not confirm
  zones: Zone[]
  warehouses: XY[]
  problem?: Problem
  depot?: XY
  orders: XY[]
  orderTargets: (XY | null)[] // the building behind each agent-placed order
  sparseRoads?: number // km of road per km2 when the graph is thin (dense blocks or tree cover hide the streets)
  iterations: Iteration[]
  log: LogEntry[]
  result?: Result
  error?: string
  errorPoint?: { kind: 'depot' | 'order'; index: number } // the placed point the error is about
}
export interface StreamEvent { type: string; message: string; data: Record<string, any>; t: number }

export type Mode = 'browse' | 'depot' | 'order' | 'zone'
/** Points the user placed by clicking on the map, in image pixels. */
export interface Custom { depot?: XY; orders: XY[]; zone: XY[]; zoneClosed: boolean }
export const emptyCustom: Custom = { orders: [], zone: [], zoneClosed: false }
