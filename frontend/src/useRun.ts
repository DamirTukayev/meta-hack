import { useCallback, useEffect, useReducer, useRef } from 'react'
import type { Problem, RunState, StreamEvent, Zone, XY } from './types'
import { accessHeaders } from './access'

export const initialState: RunState = { status: 'idle', stage: '', zones: [], warehouses: [], orders: [], orderTargets: [], iterations: [], log: [] }

type Action = { kind: 'start' } | { kind: 'reset' } | { kind: 'event'; e: StreamEvent; t0: number } | { kind: 'error'; message: string; point?: RunState['errorPoint'] } | { kind: 'done' }

let logId = 0

function reduce(s: RunState, a: Action): RunState {
  if (a.kind === 'reset') return initialState
  if (a.kind === 'start') return { ...initialState, status: 'running', stage: 'Starting' }
  if (a.kind === 'error') return { ...s, status: 'error', error: a.message, errorPoint: a.point, log: [...s.log, { id: ++logId, type: 'error', text: a.message, t: 0 }] }
  if (a.kind === 'done') return s.status === 'running' ? { ...s, status: 'done', stage: '' } : s
  const { e, t0 } = a
  const add = (text: string, type = e.type, source?: string) => [...s.log, { id: ++logId, type, text, t: e.t - t0, source }]
  const d = e.data
  switch (e.type) {
    case 'stage':
      return { ...s, stage: e.message, log: add(e.message) }
    case 'perception':
      return { ...s, mask: d.mask, graph: d.graph, sparseRoads: d.sparse ? (d.road_km_per_km2 as number) : undefined, log: add(e.message) }
    case 'scene':
      return { ...s, zones: d.zones as Zone[], warehouses: d.warehouses as XY[], log: add(e.message) }
    case 'problem':
      return { ...s, problem: { ...(d.problem as Problem), assumptions: d.assumptions }, log: add(e.message) }
    case 'scenario':
      return { ...s, depot: d.depot, orders: d.orders, orderTargets: d.order_targets ?? [], log: add(e.message) }
    case 'solve':
      return { ...s, stage: 'Verifying the plan independently', iterations: [...s.iterations, { n: d.iteration, plan: d.plan }], log: add(e.message) }
    case 'verify': {
      const its = s.iterations.slice()
      its[its.length - 1] = { ...its[its.length - 1], report: d.report }
      return { ...s, stage: d.ok ? 'Plan verified' : 'Deciding how to repair the plan', iterations: its, log: add(e.message, d.ok ? 'verify_ok' : 'verify_fail') }
    }
    case 'decision': {
      const its = s.iterations.slice()
      its[its.length - 1] = { ...its[its.length - 1], action: d.action, reason: d.reason, source: d.source }
      return { ...s, iterations: its, log: add(`${d.action.replaceAll('_', ' ')} — ${d.reason}`, 'decision', d.source) }
    }
    case 'repair':
      return { ...s, stage: 'Re-solving', log: add(e.message) }
    case 'result':
      return { ...s, result: d as RunState['result'], log: s.log }
    case 'matrix':
      return s
    default:
      return { ...s, log: add(e.message) }
  }
}

async function streamRun(body: object, onEvent: (name: string, data: any) => void, signal: AbortSignal) {
  const res = await fetch('/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json', ...accessHeaders() }, body: JSON.stringify(body), signal })
  if (!res.ok || !res.body) {
    let detail = `The server answered ${res.status}.`
    try {
      const j = await res.json()
      if (typeof j.detail === 'string') detail = j.detail
      else if (Array.isArray(j.detail)) detail = 'Some input was not accepted (too many points, or a value is out of range).'
    } catch { /* keep the generic message */ }
    throw new Error(detail)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let i: number
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, i)
      buf = buf.slice(i + 2)
      let name = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event: ')) name = line.slice(7)
        else if (line.startsWith('data: ')) data += line.slice(6)
      }
      if (data) onEvent(name, JSON.parse(data))
    }
  }
}

/** Streams one agent run. Events are revealed one by one so the viewer can follow the agent's reasoning. */
export function useRun(paceMs = 420) {
  const [state, dispatch] = useReducer(reduce, initialState)
  const queue = useRef<Action[]>([])
  const timer = useRef<number | null>(null)
  const abort = useRef<AbortController | null>(null)
  const finished = useRef(false)
  const t0 = useRef(0)

  const pump = useCallback(() => {
    if (timer.current !== null) return
    const step = () => {
      const next = queue.current.shift()
      if (next) {
        dispatch(next)
        timer.current = window.setTimeout(step, next.kind === 'event' && ['stage', 'matrix', 'result', 'scenario', 'scene'].includes(next.e.type) ? paceMs / 2 : paceMs)
      } else {
        timer.current = null
        if (finished.current) dispatch({ kind: 'done' })
      }
    }
    step()
  }, [paceMs])

  const stop = useCallback(() => {
    abort.current?.abort()
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    queue.current = []
  }, [])

  const reset = useCallback(() => {
    stop()
    dispatch({ kind: 'reset' })
  }, [stop])

  const start = useCallback(
    (body: { sample: string; request: string; decider?: 'model' | 'policy'; custom?: object; trucks?: number; capacity?: number; auto_orders?: number }) => {
      stop()
      finished.current = false
      t0.current = 0
      dispatch({ kind: 'start' })
      const ctl = new AbortController()
      abort.current = ctl
      streamRun(
        { decider: 'model', ...body },
        (name, data) => {
          if (name === 'event') {
            if (!t0.current) t0.current = data.t
            queue.current.push({ kind: 'event', e: data as StreamEvent, t0: t0.current })
          } else if (name === 'failure') {
            finished.current = true
            queue.current.push({ kind: 'error', message: data.message, point: data.point })
          } else if (name === 'done') {
            finished.current = true
          }
          pump()
        },
        ctl.signal,
      )
        .then(() => {
          finished.current = true
          pump()
        })
        .catch((err: unknown) => {
          if (ctl.signal.aborted) return
          finished.current = true
          queue.current.push({ kind: 'error', message: err instanceof Error ? err.message : 'Connection to the server was lost.' })
          pump()
        })
    },
    [pump, stop],
  )

  useEffect(() => {
    return () => stop()
  }, [stop])
  return { state, start, reset }
}
