import { useCallback, useEffect, useReducer, useRef } from 'react'
import type { Problem, RunState, StreamEvent, Zone, XY } from './types'

export const initialState: RunState = { status: 'idle', stage: '', zones: [], warehouses: [], orders: [], iterations: [], log: [] }

type Action = { kind: 'start' } | { kind: 'event'; e: StreamEvent; t0: number } | { kind: 'error'; message: string } | { kind: 'done' }

let logId = 0

function reduce(s: RunState, a: Action): RunState {
  if (a.kind === 'start') return { ...initialState, status: 'running', stage: 'Starting' }
  if (a.kind === 'error') return { ...s, status: 'error', error: a.message }
  if (a.kind === 'done') return s.status === 'running' ? { ...s, status: 'done', stage: '' } : s
  const { e, t0 } = a
  const add = (text: string, type = e.type, source?: string) => [...s.log, { id: ++logId, type, text, t: e.t - t0, source }]
  const d = e.data
  switch (e.type) {
    case 'stage':
      return { ...s, stage: e.message, log: add(e.message) }
    case 'perception':
      return { ...s, mask: d.mask, graph: d.graph, log: add(e.message) }
    case 'scene':
      return { ...s, zones: d.zones as Zone[], warehouses: d.warehouses as XY[], log: add(e.message) }
    case 'problem':
      return { ...s, problem: { ...(d.problem as Problem), assumptions: d.assumptions }, log: add(e.message) }
    case 'scenario':
      return { ...s, depot: d.depot, orders: d.orders, log: add(e.message) }
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

/** Streams one agent run. Events are revealed one by one so the viewer can follow the agent's reasoning. */
export function useRun(paceMs = 420) {
  const [state, dispatch] = useReducer(reduce, initialState)
  const queue = useRef<Action[]>([])
  const timer = useRef<number | null>(null)
  const source = useRef<EventSource | null>(null)
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
    source.current?.close()
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = null
    queue.current = []
  }, [])

  const start = useCallback(
    (sample: string, request: string, decider: 'model' | 'policy' = 'model') => {
      stop()
      finished.current = false
      t0.current = 0
      dispatch({ kind: 'start' })
      const url = `/api/run?${new URLSearchParams({ sample, request, decider })}`
      const es = new EventSource(url)
      source.current = es
      es.addEventListener('event', (m) => {
        const e = JSON.parse((m as MessageEvent).data) as StreamEvent
        if (!t0.current) t0.current = e.t
        queue.current.push({ kind: 'event', e, t0: t0.current })
        pump()
      })
      es.addEventListener('failure', (m) => {
        finished.current = true
        queue.current.push({ kind: 'error', message: JSON.parse((m as MessageEvent).data).message })
        pump()
      })
      es.addEventListener('done', () => {
        finished.current = true
        es.close()
        pump()
      })
      es.onerror = () => {
        if (!finished.current) {
          es.close()
          queue.current.push({ kind: 'error', message: 'Connection to the server was lost.' })
          pump()
        }
      }
    },
    [pump, stop],
  )

  useEffect(() => {
    return () => stop()
  }, [stop])
  return { state, start }
}
