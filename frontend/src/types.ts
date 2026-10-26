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
  metrics: { total_km: number; last_return: string }
  excluded: Record<string, string>
}
export interface Problem {
  n_orders: number
  n_vehicles: number
  capacity: number
  avoid_zone_kinds: string[]
  assumptions: string[]
  notes: string[]
}
export interface Relaxation { kind: string; amount: number; description: string; plan: PlanGeo; report: ReportGeo }
export interface Result {
  status: string
  plan: PlanGeo
  report: ReportGeo
  excluded: Record<string, string>
  relaxations: Relaxation[]
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
export interface RunState {
  status: 'idle' | 'running' | 'done' | 'error'
  stage: string
  mask?: string
  graph?: { nodes: XY[]; edges: [number, number, number, number][]; stats: Record<string, number> }
  zones: Zone[]
  warehouses: XY[]
  problem?: Problem
  depot?: XY
  orders: XY[]
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
