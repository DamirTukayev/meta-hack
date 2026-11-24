import { t } from './i18n'
import type { QuantumInfo, QuantumMode } from './types'

export const QUANTUM_MODES: { value: QuantumMode; label: string }[] = [
  { value: 'off', label: 'Off' },
  { value: 'qaoa_p1', label: 'QAOA p=1' },
  { value: 'qaoa_p2', label: 'QAOA p=2' },
  { value: 'sa', label: 'Simulated annealing' },
]

const SOLVER_LABEL: Record<string, string> = { qaoa_p1: 'QAOA p=1', qaoa_p2: 'QAOA p=2', sa: 'Simulated annealing', exact: 'Exhaustive search' }

function cost(v: number, unit: 's' | 'm') {
  return unit === 's' ? `${(v / 60).toFixed(1)} ${t('min')}` : `${(v / 1000).toFixed(2)} ${t('km')}`
}

// What the optional polishing did to the verified plan. The note that it is a CPU simulation is always shown, as the server wrote it.
export default function QuantumCard({ q, running }: { q: QuantumInfo; running: boolean }) {
  const change = q.cost_before ? ((q.cost_after - q.cost_before) / q.cost_before) * 100 : 0
  return (
    <section className="panel quantum">
      <h2>{t('Quantum polishing')} <small>{t(SOLVER_LABEL[q.solver] ?? q.solver)}</small></h2>
      <p className="q-note" role="note">{q.note}</p>
      <dl className="q-grid">
        <dt>{t('Qubits per segment')}</dt><dd>{q.qubits.join(' / ') || '—'}</dd>
        <dt>{t('Segments')}</dt><dd>{q.segments}</dd>
        {q.p_feas !== null && <><dt title={t('Mean share of the samples that encode a valid order of the stops')}>P<sub>feas</sub></dt><dd>{(q.p_feas * 100).toFixed(1)}%</dd></>}
        <dt>{t('Optimum found')}</dt><dd>{t('{a} of {b}', { a: q.optimum_found, b: q.segments })}</dd>
        <dt>{t('Swaps accepted')}</dt><dd>{q.accepted}</dd>
        <dt>{t('Cost before → after')}</dt><dd>{cost(q.cost_before, q.unit)} → {cost(q.cost_after, q.unit)} <small>({change.toFixed(2)}%)</small></dd>
        <dt>{t('Reverted by the verifier')}</dt><dd className={q.reverted ? 'fail' : ''}>{running && !q.reverted ? '…' : q.reverted ? `${t('yes')}: ${q.failed_checks.join(', ')}` : t('no')}</dd>
      </dl>
      {q.accepted > 0 && <p className="muted small">{t('Segments changed by the polishing are outlined with a dashed line on the map.')}</p>}
      {q.params_transfer && <p className="muted small">{t('QAOA angles are optimised once per segment size and reused for the other segments of that size.')}</p>}
    </section>
  )
}
