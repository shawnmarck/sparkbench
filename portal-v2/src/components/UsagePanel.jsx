import { useMemo } from 'react'
import { ActivityCalendar } from './ActivityCalendar.jsx'
import { TokenOdometer } from './TokenOdometer.jsx'
import { fmtTokens } from '../lib/fmt.js'
import { countsOf } from '../lib/usage.js'

function TokenMix({ prompt, completion }) {
  const total = prompt + completion
  const pin = total ? prompt / total : 0
  return (
    <div className="tokmix">
      <div className="tokmix-bar">
        <i className="in" style={{ flex: pin || 0.0001 }} />
        <i className="out" style={{ flex: (1 - pin) || 0.0001 }} />
      </div>
      <div className="tokmix-n">
        <span>↑{fmtTokens(prompt)}</span>
        <span>↓{fmtTokens(completion)}</span>
      </div>
    </div>
  )
}

function requestLabel(requests, total) {
  if (requests <= 2 && total > 1e6) return { text: '—', title: 'Lifetime backfill; request count unknown' }
  return { text: fmtTokens(requests), title: '' }
}

export function UsagePanel({ live }) {
  const usage = live.activity?.usage
  const summary = live.activity?.summary || {}
  const all = countsOf(usage?.windows?.all)
  const h24 = countsOf(usage?.windows?.['24h'])
  const d30 = countsOf(usage?.windows?.['30d'])
  const profiles = usage?.profiles || []
  const names = useMemo(() => {
    const m = new Map()
    for (const r of live.recipes || []) m.set(r.id, r.name || r.id)
    return m
  }, [live.recipes])

  return (
    <section className="usage-hero">
      <div className="hero-row">
        <div className="hero-stat life">
          <TokenOdometer value={all.total} />
          <span>Lifetime tokens</span>
        </div>
        <div className="hero-stats">
          <div className="hero-stat">
            <b>{fmtTokens(h24.total)}</b>
            <span>24h</span>
          </div>
          <div className="hero-stat">
            <b>{fmtTokens(d30.total)}</b>
            <span>30D</span>
          </div>
          <div className="hero-stat">
            <b>{summary.sessions_1h ?? '—'}</b>
            <span>Sessions</span>
          </div>
          <div className="hero-stat">
            <b>{summary.active_clients ?? '—'}</b>
            <span>Clients</span>
          </div>
        </div>
      </div>
      <ActivityCalendar days={usage?.days} />
      <p className="mix-line">
        <b>{fmtTokens(all.prompt)}</b> in · <b>{fmtTokens(all.completion)}</b> out
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Profile</th>
              <th>Req</th>
              <th>Tokens</th>
              <th>24h</th>
              <th>All</th>
            </tr>
          </thead>
          <tbody>
            {profiles.length ? profiles.map((p) => {
              const a = countsOf(p.all)
              const c24 = countsOf(p['24h'])
              const req = requestLabel(a.requests, a.total)
              const label = names.get(p.id) || p.id
              return (
                <tr key={p.id}>
                  <td title={p.id}>
                    <div className="pid">{label}</div>
                  </td>
                  <td title={req.title}>{req.text}</td>
                  <td><TokenMix prompt={a.prompt} completion={a.completion} /></td>
                  <td>{c24.total ? fmtTokens(c24.total) : '—'}</td>
                  <td>{fmtTokens(a.total)}</td>
                </tr>
              )
            }) : (
              <tr><td className="muted" colSpan={5}>No usage yet</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
