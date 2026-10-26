import { useEffect, useMemo, useRef, useState } from 'react'
import MapView, { IterationTabs } from './MapView'
import type { LogEntry, PlanGeo, ReportGeo, Result, RunState, Sample } from './types'
import { useRun } from './useRun'

const ICONS: Record<string, string> = { stage: '◌', perception: '▦', scene: '◫', problem: '☰', scenario: '⌖', start: '▶', solve: '◆', verify_ok: '✓', verify_fail: '✗', decision: '?', repair: '↻', relaxation: '≈', final: '■' }

function fmtT(s: number) {
  return `${Math.max(s, 0).toFixed(1)}s`
}

function RequestPanel(props: {
  samples: Sample[]
  sample?: Sample
  onSample: (n: string) => void
  request: string
  onRequest: (r: string) => void
  onPlan: () => void
  state: RunState
}) {
  const { sample, state } = props
  const running = state.status === 'running'
  return (
    <section className="panel request">
      <h2>Request</h2>
      <label>Satellite image</label>
      <select value={sample?.name} onChange={(e) => props.onSample(e.target.value)} disabled={running}>
        {props.samples.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
      </select>
      <label>What should the trucks do?</label>
      <textarea value={props.request} onChange={(e) => props.onRequest(e.target.value)} rows={4} maxLength={400} disabled={running} placeholder="40 orders, 3 trucks, by 18:00, avoid the industrial zone" />
      <div className="examples">
        {sample?.examples.map((ex) => <button key={ex} className="example" onClick={() => props.onRequest(ex)} disabled={running}>{ex}</button>)}
      </div>
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
              <h4>Assumed, because the request did not say</h4>
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
  const { state, start } = useRun()

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
  const onSample = (n: string) => { setName(n); setRequest(samples.find((s) => s.name === n)?.examples[0] ?? '') }
  const onPlan = () => { setPinned(null); setRelax(null); start(name, request) }

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
        <RequestPanel samples={samples} sample={sample} onSample={onSample} request={request} onRequest={setRequest} onPlan={onPlan} state={state} />
        <div className="center">
          <IterationTabs iterations={state.iterations} selected={relaxed ? -1 : sel} onSelect={(i) => { setPinned(i); setRelax(null) }} running={state.status === 'running'} />
          <MapView sample={sample} state={state} selected={sel} plan={plan} report={report} />
          <ResultBar state={state} relax={relax} onShowRelax={setRelax} />
        </div>
        <aside>
          <Checklist report={report} title={title} />
          <AgentLog log={state.log} running={state.status === 'running'} />
        </aside>
      </main>
      <footer>Imagery: USGS NAIP (public domain). Built solo for the Meta Global AI Developer Hackathon.</footer>
    </div>
  )
}
