import { useEffect, useMemo, useRef, useState } from 'react'
import AreaPicker from './AreaPicker'
import Stepper from './Stepper'
import { useVoice } from './useVoice'
import MapView, { IterationTabs } from './MapView'
import { emptyCustom } from './types'
import type { Custom, LogEntry, Mode, PlanGeo, ReportGeo, Result, RunState, Sample, XY } from './types'
import { useRun } from './useRun'

const ICONS: Record<string, string> = { error: '⚠', stage: '◌', perception: '▦', scene: '◫', problem: '☰', scenario: '⌖', start: '▶', solve: '◆', verify_ok: '✓', verify_fail: '✗', decision: '?', repair: '↻', relaxation: '≈', final: '■' }

function fmtT(s: number) {
  return `${Math.max(s, 0).toFixed(1)}s`
}

function RequestPanel(props: {
  samples: Sample[]
  sample?: Sample
  onSample: (n: string) => void
  onPickArea: () => void
  request: string
  onRequest: (r: string) => void
  onPlan: () => void
  state: RunState
  custom: Custom
  auto: boolean
  autoCount: number
  canPlan: boolean
  hasPlan: boolean
  trucks: number
  onTrucks: (n: number) => void
}) {
  const { sample, state, custom } = props
  const running = state.status === 'running'
  const voice = useVoice(props.onRequest)
  return (
    <section className="panel request">
      <h2>Request</h2>
      <label>Satellite image</label>
      <select value={sample?.name} onChange={(e) => props.onSample(e.target.value)} disabled={running}>
        {props.samples.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
      </select>
      <button className="link" onClick={props.onPickArea} disabled={running}>＋ Choose another area on the map</button>
      <div className="field-row">
        <label htmlFor="trucks">Trucks</label>
        <div className="count">
          <button type="button" onClick={() => props.onTrucks(Math.max(1, props.trucks - 1))} disabled={running || props.trucks <= 1} aria-label="Fewer trucks">−</button>
          <input id="trucks" type="number" min={1} max={30} value={props.trucks} disabled={running} onChange={(e) => props.onTrucks(Math.max(1, Math.min(30, Number(e.target.value) || 1)))} />
          <button type="button" onClick={() => props.onTrucks(Math.min(30, props.trucks + 1))} disabled={running || props.trucks >= 30} aria-label="More trucks">+</button>
        </div>
      </div>
      <label>Time and what to avoid</label>
      <textarea value={props.request} onChange={(e) => props.onRequest(e.target.value)} rows={4} maxLength={400} disabled={running} placeholder="by 18:00, avoid the industrial zone" />
      <div className="voice">
        <button type="button" className={'mic ' + voice.phase} onClick={voice.toggle} disabled={running || voice.phase === 'sending' || !voice.supported} aria-pressed={voice.phase === 'recording'}>
          {voice.phase === 'recording' ? '■ Stop' : voice.phase === 'sending' ? 'Listening to it…' : '🎙 Speak'}
        </button>
        <span className="voice-note">
          {voice.phase === 'recording' ? 'Recording… say the time and what to avoid.' : voice.error ? <em className="err">{voice.error}</em> : voice.heard ? <>Heard: “{voice.heard}”</> : 'or say it — Muse Voice Transcribe'}
        </span>
      </div>
      <div className="examples">
        {sample?.examples.map((ex) => <button key={ex} className="example" onClick={() => props.onRequest(ex)} disabled={running}>{ex}</button>)}
      </div>
      <ul className="checklist-mini">
        <li className={custom.depot ? 'ok' : ''}>{custom.depot ? '✓' : '○'} Depot {custom.depot ? 'placed' : 'not placed'}</li>
        <li className={custom.orders.length > 0 || props.auto ? 'ok' : ''}>
          {custom.orders.length > 0 || props.auto ? '✓' : '○'} {custom.orders.length > 0 ? `${custom.orders.length} order${custom.orders.length > 1 ? 's' : ''} placed by you` : props.auto ? `${props.autoCount} random orders (agent places them)` : 'Orders not placed'}
        </li>
        <li className={custom.zoneClosed ? 'ok' : 'opt'}>{custom.zoneClosed ? '✓ Your avoid-zone drawn' : '○ Zone to avoid (optional)'}</li>
      </ul>
      <button className="primary" onClick={props.onPlan} disabled={running || !props.canPlan}>{running ? 'Agent working…' : props.hasPlan ? 'Replan' : 'Plan route'}</button>
      {!props.canPlan && !running && <p className="muted small">Place the depot and at least one order on the map, or tick “Place orders for me”.</p>}
      {state.problem && (
        <div className="understood">
          <h3>What the agent understood</h3>
          <dl>
            <dt>Orders</dt><dd>{state.problem.n_orders}</dd>
            <dt>Trucks</dt><dd>{state.problem.n_vehicles} × {state.problem.capacity} units</dd>
            <dt>Avoid</dt><dd>{state.problem.avoid_zone_kinds.join(', ') || 'nothing'}</dd>
          </dl>
          {state.problem.assumptions.length > 0 && (
            <>
              <h4>Assumed or adjusted</h4>
              <ul>{state.problem.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            </>
          )}
        </div>
      )}
    </section>
  )
}

function AgentLog({ log, running }: { log: LogEntry[]; running: boolean }) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [log.length])
  return (
    <section className="panel log">
      <h2>Agent log</h2>
      {!log.length && <p className="muted">The agent's steps appear here: perceive, understand, solve, verify, repair.</p>}
      <ol>
        {log.map((l) => (
          <li key={l.id} className={l.type}>
            <span className="icon">{ICONS[l.type] ?? '·'}</span>
            <span className="text">
              {l.type === 'decision' && <em className="badge">{l.source === 'model' ? 'Muse Spark decides' : 'policy decides'}</em>}
              {l.text}
            </span>
            <span className="time">{fmtT(l.t)}</span>
          </li>
        ))}
      </ol>
      {running && <div className="working"><span className="spinner" /> working…</div>}
      <div ref={end} />
    </section>
  )
}

function Checklist({ report, title }: { report?: ReportGeo; title: string }) {
  return (
    <section className="panel checklist">
      <h2>Verification <small>{title}</small></h2>
      {!report && <p className="muted">An independent verifier re-simulates every route on the road graph and checks six things.</p>}
      <ul>
        {report?.checks.map((c) => (
          <li key={c.kind} className={c.passed ? 'pass' : 'fail'}>
            <span className="mark">{c.passed ? '✓' : '✗'}</span>
            <div><b>{c.title}</b><span>{c.detail}</span></div>
          </li>
        ))}
      </ul>
      {report?.violations.map((v, i) => <p key={i} className="violation">{v.message}</p>)}
    </section>
  )
}

function ResultBar(props: { state: RunState; onShowRelax: (i: number | null) => void; relax: number | null }) {
  const { state } = props
  const r: Result | undefined = state.result
  if (state.status === 'error') return <div className="result error"><b>Something went wrong.</b> {state.error}</div>
  if (!r) return <div className="result idle">{state.status === 'running' ? 'The agent is working on it…' : 'No plan yet.'}</div>
  const total = state.problem?.n_orders ?? r.plan.served
  const excluded = Object.keys(r.excluded).length
  const trucks = r.plan.routes.length
  const label = r.status === 'verified' ? 'VERIFIED' : r.status === 'verified_partial' ? 'VERIFIED · PARTIAL' : r.status === 'needs_relaxation' ? 'CAN’T MEET AS STATED' : 'UNRESOLVED'
  return (
    <div className={`result ${r.status}`}>
      <div className="verdict">{label}</div>
      <div className="tiles">
        <div className="tile"><b>{r.plan.served}<small>/{total}</small></b><span>orders served</span></div>
        <div className="tile"><b>{trucks}</b><span>truck{trucks === 1 ? '' : 's'} used</span></div>
        <div className="tile"><b>{r.report.metrics.last_return}</b><span>last truck back</span></div>
        <div className="tile"><b>{r.report.metrics.total_km}<small> km</small></b><span>total driving</span></div>
      </div>
      <p className="run-meta">{r.seconds}s · ${r.cost_usd.toFixed(3)} · {r.paid_calls} model call{r.paid_calls === 1 ? '' : 's'}</p>
      {excluded > 0 && <p className="note">{excluded} order{excluded > 1 ? 's' : ''} left out — they cannot be reached without entering an avoided zone: {Object.keys(r.excluded).join(', ')}.</p>}
      {r.status === 'needs_relaxation' && (
        <div className="relax">
          <p className="note">The request is not feasible as stated. Smallest changes that work (each one verified):</p>
          {r.relaxations.map((o, i) => (
            <button key={o.kind} className={'chip ' + (props.relax === i ? 'on' : '')} onClick={() => props.onShowRelax(props.relax === i ? null : i)}>{o.description}</button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [samples, setSamples] = useState<Sample[]>([])
  const [name, setName] = useState('columbus')
  const [request, setRequest] = useState('')
  const [pinned, setPinned] = useState<number | null>(null)
  const [relax, setRelax] = useState<number | null>(null)
  const { state, start, reset } = useRun()
  const [mode, setMode] = useState<Mode>('depot')
  const [auto, setAuto] = useState(false)
  const [autoCount, setAutoCount] = useState(20)
  const [trucks, setTrucks] = useState(3)
  const [stale, setStale] = useState(false) // inputs changed after a plan was made: the plan on the map is out of date
  const [picking, setPicking] = useState(false)
  const [custom, setCustom] = useState<Custom>(emptyCustom)

  useEffect(() => {
    fetch('/api/samples').then((r) => r.json()).then((s: Sample[]) => {
      setSamples(s)
      const first = s.find((x) => x.name === 'columbus') ?? s[0]
      if (first) { setName(first.name); setRequest(first.examples[0] ?? '') }
    })
  }, [])

  useEffect(() => {
    if (state.result?.status === 'needs_relaxation') setRelax(0)
  }, [state.result])

  // When a run finishes its depot and orders become editable points (also the ones the agent placed itself).
  useEffect(() => {
    if (state.status !== 'done' || !state.depot) return
    setCustom((c) => ({ ...c, depot: c.depot ?? state.depot, orders: c.orders.length ? c.orders : state.orders }))
    setAuto(false)
  }, [state.status, state.depot, state.orders])

  const sample = samples.find((s) => s.name === name)
  const onSample = (n: string) => { setName(n); setRequest(samples.find((s) => s.name === n)?.examples[0] ?? ''); setCustom(emptyCustom); setMode('depot'); setAuto(false); setStale(false); reset() }
  const onArea = (s: Sample) => {
    setSamples((list) => (list.some((x) => x.name === s.name) ? list : [...list, s]))
    setName(s.name)
    setRequest(s.examples[0] ?? '')
    setCustom(emptyCustom)
    setMode('depot')
    setAuto(false)
    setStale(false)
    setPinned(null)
    setRelax(null)
    reset()
    setPicking(false)
  }
  const canPlan = !!request.trim() && ((!!custom.depot && custom.orders.length > 0) || (auto && custom.orders.length === 0))
  const onPlan = () => {
    setPinned(null)
    setRelax(null)
    setStale(false)
    setMode('browse')
    const body: { sample: string; request: string; trucks: number; custom?: object; auto_orders?: number } = { sample: name, request, trucks }
    if (custom.depot || custom.orders.length > 0 || custom.zoneClosed) {
      body.custom = { depot: custom.depot, orders: custom.orders, zone: custom.zoneClosed ? custom.zone : [] }
    }
    if (auto && custom.orders.length === 0) body.auto_orders = autoCount
    start(body)
  }
  // Changing the inputs after a plan keeps the old plan on screen (faded) and marks it out of date.
  const edit = (next: Custom) => {
    if (state.status === 'done') setStale(true) // after an error the banner stays until the next plan, so the map does not jump while you drag
    setCustom(next)
  }
  // One click: let the agent place 20 orders and plan with the first example sentence.
  const onQuickStart = () => {
    setAuto(true)
    setAutoCount(20)
    const req = request.trim() || sample?.examples[0] || 'by 12:00, avoid the industrial zone'
    setRequest(req)
    setPinned(null)
    setRelax(null)
    setStale(false)
    setMode('browse')
    start({ sample: name, request: req, trucks, auto_orders: 20 })
  }
  const onDrag = (kind: 'depot' | 'order', i: number, xy: XY) => {
    if (kind === 'depot') edit({ ...custom, depot: xy })
    else edit({ ...custom, orders: custom.orders.map((o, k) => (k === i ? xy : o)) })
  }
  const onEditPlan = () => { setStale(true); setMode('order') }
  const onMapClick = (xy: XY, unit: number) => {
    const near = (p: XY, r: number) => Math.hypot(p[0] - xy[0], p[1] - xy[1]) < r * unit
    if (mode === 'depot') {
      edit({ ...custom, depot: xy })
      if (custom.orders.length === 0) setMode('order') // the natural next step
    } else if (mode === 'order') {
      setAuto(false)
      const hit = custom.orders.findIndex((o) => near(o, 14))
      edit({ ...custom, orders: hit >= 0 ? custom.orders.filter((_, i) => i !== hit) : [...custom.orders, xy] })
    } else if (mode === 'zone') {
      if (custom.zoneClosed) return
      if (custom.zone.length >= 3 && near(custom.zone[0], 16)) edit({ ...custom, zoneClosed: true })
      else edit({ ...custom, zone: [...custom.zone, xy] })
    }
  }

  const sel = pinned !== null && pinned < state.iterations.length ? pinned : state.iterations.length - 1
  const iteration = state.iterations[sel]
  const relaxed = relax !== null ? state.result?.relaxations[relax] : undefined
  const plan: PlanGeo | undefined = relaxed?.plan ?? iteration?.plan
  const report: ReportGeo | undefined = relaxed?.report ?? iteration?.report
  const title = useMemo(() => (relaxed ? 'relaxed plan' : iteration ? `plan #${iteration.n}` : ''), [relaxed, iteration])

  if (!sample) return <div className="boot">Loading…</div>
  return (
    <div className="app">
      <header>
        <div className="brand"><svg width="26" height="26" viewBox="0 0 32 32"><circle cx="16" cy="16" r="13" fill="none" stroke="#2dd4bf" strokeWidth="3" /><circle cx="16" cy="16" r="4" fill="#2dd4bf" /></svg><b>OrbitRoute</b></div>
        <p>A satellite image and one sentence in. A verified delivery plan out — the agent checks its own work.</p>
        <span className="powered">SAM 3.1 · Muse Spark · PyVRP</span>
      </header>
      <main>
        <RequestPanel samples={samples} sample={sample} onSample={onSample} onPickArea={() => setPicking(true)} request={request} onRequest={setRequest} onPlan={onPlan} state={state} custom={custom} auto={auto} autoCount={autoCount} canPlan={canPlan} hasPlan={state.status === 'done' || state.status === 'error'} trucks={trucks} onTrucks={setTrucks} />
        <div className="center">
          {state.status === 'error' && (
            <div className="banner error" role="alert">
              <b>The agent could not run this.</b>
              <span>{state.error}</span>
              <span className="hint">Your points are still on the map{state.errorPoint ? ' — the one with the red ring is the problem. The found roads are switched on so you can see where to move it' : ''}. Drag it (or add another), then press Replan.</span>
            </div>
          )}
          {stale && state.status === 'done' && (
            <div className="banner warn" role="status">
              <b>You changed the inputs — the plan below is out of date.</b>
              <span>Drag the depot or any order, add or remove points, then press <b>Replan</b>.</span>
              <button className="primary inline" onClick={onPlan} disabled={!canPlan}>Replan</button>
            </div>
          )}
          <Stepper state={state} />
          <IterationTabs iterations={state.iterations} selected={relaxed ? -1 : sel} onSelect={(i) => { setPinned(i); setRelax(null) }} running={state.status === 'running'} />
          <MapView
            sample={sample} state={state} selected={sel} plan={plan} report={report}
            mode={mode} custom={custom} onMode={setMode} onClick={onMapClick}
            onCloseZone={() => edit({ ...custom, zoneClosed: true })}
            onClear={() => { edit(emptyCustom); setMode('depot'); setAuto(false) }}
            auto={auto} autoCount={autoCount} onAuto={setAuto} onAutoCount={setAutoCount}
            stale={stale} onDrag={onDrag} onEditPlan={onEditPlan}
            onQuickStart={onQuickStart} onPickArea={() => setPicking(true)}
          />
          <ResultBar state={state} relax={relax} onShowRelax={setRelax} />
        </div>
        <aside>
          <Checklist report={report} title={title} />
          <AgentLog log={state.log} running={state.status === 'running'} />
        </aside>
      </main>
      {picking && <AreaPicker onClose={() => setPicking(false)} onChosen={onArea} />}
      <footer>Imagery: USGS NAIP (public domain). Built solo for the Meta Global AI Developer Hackathon.</footer>
    </div>
  )
}
