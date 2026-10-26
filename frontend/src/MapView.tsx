import { useMemo, useRef, useState } from 'react'
import type { Custom, Iteration, Mode, PlanGeo, ReportGeo, RunState, Sample, XY } from './types'

export const ROUTE_COLORS = ['#f43f5e', '#38bdf8', '#4ade80', '#fb923c', '#c084fc', '#2dd4bf']
const ZONE_COLORS: Record<string, string> = {
  industrial: '#ef4444',
  commercial: '#f59e0b',
  residential: '#3b82f6',
  park_forest: '#22c55e',
  other: '#9ca3af',
  custom: '#e879f9',
}

interface Layers { roads: boolean; graph: boolean; zones: boolean; orders: boolean; routes: boolean }

const pts = (poly: XY[]) => poly.map((p) => p.join(',')).join(' ')

export default function MapView(props: {
  sample: Sample
  state: RunState
  selected: number // index of the iteration shown, or -1 for the final result
  plan?: PlanGeo
  report?: ReportGeo
  mode: Mode
  custom: Custom
  onMode: (m: Mode) => void
  onClick: (xy: XY, unit: number) => void
  onCloseZone: () => void
  onClear: () => void
}) {
  const { sample, state, plan, report, mode, custom } = props
  const svgRef = useRef<SVGSVGElement>(null)
  const editing = mode !== 'browse' && (state.status === 'idle' || state.status === 'error')
  const draft = state.status === 'idle' || state.status === 'error'
  const [layers, setLayers] = useState<Layers>({ roads: true, graph: false, zones: true, orders: true, routes: true })
  const u = sample.width / 1536 // marker size unit, so overlays scale with the image
  const avoid = state.problem?.avoid_zone_kinds ?? []

  const edges = useMemo(() => {
    if (!state.graph) return []
    const n = state.graph.nodes
    return state.graph.edges.map(([a, b, speed, bridge]) => ({ a: n[a], b: n[b], speed, bridge }))
  }, [state.graph])

  const click = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!editing || !svgRef.current) return
    const r = svgRef.current.getBoundingClientRect()
    props.onClick([((e.clientX - r.left) / r.width) * sample.width, ((e.clientY - r.top) / r.height) * sample.height], u)
  }
  const toggle = (k: keyof Layers) => setLayers((l) => ({ ...l, [k]: !l[k] }))
  const names: [keyof Layers, string][] = [['roads', 'Road mask'], ['graph', 'Graph'], ['zones', 'Zones'], ['orders', 'Orders'], ['routes', 'Routes']]

  return (
    <div className="map">
      <div className="map-toolbar">
        {names.map(([k, label]) => (
          <button key={k} className={'chip ' + (layers[k] ? 'on' : '')} onClick={() => toggle(k)}>{label}</button>
        ))}
      </div>
      {state.status !== 'running' && (
        <div className="map-toolbar edit">
          <span className="edit-label">Place on the map:</span>
          {([['browse', 'Off'], ['depot', 'Depot'], ['order', 'Orders'], ['zone', 'Avoid zone']] as [Mode, string][]).map(([m, label]) => (
            <button key={m} className={'chip ' + (mode === m ? 'on' : '')} onClick={() => props.onMode(m)}>{label}</button>
          ))}
          {mode === 'zone' && custom.zone.length >= 3 && !custom.zoneClosed && <button className="chip accent" onClick={props.onCloseZone}>Close zone</button>}
          {(custom.depot || custom.orders.length > 0 || custom.zone.length > 0) && <button className="chip" onClick={props.onClear}>Clear mine</button>}
          <span className="edit-hint">
            {mode === 'depot' && 'Click to set the depot.'}
            {mode === 'order' && `Click to add an order, click an order to remove it (${custom.orders.length} placed).`}
            {mode === 'zone' && (custom.zoneClosed ? 'Zone drawn. Click “Clear mine” to redraw.' : 'Click corners; click the first corner or “Close zone” to finish.')}
            {mode === 'browse' && !custom.depot && custom.orders.length === 0 && custom.zone.length === 0 && 'Optional: choose your own depot, orders and a zone to avoid.'}
          </span>
        </div>
      )}
      <div className="map-frame" style={{ aspectRatio: `${sample.width} / ${sample.height}` }}>
        <img src={sample.image} alt="Satellite view" draggable={false} />
        <svg ref={svgRef} viewBox={`0 0 ${sample.width} ${sample.height}`} preserveAspectRatio="xMidYMid meet" onClick={click} className={editing ? 'editing' : ''}>
          {layers.roads && state.mask && <image href={state.mask} width={sample.width} height={sample.height} />}
          {layers.zones &&
            state.zones.map((z, i) => {
              const hot = avoid.includes(z.kind)
              const c = ZONE_COLORS[z.kind] ?? '#9ca3af'
              return <polygon key={i} points={pts(z.polygon)} fill={c} fillOpacity={hot ? 0.28 : 0.07} stroke={c} strokeOpacity={hot ? 0.95 : 0.35} strokeWidth={(hot ? 3 : 1.5) * u} strokeDasharray={hot ? undefined : `${8 * u} ${6 * u}`} />
            })}
          {layers.graph &&
            edges.map((e, i) => (
              <line key={i} x1={e.a[0]} y1={e.a[1]} x2={e.b[0]} y2={e.b[1]} stroke={e.bridge ? '#e879f9' : e.speed >= 50 ? '#fb7185' : e.speed >= 40 ? '#fbbf24' : '#67e8f9'} strokeWidth={3 * u} strokeLinecap="round" />
            ))}
          {layers.routes &&
            plan?.routes.map((r) => (
              <g key={r.vehicle}>
                <polyline points={pts(r.polyline)} fill="none" stroke="#0b1220" strokeOpacity={0.55} strokeWidth={9 * u} strokeLinejoin="round" strokeLinecap="round" />
                <polyline points={pts(r.polyline)} fill="none" stroke={ROUTE_COLORS[r.vehicle % ROUTE_COLORS.length]} strokeWidth={5 * u} strokeLinejoin="round" strokeLinecap="round" />
              </g>
            ))}
          {report?.violations
            .filter((v) => v.segments)
            .flatMap((v) => v.segments!)
            .map(([a, b], i) => (
              <g key={'v' + i}>
                <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#fff" strokeWidth={13 * u} strokeLinecap="round" opacity={0.9} />
                <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#ef4444" strokeWidth={8 * u} strokeLinecap="round" className="pulse" />
                <circle cx={(a[0] + b[0]) / 2} cy={(a[1] + b[1]) / 2} r={30 * u} fill="none" stroke="#ef4444" strokeWidth={4 * u} className="pulse" />
              </g>
            ))}
          {layers.orders &&
            state.orders.map((o, i) => <circle key={i} cx={o[0]} cy={o[1]} r={5 * u} fill="#e5e7eb" stroke="#0b1220" strokeWidth={1.5 * u} opacity={plan ? 0.0 : 0.9} />)}
          {layers.orders &&
            plan?.routes.map((r) =>
              r.stops.map((s, k) => (
                <g key={`${r.vehicle}-${s.order}`}>
                  <circle cx={s.xy[0]} cy={s.xy[1]} r={11 * u} fill={ROUTE_COLORS[r.vehicle % ROUTE_COLORS.length]} stroke="#fff" strokeWidth={2 * u} />
                  <text x={s.xy[0]} y={s.xy[1] + 4.2 * u} textAnchor="middle" fontSize={11.5 * u} fontWeight={700} fill="#fff">{k + 1}</text>
                </g>
              )),
            )}
          {draft && custom.zone.length > 0 && (
            <g>
              {custom.zoneClosed ? (
                <polygon points={pts(custom.zone)} fill="#e879f9" fillOpacity={0.25} stroke="#e879f9" strokeWidth={3 * u} />
              ) : (
                <polyline points={pts(custom.zone)} fill="none" stroke="#e879f9" strokeWidth={3 * u} strokeDasharray={`${8 * u} ${6 * u}`} />
              )}
              {!custom.zoneClosed && custom.zone.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={(i === 0 ? 9 : 5) * u} fill={i === 0 ? '#fff' : '#e879f9'} stroke="#e879f9" strokeWidth={2 * u} />)}
            </g>
          )}
          {draft && custom.orders.map((o, i) => (
            <g key={'d' + i}>
              <circle cx={o[0]} cy={o[1]} r={11 * u} fill="#f8fafc" stroke="#0b1220" strokeWidth={2 * u} />
              <text x={o[0]} y={o[1] + 4.2 * u} textAnchor="middle" fontSize={11.5 * u} fontWeight={700} fill="#0b1220">{i + 1}</text>
            </g>
          ))}
          {draft && custom.depot && (
            <g>
              <rect x={custom.depot[0] - 16 * u} y={custom.depot[1] - 16 * u} width={32 * u} height={32 * u} rx={6 * u} fill="#0b1220" stroke="#facc15" strokeWidth={4 * u} strokeDasharray={`${6 * u} ${4 * u}`} />
              <text x={custom.depot[0]} y={custom.depot[1] + 5 * u} textAnchor="middle" fontSize={15 * u} fontWeight={800} fill="#facc15">D</text>
            </g>
          )}
          {state.depot && (
            <g>
              <rect x={state.depot[0] - 16 * u} y={state.depot[1] - 16 * u} width={32 * u} height={32 * u} rx={6 * u} fill="#0b1220" stroke="#facc15" strokeWidth={4 * u} />
              <text x={state.depot[0]} y={state.depot[1] + 5 * u} textAnchor="middle" fontSize={15 * u} fontWeight={800} fill="#facc15">D</text>
            </g>
          )}
        </svg>
        {state.status === 'running' && <div className="map-stage"><span className="spinner" />{state.stage}</div>}
        {state.status === 'idle' && !editing && !custom.depot && custom.orders.length === 0 && custom.zone.length === 0 && <div className="map-hint">Pick a request and press <b>Plan route</b></div>}
      </div>
      <div className="legend">
        {Array.from(new Set(state.zones.map((z) => z.kind))).map((k) => (
          <span key={k}><i style={{ background: ZONE_COLORS[k] }} />{k.replace('_', '/')}{avoid.includes(k) ? ' (avoid)' : ''}</span>
        ))}
        <span><i className="sq" />depot</span>
        <span className="credit">{sample.credit}</span>
      </div>
    </div>
  )
}

export function IterationTabs(props: { iterations: Iteration[]; selected: number; onSelect: (i: number) => void; running: boolean }) {
  if (!props.iterations.length) return null
  return (
    <div className="tabs">
      {props.iterations.map((it, i) => {
        const state = !it.report ? 'checking' : it.report.ok ? 'ok' : 'fail'
        return (
          <button key={it.n} className={`tab ${state} ${i === props.selected ? 'active' : ''}`} onClick={() => props.onSelect(i)}>
            Plan #{it.n} <b>{state === 'ok' ? '✓ verified' : state === 'fail' ? `✗ ${it.report!.violations.length} violation${it.report!.violations.length > 1 ? 's' : ''}` : '… checking'}</b>
          </button>
        )
      })}
    </div>
  )
}
