import { useEffect, useMemo, useRef, useState } from 'react'
import { fmtDur, fmtTokens, fmtTokS, shortName } from '../lib/fmt.js'

const LAST_N = 5
const STORE = 'spark-v2-activity-dock'

function rowId(row, i) {
  return row.id || `${row.at || ''}-${i}`
}

export function ActivityDock({ recent, recipes }) {
  const rows = (recent || []).slice(0, LAST_N).slice().reverse()
  const names = useMemo(() => {
    const m = new Map()
    for (const r of recipes || []) m.set(r.id, r.name || r.id)
    return m
  }, [recipes])
  const seen = useRef(new Set())
  const primed = useRef(false)
  const [fresh, setFresh] = useState(() => new Set())
  const [open, setOpen] = useState(() => {
    try {
      return window.localStorage.getItem(STORE) !== '0'
    } catch (_e) {
      return true
    }
  })

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

  function toggle() {
    setOpen((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(STORE, next ? '1' : '0')
      } catch (_e) { /* ignore */ }
      return next
    })
  }

  function modelLabel(row) {
    return shortName(names.get(row.profile), row.model || row.profile)
  }

  return (
    <aside className={`activity-dock${open ? '' : ' closed'}`} aria-label="Recent :9000 activity">
      <button type="button" className="activity-dock-head" onClick={toggle} aria-expanded={open}>
        <h2>Activity</h2>
        <span>last {LAST_N}{fresh.size && !open ? ` · ${fresh.size} new` : ''}</span>
        <em>{open ? 'Hide' : 'Show'}</em>
      </button>
      {open ? (
        <div className="activity-stream">
          <div className="activity-row head">
            <span>Time</span>
            <span>App</span>
            <span>Model</span>
            <span>In</span>
            <span>Out</span>
            <span>Tok/s</span>
            <span>Dur</span>
          </div>
          {rows.length ? rows.map((row, i) => {
            const id = rowId(row, i)
            const bad = row.status && String(row.status) !== '200'
            return (
              <div
                key={id}
                className={`activity-row${fresh.has(id) ? ' in' : ''}${bad ? ' bad' : ''}`}
                title={[row.profile, row.engine, row.stream ? 'stream' : 'sync', row.status].filter(Boolean).join(' · ')}
              >
                <span className="t">{row.at ? new Date(row.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'}</span>
                <span className="app">{row.app || row.client_ip || '—'}</span>
                <span className="model">{modelLabel(row)}</span>
                <span className="tok">{fmtTokens(row.prompt_tokens)}</span>
                <span className="tok">{fmtTokens(row.completion_tokens)}</span>
                <span className="rate">{fmtTokS(row.tok_s)}</span>
                <span className="dur">{fmtDur(row.duration_ms)}</span>
              </div>
            )
          }) : (
            <div className="activity-row muted">No recent :9000 sessions</div>
          )}
        </div>
      ) : null}
    </aside>
  )
}
