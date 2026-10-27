import type { RunState } from './types'

type StepState = 'done' | 'active' | 'todo'

const STEPS = [
  { key: 'perceive', label: 'Read image', who: 'SAM 3.1' },
  { key: 'understand', label: 'Understand', who: 'Muse Spark' },
  { key: 'plan', label: 'Plan', who: 'Solver' },
  { key: 'verify', label: 'Verify', who: 'Independent' },
  { key: 'repair', label: 'Repair', who: 'If needed' },
] as const

/** Where the agent is, derived from the events seen so far. */
export function stepStates(s: RunState): Record<string, StepState> {
  const running = s.status === 'running'
  const perceived = !!s.mask
  const understood = !!s.problem
  const planned = s.iterations.length > 0
  const verified = s.iterations.some((i) => i.report)
  const repaired = s.iterations.some((i) => i.action)
  const finished = s.status === 'done' || !!s.result
  const pick = (done: boolean, active: boolean): StepState => (done ? 'done' : active && running ? 'active' : 'todo')
  return {
    perceive: pick(perceived, true),
    understand: pick(understood, perceived),
    plan: pick(planned, understood),
    verify: pick(verified && (finished || s.iterations.every((i) => i.report)), planned),
    repair: finished ? (repaired ? 'done' : 'todo') : repaired ? 'active' : 'todo',
  }
}

export default function Stepper({ state }: { state: RunState }) {
  const st = stepStates(state)
  return (
    <ol className="stepper" aria-label="Agent progress">
      {STEPS.map((step, i) => (
        <li key={step.key} className={st[step.key]}>
          <span className="bullet">{st[step.key] === 'done' ? '✓' : st[step.key] === 'active' ? <i className="spinner" /> : i + 1}</span>
          <span className="label"><b>{step.label}</b><small>{step.who}</small></span>
        </li>
      ))}
    </ol>
  )
}
