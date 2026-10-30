import { useEffect, useMemo, useRef, useState } from 'react'
import { arrowsAlong, buildGeo, pointAt, upTo } from './routeGeometry'
import Timeline from './Timeline'
import { t, zoneName } from './i18n'
import type { Custom, Iteration, Mode, PlanGeo, ReportGeo, RunState, Sample, XY } from './types'

export const ROUTE_COLORS = ['#ff4d4d', '#5fd0ff', '#ffb000', '#7ee787', '#c792ea', '#ff9ecb']
const ZONE_COLORS: Record<string, string> = {
  industrial: '#ef4444',
  commercial: '#f59e0b',
  residential: '#3b82f6',
  park_forest: '#22c55e',
  other: '#9ca3af',
  flooded: '#14d4c4',
  custom: '#e879f9',
}

// Map roads the photo does not confirm: amber dashes = not found in the road mask (trees, shadow or a real problem), red = looked at and blocked, blue = under water
const RISK_COLORS: Record<string, string> = { unseen: '#f59e0b', blocked: '#ef4444', water: '#38bdf8' }

interface Layers { roads: boolean; graph: boolean; zones: boolean; orders: boolean; routes: boolean }

const clock = (sec: number) => `${String(Math.floor(sec / 3600)).padStart(2, '0')}:${String(Math.floor((sec % 3600) / 60)).padStart(2, '0')}`
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
  onUndo: () => void
  onRedrawZone: () => void
  auto: boolean
  autoCount: number
  onAuto: (v: boolean) => void
  onAutoCount: (n: number) => void
  stale: boolean
  onDrag: (kind: 'depot' | 'order', i: number, xy: XY) => void
  onEditPlan: () => void
  onQuickStart: () => void
  onPickArea: () => void
  depotOverride?: XY // a relaxation that moves the depot: where it goes
  evidence: boolean // draw the map roads the photo does not confirm on the routes
  onEvidence: (v: boolean) => void
}) {
  const { sample, state, plan, report, mode, custom } = props
  const svgRef = useRef<SVGSVGElement>(null)
  const editing = mode !== 'browse' && state.status !== 'running'
  const draft = state.status === 'idle' || state.status === 'error' || props.stale // your points, drawn on the map and draggable
  const [drag, setDrag] = useState<{ kind: 'depot' | 'order'; i: number } | null>(null)
  const [heroOff, setHeroOff] = useState(false) // "Place my own points" closes the welcome card so the map underneath can be clicked
  useEffect(() => setHeroOff(false), [sample.name]) // a new image gets the card again
  useEffect(() => {
    if (state.errorPoint) setLayers((l) => ({ ...l, graph: true, roads: true })) // show the roads that were found next to the offending point
  }, [state.errorPoint])
  const dragged = useRef({ moved: false, suppress: false, start: [0, 0] as XY })
  const [layers, setLayers] = useState<Layers>({ roads: true, graph: false, zones: true, orders: true, routes: true })
  const u = sample.width / 1536 // marker size unit, so overlays scale with the image
  const avoid = state.problem?.avoid_zone_kinds ?? []
  const depot = props.depotOverride ?? state.depot

  // Replay of the drive: progress 0..1 along the longest route (null = show the finished plan).
  const [progress, setProgress] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [hover, setHover] = useState<{ vehicle: number; stop: number } | null>(null)
  const [pick, setPick] = useState<{ vehicle: number; stop: number } | null>(null) // the order chosen from a list or on the map: its leg is shown, the rest is dimmed
  const geos = useMemo(() => (plan ? plan.routes.map(buildGeo) : []), [plan])
  const longest = Math.max(1, ...geos.map((g) => g.total))
  const dCur = progress === null ? Infinity : progress * longest
  useEffect(() => {
    setProgress(null)
    setPlaying(false)
    setHover(null)
    setPick(null)
  }, [plan])
  useEffect(() => {
    if (!playing) return
    let raf = 0
    let last = performance.now()
    const REPLAY_SECONDS = 14 // the longest route takes this long to drive on screen
    const tick = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      setProgress((p) => {
        const next = (p ?? 0) + dt / REPLAY_SECONDS
        if (next >= 1) {
          setPlaying(false)
          return 1
        }
        return next
      })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])
  const togglePlay = () => {
    if (playing) return setPlaying(false)
    if (progress === null || progress >= 1) setProgress(0)
    setPlaying(true)
  }

  const edges = useMemo(() => {
    if (!state.graph) return []
    const n = state.graph.nodes
    return state.graph.edges.map(([a, b, speed, bridge], i) => ({ a: n[a], b: n[b], speed, bridge, risk: state.edgeRisk?.[i] ?? 'seen' }))
  }, [state.graph, state.edgeRisk])

  const toImage = (e: React.MouseEvent<SVGSVGElement>): XY | null => {
    if (!svgRef.current) return null
    const r = svgRef.current.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * sample.width, ((e.clientY - r.top) / r.height) * sample.height]
  }
  const click = (e: React.MouseEvent<SVGSVGElement>) => {
    if (dragged.current.suppress) { dragged.current.suppress = false; return } // the click that ends a drag is not a new point
    const xy = toImage(e)
    if (editing && xy) props.onClick(xy, u)
  }
  const move = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!drag) return
    const xy = toImage(e)
    if (!xy) return
    if (!dragged.current.moved && Math.hypot(xy[0] - dragged.current.start[0], xy[1] - dragged.current.start[1]) < 8 * u) return
    dragged.current.moved = true
    props.onDrag(drag.kind, drag.i, [Math.max(0, Math.min(sample.width, xy[0])), Math.max(0, Math.min(sample.height, xy[1]))])
  }
  const endDrag = () => {
    if (drag && dragged.current.moved) dragged.current.suppress = true
    setDrag(null)
    dragged.current.moved = false
  }
  const startDrag = (kind: 'depot' | 'order', i: number) => (e: React.MouseEvent) => {
    if (!draft || mode === 'zone') return
    e.stopPropagation()
    const r = svgRef.current?.getBoundingClientRect()
    if (!r) return
    dragged.current.start = [((e.clientX - r.left) / r.width) * sample.width, ((e.clientY - r.top) / r.height) * sample.height]
    dragged.current.moved = false
    setDrag({ kind, i })
  }
  const lenPx = (leg: XY[]) => leg.reduce((n, p, i) => (i ? n + Math.hypot(p[0] - leg[i - 1][0], p[1] - leg[i - 1][1]) : 0), 0)
  const pickIdx = pick && plan ? plan.routes.findIndex((r) => r.vehicle === pick.vehicle) : -1
  const pickStop = pick && pickIdx >= 0 ? plan!.routes[pickIdx].stops[pick.stop] : undefined
  const pickKm = pick && pickIdx >= 0 && geos[pickIdx]?.legs[pick.stop] ? (lenPx(geos[pickIdx].legs[pick.stop]) * sample.m_per_px) / 1000 : 0
  const choose = (vehicle: number, stop: number) => setPick((p) => (p && p.vehicle === vehicle && p.stop === stop ? null : { vehicle, stop }))
  const hasEvidence = (report?.flagged?.length ?? 0) > 0 || (report?.unconfirmed?.length ?? 0) > 0 || (state.inspections?.some((f) => f.verdict === 'blocked') ?? false)
  const toggle = (k: keyof Layers) => setLayers((l) => ({ ...l, [k]: !l[k] }))
  const names: [keyof Layers, string][] = [['roads', 'Road mask'], ['graph', 'Graph'], ['zones', 'Zones'], ['orders', 'Orders'], ['routes', 'Routes']]

  return (
    <div className="map">
      <div className="map-toolbar">
        {names.map(([k, label]) => (
          <button key={k} className={'chip ' + (layers[k] ? 'on' : '')} onClick={() => toggle(k)}>{t(label)}</button>
        ))}
        {hasEvidence && <button className={'chip ' + (props.evidence ? 'on' : '')} onClick={() => props.onEvidence(!props.evidence)} title={t('Show the map roads the photo does not confirm on the routes')}>{t('Evidence')}</button>}
      </div>
      {state.status !== 'running' && (
        <div className="steps-wrap">
          <div className="steps">
            <button className={'step ' + (mode === 'depot' ? 'active ' : '') + (custom.depot ? 'done' : '')} onClick={() => props.onMode('depot')}>
              <i>{custom.depot ? '✓' : '1'}</i> {t('Depot')}
            </button>
            <button className={'step ' + (mode === 'order' ? 'active ' : '') + (custom.orders.length > 0 ? 'done' : '')} onClick={() => props.onMode('order')}>
              <i>{custom.orders.length > 0 ? '✓' : '2'}</i> {t('Orders')}{custom.orders.length > 0 ? ` (${custom.orders.length})` : ''}
            </button>
            <button className={'step ' + (mode === 'zone' ? 'active ' : '') + (custom.zoneClosed ? 'done' : '')} onClick={() => props.onMode('zone')}>
              <i>{custom.zoneClosed ? '✓' : '3'}</i> {t('Zone to avoid')} <small>{t('optional')}</small>
            </button>
            {mode === 'zone' && custom.zone.length >= 3 && !custom.zoneClosed && <button className="chip accent" onClick={props.onCloseZone}>{t('Close zone')}</button>}
            <span className="spacer" />
            <label className="auto" title={t('Let the agent scatter random orders on the roads instead of clicking them')}>
              <input type="checkbox" checked={props.auto} onChange={(e) => props.onAuto(e.target.checked)} />
              {t('Place orders for me')}
              <input type="number" min={1} max={100} value={props.autoCount} disabled={!props.auto} onChange={(e) => props.onAutoCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} aria-label={t('Number of random orders')} />
            </label>
            {state.status === 'done' && !props.stale && <button className="chip accent" onClick={props.onEditPlan}>✎ {t('Edit this plan')}</button>}
            {mode === 'zone' && custom.zone.length > 0 && <button className="chip" onClick={props.onRedrawZone}>{t('Redraw zone')}</button>}
            {(custom.depot || custom.orders.length > 0 || custom.zone.length > 0) && mode !== 'browse' && <button className="chip" onClick={props.onUndo} title={t('Remove the last point of the current step')}>↶ {t('Undo')}</button>}
            {(custom.depot || custom.orders.length > 0 || custom.zone.length > 0) && <button className="chip" onClick={props.onClear}>{t('Clear')}</button>}
          </div>
          <p className="edit-hint">
            {mode === 'depot' && t('Click the map to place the depot — where the trucks start and finish.')}
            {mode === 'order' && (props.auto ? t('The agent will place the orders. Click the map to place your own instead.') : t('Click the map to add an order; click an order to remove it.') + (custom.orders.length ? ` ${t('({n} placed)', { n: custom.orders.length })}` : ''))}
            {mode === 'zone' && (custom.zoneClosed ? t('Zone drawn. Press “Redraw zone” to change it, or Undo to take back the last corner.') : t('Click corners of an area the trucks must avoid; click the first corner or “Close zone” to finish.'))}
            {mode === 'browse' && (state.status === 'done' ? t('Press “Edit this plan” to move the depot, drag orders or add new ones.') : t('View only. Pick a step above to place points.'))}
          </p>
        </div>
      )}
      <div className="map-frame" style={{ aspectRatio: `${sample.width} / ${sample.height}` }}>
        <img src={sample.image} alt={t('Satellite view')} draggable={false} />
        <svg ref={svgRef} viewBox={`0 0 ${sample.width} ${sample.height}`} preserveAspectRatio="xMidYMid meet" onClick={click} onMouseMove={move} onMouseUp={endDrag} onMouseLeave={endDrag} className={(editing ? 'editing ' : '') + (draft && mode !== 'zone' ? 'draggable' : '')}>
          {layers.roads && state.mask && <image href={state.mask} width={sample.width} height={sample.height} />}
          {layers.zones &&
            state.zones.map((z, i) => {
              const hot = avoid.includes(z.kind)
              const c = ZONE_COLORS[z.kind] ?? '#9ca3af'
              return <polygon key={i} points={pts(z.polygon)} fill={c} fillOpacity={hot ? 0.28 : 0.07} stroke={c} strokeOpacity={hot ? 0.95 : 0.35} strokeWidth={(hot ? 3 : 1.5) * u} strokeDasharray={hot ? undefined : `${8 * u} ${6 * u}`} />
            })}
          {layers.graph &&
            edges.map((e, i) => (
              <line key={i} x1={e.a[0]} y1={e.a[1]} x2={e.b[0]} y2={e.b[1]} stroke={e.risk === 'water' ? RISK_COLORS.water : e.risk === 'blocked' ? RISK_COLORS.blocked : e.risk === 'unseen' ? RISK_COLORS.unseen : e.bridge ? '#e879f9' : e.speed >= 50 ? '#fb7185' : e.speed >= 40 ? '#fbbf24' : '#67e8f9'} strokeWidth={3 * u} strokeLinecap="round" strokeDasharray={e.risk === 'unseen' ? `${5 * u} ${5 * u}` : undefined} />
            ))}
          {layers.routes &&
            plan?.routes.map((r, ri) => {
              const color = ROUTE_COLORS[r.vehicle % ROUTE_COLORS.length]
              const g = geos[ri]
              if (!g) return null
              const replay = progress !== null
              const faded = props.stale
              const cur = replay ? Math.min(dCur, g.total) : g.total
              return (
                <g key={r.vehicle} opacity={faded ? 0.28 : 1}>
                  {/* the whole route, faded while replaying; the last leg (back to the depot) is dashed */}
                  {g.legs.map((leg, li) => {
                    const chosen = pick !== null && pick.vehicle === r.vehicle && pick.stop === li
                    return (
                      <g key={li} opacity={pick ? (chosen ? 1 : 0.14) : replay ? 0.35 : 1}>
                        <polyline points={pts(leg)} fill="none" stroke="#000000" strokeOpacity={0.55} strokeWidth={9 * u} strokeLinejoin="round" strokeLinecap="round" />
                        {chosen && <polyline points={pts(leg)} fill="none" stroke="#ffffff" strokeWidth={13 * u} strokeLinejoin="round" strokeLinecap="round" />}
                        <polyline points={pts(leg)} fill="none" stroke={color} strokeWidth={(chosen ? 7 : 5) * u} strokeLinejoin="round" strokeLinecap="round" strokeDasharray={li === g.legs.length - 1 ? `${12 * u} ${9 * u}` : undefined} />
                      </g>
                    )
                  })}
                  {replay && cur > 0 && <polyline points={pts(upTo(g.flat, cur))} fill="none" stroke={color} strokeWidth={7 * u} strokeLinejoin="round" strokeLinecap="round" />}
                  {/* direction of travel */}
                  {g.legs.map((leg, li) => (
                    <g key={li} opacity={pick ? (pick.vehicle === r.vehicle && pick.stop === li ? 1 : 0.14) : 1}>
                      {arrowsAlong(leg, 180 * u).map((a, ai) => (
                        <polygon key={ai} points={`${7 * u},0 ${-5 * u},${-5.5 * u} ${-5 * u},${5.5 * u}`} transform={`translate(${a.xy[0]} ${a.xy[1]}) rotate(${(a.angle * 180) / Math.PI})`} fill="#fff" stroke="#000000" strokeWidth={1.6 * u} strokeLinejoin="round" />
                      ))}
                    </g>
                  ))}
                  {replay && (() => {
                    const p = pointAt(g.flat, cur)
                    return (
                      <g transform={`translate(${p.xy[0]} ${p.xy[1]})`}>
                        <circle r={13 * u} fill={color} stroke="#fff" strokeWidth={3 * u} />
                        <polygon points={`${8 * u},0 ${-4 * u},${-5.5 * u} ${-4 * u},${5.5 * u}`} transform={`rotate(${(p.angle * 180) / Math.PI})`} fill="#fff" />
                      </g>
                    )
                  })()}
                </g>
              )
            })}
          {layers.zones && state.exposure?.shelters.map((s, i) => (
            <g key={'sh' + i}>
              <rect x={s.xy[0] - 16 * u} y={s.xy[1] - 16 * u} width={32 * u} height={32 * u} fill="#22c55e" stroke="#052e16" strokeWidth={2 * u} />
              <text x={s.xy[0]} y={s.xy[1] + 6 * u} textAnchor="middle" fontSize={18 * u} fontWeight={700} fill="#052e16">S</text>
            </g>
          ))}
          {layers.routes && props.evidence && state.inspections?.filter((f) => f.verdict === 'blocked').flatMap((f) => f.segments).map(([a, b], i) => (
            <line key={'ib' + i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={RISK_COLORS.blocked} strokeWidth={2 * u} strokeDasharray={`${2 * u} ${4 * u}`} strokeLinecap="round" opacity={0.9} />
          ))}
          {layers.routes && props.evidence && report?.flagged?.map(([a, b], i) => (
            <line key={'f' + i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#fff" strokeWidth={5 * u} strokeLinecap="round" opacity={0.85} />
          ))}
          {layers.routes && props.evidence && report?.flagged?.map(([a, b, risk], i) => (
            <line key={'fc' + i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={RISK_COLORS[risk] ?? '#f59e0b'} strokeWidth={3 * u} strokeDasharray={`${4 * u} ${5 * u}`} strokeLinecap="round" />
          ))}
          {layers.routes && props.evidence && report?.unconfirmed?.map(([a, b], i) => (
            <line key={'u' + i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#fff" strokeWidth={3 * u} strokeDasharray={`${3 * u} ${6 * u}`} strokeLinecap="round" opacity={0.95} />
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
            state.orders.map((o, i) => <circle key={i} cx={o[0]} cy={o[1]} r={5 * u} fill="#e5e7eb" stroke="#000000" strokeWidth={1.5 * u} opacity={plan ? 0.0 : 0.9} />)}
          {layers.orders && state.orderTargets.map((target, i) => {
            const o = state.orders[i]
            if (!target || !o) return null
            return (
              <g key={'b' + i} opacity={0.9}>
                <line x1={o[0]} y1={o[1]} x2={target[0]} y2={target[1]} stroke="#ffb000" strokeWidth={1.6 * u} strokeDasharray={`${3 * u} ${2.5 * u}`} />
                <rect x={target[0] - 5 * u} y={target[1] - 5 * u} width={10 * u} height={10 * u} fill="#ffb000" stroke="#000000" strokeWidth={1.4 * u}><title>{t('Order {n}: a building found by SAM 3.1, served from the nearest road', { n: i + 1 })}</title></rect>
              </g>
            )
          })}
          {layers.orders && Object.keys(report?.excluded ?? {}).map((id) => {
            const o = state.orders[Number(id) - 1]
            if (!o) return null
            return (
              <g key={'x' + id}>
                <title>{t('Order #{n} is left out: {why}', { n: id, why: report?.excluded[id] ?? '' })}</title>
                <circle cx={o[0]} cy={o[1]} r={18 * u} fill="#1a0000" fillOpacity={0.85} stroke="#ff4d4d" strokeWidth={4 * u} strokeDasharray={`${5 * u} ${4 * u}`} />
                <text x={o[0]} y={o[1] + 8 * u} textAnchor="middle" fontSize={24 * u} fontWeight={800} fill="#ff4d4d">×</text>
              </g>
            )
          })}
          {layers.orders && !props.stale &&
            plan?.routes.map((r, ri) =>
              r.stops.map((st, k) => {
                const color = ROUTE_COLORS[r.vehicle % ROUTE_COLORS.length]
                const visited = progress === null || dCur >= (geos[ri]?.stopDist[k] ?? 0) - 0.5
                const hot = hover?.vehicle === r.vehicle && hover.stop === k
                const chosen = pick !== null && pick.vehicle === r.vehicle && pick.stop === k
                const nearChosen = pick !== null && pick.vehicle === r.vehicle && pick.stop === k + 1 // the stop the chosen leg starts from
                const shown = pick ? (chosen || nearChosen ? 1 : 0.22) : visited ? 1 : 0.5
                return (
                  <g key={`${r.vehicle}-${st.order}`} opacity={shown} className="stop" onClick={(e) => { e.stopPropagation(); choose(r.vehicle, k) }} onMouseEnter={() => setHover({ vehicle: r.vehicle, stop: k })} onMouseLeave={() => setHover(null)}>
                    <title>{t('Truck {v} · stop {k} of {n} · order #{o} · arrives {time}', { v: r.vehicle + 1, k: k + 1, n: r.stops.length, o: st.order, time: clock(st.arrive_s) })}</title>
                    {(hot || chosen) && <circle cx={st.xy[0]} cy={st.xy[1]} r={24 * u} fill="none" stroke="#fff" strokeWidth={3 * u} />}
                    <circle cx={st.xy[0]} cy={st.xy[1]} r={14 * u} fill={visited ? color : '#000000'} stroke={visited ? '#fff' : color} strokeWidth={3 * u} />
                    <text x={st.xy[0]} y={st.xy[1] + 5 * u} textAnchor="middle" fontSize={14 * u} fontWeight={800} fill="#fff">{k + 1}</text>
                    {/* the order's own number (the one you gave it when placing it), shown for the stop you point at or have chosen */}
                    {(hot || chosen) && (
                      <g transform={`translate(${st.xy[0] + 12 * u} ${st.xy[1] - 27 * u})`}>
                        <rect width={(10 + 9 * String(st.order).length) * u} height={16 * u} rx={8 * u} fill="#000000" fillOpacity={0.88} stroke={color} strokeWidth={1.5 * u} />
                        <text x={((10 + 9 * String(st.order).length) / 2) * u} y={11.5 * u} textAnchor="middle" fontSize={11 * u} fontWeight={700} fill="#fff">{`#${st.order}`}</text>
                      </g>
                    )}
                  </g>
                )
              }),
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
            <g key={'d' + i} className="grab" onMouseDown={startDrag('order', i)}>
              <title>{t('Your order {n} — drag to move, click to remove', { n: i + 1 })}</title>
              {state.errorPoint?.kind === 'order' && state.errorPoint.index === i && <circle cx={o[0]} cy={o[1]} r={30 * u} fill="none" stroke="#ef4444" strokeWidth={5 * u} className="pulse" />}
              <circle cx={o[0]} cy={o[1]} r={15 * u} fill="#f8fafc" stroke="#000000" strokeWidth={3 * u} />
              <text x={o[0]} y={o[1] + 5.2 * u} textAnchor="middle" fontSize={15 * u} fontWeight={800} fill="#000000">{i + 1}</text>
            </g>
          ))}
          {draft && custom.depot && (
            <g className="grab" onMouseDown={startDrag('depot', 0)}>
              <title>{t('Depot — drag to move it')}</title>
              {state.errorPoint?.kind === 'depot' && <circle cx={custom.depot[0]} cy={custom.depot[1]} r={32 * u} fill="none" stroke="#ef4444" strokeWidth={5 * u} className="pulse" />}
              <rect x={custom.depot[0] - 16 * u} y={custom.depot[1] - 16 * u} width={32 * u} height={32 * u} rx={6 * u} fill="#000000" stroke="#facc15" strokeWidth={4 * u} strokeDasharray={`${6 * u} ${4 * u}`} />
              <text x={custom.depot[0]} y={custom.depot[1] + 5 * u} textAnchor="middle" fontSize={15 * u} fontWeight={800} fill="#facc15">D</text>
            </g>
          )}
          {depot && !props.stale && (
            <g>
              <rect x={depot[0] - 16 * u} y={depot[1] - 16 * u} width={32 * u} height={32 * u} rx={6 * u} fill="#000000" stroke="#facc15" strokeWidth={4 * u} />
              <text x={depot[0]} y={depot[1] + 5 * u} textAnchor="middle" fontSize={15 * u} fontWeight={800} fill="#facc15">D</text>
            </g>
          )}
        </svg>
        {state.status === 'running' && <div className="map-stage"><span className="spinner" />{state.stage}</div>}
        {state.status === 'idle' && !heroOff && !custom.depot && custom.orders.length === 0 && !props.auto && (
          <div className="hero" role="region" aria-label={t('Get started')}>
            {sample.event ? (
              <>
                <h3>{t('Plan relief deliveries through the flood')}</h3>
                <p>{t('A navigator knows the roads as they were before {event}. This is the photo taken during it: the agent finds the water, keeps the trucks out of it and checks its own plan.', { event: sample.event ?? '' })}</p>
              </>
            ) : (
              <>
                <h3>{t('Plan deliveries from a satellite photo')}</h3>
                <p>{t('Place a depot and some orders, say what to avoid, and the agent plans the routes — then checks its own work.')}</p>
              </>
            )}
            <div className="hero-actions">
              <button className="primary inline" onClick={props.onQuickStart}>▶ {t('Try it with 20 random orders')}</button>
              <button className="chip" onClick={() => { setHeroOff(true); props.onMode('depot') }}>{t('Place my own points')}</button>
              <button className="chip" onClick={props.onPickArea}>{t('Choose another area')}</button>
            </div>
          </div>
        )}
      </div>
      {pick && pickStop && (
        <div className="pick-info" role="status">
          <span>{t('Truck {v} → order #{o} (stop {k} of {n}) · arrives {time} · {km} km from the previous point', { v: pick.vehicle + 1, o: pickStop.order, k: pick.stop + 1, n: plan!.routes[pickIdx].stops.length, time: clock(pickStop.arrive_s), km: pickKm.toFixed(1) })}</span>
          <button className="chip" onClick={() => setPick(null)}>{t('Show all')}</button>
        </div>
      )}
      {plan && plan.routes.length > 0 && (
        <div className="drive">
          <div className="replay">
            <button className="chip on" onClick={togglePlay}>{playing ? `⏸ ${t('Pause')}` : progress !== null && progress >= 1 ? `↺ ${t('Replay the drive')}` : `▶ ${t('Replay the drive')}`}</button>
            <input type="range" min={0} max={1000} value={Math.round((progress ?? 1) * 1000)} onChange={(e) => { setPlaying(false); setProgress(Number(e.target.value) / 1000) }} aria-label={t('Replay position')} />
            {progress !== null && <button className="chip" onClick={() => { setPlaying(false); setProgress(null) }}>{t('Show all')}</button>}
          </div>
          <div className="trucks" aria-label={t('Trucks')}>
            {plan.routes.map((r) => {
              const color = ROUTE_COLORS[r.vehicle % ROUTE_COLORS.length]
              return (
                <div key={r.vehicle} className="truck-card" style={{ borderColor: color }}>
                  <div className="truck-head"><i style={{ background: color }} /><b>{t('Truck')} {r.vehicle + 1}</b><span>{t('{n} stops', { n: r.stops.length })} · {(r.distance_m / 1000).toFixed(1)} {t('km')}</span></div>
                  <ol className="sequence">
                    <li className="end"><span className="dot depot">D</span> {t('Leaves the depot')} <time>{clock(r.start_s)}</time></li>
                    {r.stops.map((st, k) => (
                      <li key={st.order} className={(hover?.vehicle === r.vehicle && hover.stop === k ? 'hot ' : '') + (pick?.vehicle === r.vehicle && pick.stop === k ? 'chosen' : '')} onMouseEnter={() => setHover({ vehicle: r.vehicle, stop: k })} onMouseLeave={() => setHover(null)}>
                        <button type="button" className="row-pick" onClick={() => choose(r.vehicle, k)} title={t('Show the way to this order on the map')} aria-pressed={pick?.vehicle === r.vehicle && pick.stop === k}>
                          <span className="dot" style={{ background: color }}>{k + 1}</span> {t('Order')} #{st.order} <time>{clock(st.arrive_s)}</time>
                        </button>
                      </li>
                    ))}
                    <li className="end"><span className="dot depot">D</span> {t('Back at the depot')} <time>{clock(r.end_s)}</time></li>
                  </ol>
                </div>
              )
            })}
          </div>
          <Timeline plan={plan} problem={state.problem} />
          <p className="trucks-note">{t('Click an order in a list to see the way to it on the map. Arrows show the direction of travel and the dashed leg is the way back to the depot. The number in the circle is the order a truck visits the stop in (it restarts for every truck); the tag like #7 is the order\'s own number from when you placed it. The agent chooses the visiting sequence itself, to keep the driving time as short as possible.')} {state.problem ? t('One trip per truck; capacity {n} each.', { n: state.problem.capacity }) : t('One trip per truck.')}</p>
        </div>
      )}
      <div className="legend">
        <span className="legend-title" title={t('Muse Spark outlines these areas on the image; the outlines are approximate.')}>{t('Land use')}</span>
        {Array.from(new Set(state.zones.map((z) => z.kind))).map((k) => (
          <span key={k}><i style={{ background: ZONE_COLORS[k] }} />{k === 'flooded' ? t('flood water') : zoneName(k)}{avoid.includes(k) ? ` — ${t('trucks avoid it')}` : ''}</span>
        ))}
      </div>
      <div className="legend symbols">
        <span className="legend-title">{t('Symbols')}</span>
        <span><i className="sq" />{t('Depot: where every truck starts and ends')}</span>
        <span><i className="line" />{t('A colour is one truck; arrows show the direction, the dashed part is the way back')}</span>
        <span><i className="num">2</i>{t("Order number in the circle = the order the truck visits it in; #7 = the order's own number")}</span>
        {props.evidence && (report?.flagged?.length ?? 0) > 0 && <span><i className="gap" />{t('Coloured dashes on a route = a map road the photo does not confirm: amber, not found in the road mask (trees, shadow or a real problem); blue, under water; red, looked at and blocked')}</span>}
        {(state.exposure?.shelters.length ?? 0) > 0 && <span><i className="bld" />{t('Green S = a large dry building a crowd could be put up in, reachable by roads that are not under water (a rough guess from the photo)')}</span>}
        {props.evidence && (state.inspections?.some((f) => f.verdict === 'blocked') ?? false) && <span><i className="gap" />{t('Red dots = Muse Spark looked at a stretch the photo does not confirm and found standing water or debris; the agent planned around it where it could')}</span>}
        {props.evidence && (report?.unconfirmed?.length ?? 0) > 0 && <span><i className="gap" />{t('White dots on a route = a link drawn across a gap in the roads found; the photo does not show a road there')}</span>}
        <span><i className="viol" />{t('Red pulsing road = a plan broke the “avoid” rule there')}</span>
        {state.orderTargets.some(Boolean) && <span><i className="bld" />{t('Amber square = the building an order belongs to; the dashed line is the road it is served from')}</span>}
        {Object.keys(report?.excluded ?? {}).length > 0 && <span><i className="cut">×</i>{t('Dashed red × = an order left out because the zone cuts it off')}</span>}
        <span className="credit">{sample.credit}{state.roadSource === 'osm' ? ` · ${t('Roads: © OpenStreetMap contributors (ODbL)')}` : ''}</span>
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
            {t('Plan #{n}', { n: it.n })} <b>{state === 'ok' ? `✓ ${t('verified')}` : state === 'fail' ? `✗ ${t('{n} violations', { n: it.report!.violations.length })}` : `… ${t('checking')}`}</b>
          </button>
        )
      })}
    </div>
  )
}
