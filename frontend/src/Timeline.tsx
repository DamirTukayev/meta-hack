import { ROUTE_COLORS } from './MapView'
import type { PlanGeo, Problem } from './types'

const clock = (sec: number) => `${String(Math.floor(sec / 3600)).padStart(2, '0')}:${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}`

/** One row per truck on a shared clock: when it leaves, each stop it makes, when it is back, and the deadline. */
export default function Timeline({ plan, problem }: { plan: PlanGeo; problem?: Problem }) {
  const routes = plan.routes
  if (!routes.length) return null
  const t0 = Math.min(problem?.shift_start_s ?? Infinity, ...routes.map((r) => r.start_s))
  const lastEnd = Math.max(...routes.map((r) => r.end_s))
  // Scale to the trucks' own times; the deadline joins the scale only when it is reasonably close, otherwise it is noted at the edge.
  const used = Math.max(lastEnd - t0, 60)
  const deadline = problem?.deadline_s
  const deadlineClose = deadline !== undefined && deadline - t0 <= used * 1.8
  const t1 = deadlineClose ? Math.max(lastEnd, deadline!) : lastEnd + used * 0.08
  const span = Math.max(t1 - t0, 60)
  const x = (t: number) => 70 + ((t - t0) / span) * 510
  const rowH = 30
  const h = 24 + routes.length * rowH
  return (
    <figure className="timeline">
      <svg viewBox={`0 0 650 ${h}`} role="img" aria-label="Timeline of every truck">
        {/* time axis */}
        <text x={70} y={12} className="axis">{clock(t0)}</text>
        {deadlineClose && deadline! > lastEnd ? null : <text x={70 + 510 / 2} y={12} className="axis" textAnchor="middle">{clock(t0 + span / 2)}</text>}
        {deadline !== undefined && deadlineClose && (
          <g>
            <line x1={x(deadline)} x2={x(deadline)} y1={18} y2={h - 4} className="deadline" />
            <text x={x(deadline)} y={12} className="axis deadline-label" textAnchor="end">deadline {clock(deadline)}</text>
          </g>
        )}
        {deadline !== undefined && !deadlineClose && <text x={640} y={12} className="axis deadline-label" textAnchor="end">deadline {clock(deadline)} (off scale)</text>}
        {routes.map((r, i) => {
          const y = 24 + i * rowH
          const color = ROUTE_COLORS[r.vehicle % ROUTE_COLORS.length]
          return (
            <g key={r.vehicle}>
              <text x={0} y={y + 14} className="axis">Truck {r.vehicle + 1}</text>
              <rect x={x(r.start_s)} y={y + 6} width={Math.max(x(r.end_s) - x(r.start_s), 2)} height={12} rx={6} fill={color} opacity={0.35} />
              {r.stops.map((s, k) => (
                <g key={s.order}>
                  <title>{`Truck ${r.vehicle + 1} · stop ${k + 1} · order #${s.order} · ${clock(s.arrive_s)}`}</title>
                  <circle cx={x(s.arrive_s)} cy={y + 12} r={8} fill={color} stroke="#000000" strokeWidth={1.5} />
                  <text x={x(s.arrive_s)} y={y + 15.5} textAnchor="middle" className="tick">{k + 1}</text>
                </g>
              ))}
              <text x={x(r.end_s) + 8} y={y + 15.5} className="axis" textAnchor="start">{`back ${clock(r.end_s)}`}</text>
            </g>
          )
        })}
      </svg>
      <figcaption>Every truck on one clock: the bar is the time away from the depot, the numbered dots are its stops in visiting order.</figcaption>
    </figure>
  )
}
