import { useEffect, useRef, useState } from 'react'
import { fmtTokens, fmtTokS } from '../lib/fmt.js'

const LAST_N = 6

function rowId(row, i) {
  return row.id || `${row.at || ''}-${i}`
}

export function ActivityDock({ recent }) {
  const rows = (recent || []).slice(0, LAST_N).slice().reverse()
  const seen = useRef(new Set())
  const primed = useRef(false)
  const [fresh, setFresh] = useState(() => new Set())

  useEffect(() => {
    const ids = rows.map((row, i) => rowId(row, i))
    if (!primed.current) {
      ids.forEach((id) => seen.current.add(id))
      primed.current = true
      return
    }
    const next = new Set(ids.filter((id) => !seen.current.has(id)))
    ids.forEach((id) => seen.current.add(id))
    if (!next.size) return
    setFresh(next)
    const t = window.setTimeout(() => setFresh(new Set()), 900)
    return () => window.clearTimeout(t)
  }, [rows.map((row, i) => rowId(row, i)).join('|')])

  return (
    <aside className="activity-dock" aria-label="Recent :9000 activity">
      <div className="activity-dock-head">
        <h2>Activity</h2>
        <span>last {LAST_N} · :9000</span>
      </div>
      <div className="activity-stream">
        {rows.length ? rows.map((row, i) => {
          const id = rowId(row, i)
          const prompt = Number(row.prompt_tokens) || 0
          const completion = Number(row.completion_tokens) || 0
          return (
            <div key={id} className={`activity-row${fresh.has(id) ? ' in' : ''}`}>
              <span className="t">{row.at ? new Date(row.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'}</span>
              <span className="app">{row.app || row.client_ip || '—'}</span>
              <span className="tok">↑{fmtTokens(prompt)} ↓{fmtTokens(completion)}</span>
              <span className="rate">{fmtTokS(row.tok_s)}</span>
            </div>
          )
        }) : (
          <div className="activity-row muted">No recent :9000 sessions</div>
        )}
      </div>
    </aside>
  )
}
