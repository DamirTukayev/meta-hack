import { useEffect, useMemo, useRef, useState } from 'react'
import AreaPicker from './AreaPicker'
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
}) {
  const { sample, state, custom } = props
  const running = state.status === 'running'
  return (
    <section className="panel request">
      <h2>Request</h2>
      <label>Satellite image</label>
      <select value={sample?.name} onChange={(e) => props.onSample(e.target.value)} disabled={running}>
        {props.samples.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
      </select>
      <button className="link" onClick={props.onPickArea} disabled={running}>＋ Choose another area on the map</button>
      <label>What should the trucks do?</label>
      <textarea value={props.request} onChange={(e) => props.onRequest(e.target.value)} rows={4} maxLength={400} disabled={running} placeholder="40 orders, 3 trucks, by 18:00, avoid the industrial zone" />
      <div className="examples">
        {sample?.examples.map((ex) => <button key={ex} className="example" onClick={() => props.onRequest(ex)} disabled={running}>{ex}</button>)}
      </div>
      {(custom.depot || custom.orders.length > 0 || custom.zoneClosed) && (
        <p className="own">
          Using your own {[custom.depot && 'depot', custom.orders.length > 0 && `${custom.orders.length} order${custom.orders.length > 1 ? 's' : ''}`, custom.zoneClosed && 'avoid-zone'].filter(Boolean).join(', ')}.
          {custom.orders.length > 0 && ' The order count in the text is ignored.'}
        </p>
      )}
      <button className="primary" onClick={props.onPlan} disabled={running || !props.request.trim()}>{running ? 'Agent working…' : 'Plan route'}</button>
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
      <div className="stats">
        <span><b>{r.plan.served}/{total}</b> orders</span>
        <span><b>{trucks}</b> truck{trucks === 1 ? '' : 's'}</span>
        <span>back by <b>{r.report.metrics.last_return}</b></span>
        <span><b>{r.report.metrics.total_km}</b> km</span>
        <span>{r.seconds}s · ${r.cost_usd.toFixed(3)} · {r.paid_calls} model calls</span>
      </div>
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
  const [mode, setMode] = useState<Mode>('browse')
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

  const sample = samples.find((s) => s.name === name)
  const onSample = (n: string) => { setName(n); setRequest(samples.find((s) => s.name === n)?.examples[0] ?? ''); setCustom(emptyCustom); setMode('browse'); reset() }
  const onArea = (s: Sample) => {
    setSamples((list) => (list.some((x) => x.name === s.name) ? list : [...list, s]))
    setName(s.name)
    setRequest(s.examples[0] ?? '')
    setCustom(emptyCustom)
    setMode('browse')
    setPinned(null)
    setRelax(null)
    reset()
    setPicking(false)
  }
  const onPlan = () => {
    setPinned(null)
    setRelax(null)
    setMode('browse')
    const body: { sample: string; request: string; custom?: object } = { sample: name, request }
    if (custom.depot || custom.orders.length > 0 || custom.zoneClosed) {
      body.custom = { depot: custom.depot, orders: custom.orders, zone: custom.zoneClosed ? custom.zone : [] }
    }
    start(body)
  }
  // Editing starts from a clean map: the previous run no longer matches the inputs.
  const edit = (next: Custom) => {
    if (state.status !== 'idle') { reset(); setPinned(null); setRelax(null) } // a new input starts from a clean map
    setCustom(next)
  }
  const onMapClick = (xy: XY, unit: number) => {
    const near = (p: XY, r: number) => Math.hypot(p[0] - xy[0], p[1] - xy[1]) < r * unit
    if (mode === 'depot') edit({ ...custom, depot: xy })
    else if (mode === 'order') {
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
        <RequestPanel samples={samples} sample={sample} onSample={onSample} onPickArea={() => setPicking(true)} request={request} onRequest={setRequest} onPlan={onPlan} state={state} custom={custom} />
        <div className="center">
          {state.status === 'error' && (
            <div className="banner error" role="alert">
              <b>The agent could not run this.</b>
              <span>{state.error}</span>
              <span className="hint">Your points are still on the map. Turn on <b>Graph</b> to see which roads were found, then adjust and press Plan route again.</span>
            </div>
          )}
          <IterationTabs iterations={state.iterations} selected={relaxed ? -1 : sel} onSelect={(i) => { setPinned(i); setRelax(null) }} running={state.status === 'running'} />
          <MapView
            sample={sample} state={state} selected={sel} plan={plan} report={report}
            mode={mode} custom={custom} onMode={setMode} onClick={onMapClick}
            onCloseZone={() => edit({ ...custom, zoneClosed: true })}
            onClear={() => { edit(emptyCustom); setMode('browse') }}
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
