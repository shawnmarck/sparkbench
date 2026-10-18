import { useEffect, useState } from 'react'
import { fmtEtaS } from '../lib/fmt.js'

function elapsedFrom(startedAt, now) {
  if (!startedAt) return null
  const ms = now - new Date(startedAt).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  return Math.floor(ms / 1000)
}

export function LoadMeter({ loading }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!loading) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [loading?.started_at, loading?.profile])

  if (!loading) return null
  const expect = loading.expect || {}
  const typical = Number(expect.typical_s) || 0
  const elapsed = elapsedFrom(loading.started_at, now) ?? (Number(loading.elapsed_s) || 0)
  const overtime = typical > 0 && elapsed >= typical
  const eta = typical > 0 ? Math.max(0, typical - elapsed) : null
  const pct = typical > 0 ? (overtime ? 0.95 : Math.min(0.95, elapsed / typical)) : 0.08
  const label = overtime
    ? `still waiting · usually ${fmtEtaS(typical)}`
    : eta != null
      ? `~${fmtEtaS(eta)} left`
      : (expect.hint || 'loading')
  return (
    <div
      className={`meters load-meter${overtime ? ' over' : ''}`}
      title={expect.hint || loading.detail || 'Engine loading'}
    >
      <div className="meter-row">
        <span>{loading.phase_label || 'Loading'}</span>
        <b>{fmtEtaS(elapsed)}{typical ? ` / ${fmtEtaS(typical)}` : ''} · {label}</b>
      </div>
      <div className="bar load" style={{ '--pct': pct }}><i /></div>
    </div>
  )
}
