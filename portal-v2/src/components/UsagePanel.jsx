import { useMemo, useState } from 'react'
import { fmtTokens } from '../lib/fmt.js'
import { countsOf, lastNDates } from '../lib/usage.js'

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

function Heatmap({ days }) {
  const byDate = useMemo(() => {
    const m = new Map()
    for (const row of days || []) m.set(row.date, countsOf(row))
    return m
  }, [days])
  const dates = lastNDates(31)
  const max = Math.max(1, ...dates.map((d) => byDate.get(d)?.total || 0))
  const [hover, setHover] = useState(null)
  const tip = hover && {
    date: hover,
    ...(byDate.get(hover) || { total: 0, requests: 0 }),
  }

  return (
    <div className="heat">
      <div className="heat-head">
        <span>Past 31 days</span>
        <span className="heat-range">{dates[0]?.slice(5)} → {dates[dates.length - 1]?.slice(5)}</span>
      </div>
      <div className="heat-row">
        {dates.map((date) => {
          const tot = byDate.get(date)?.total || 0
          const level = tot === 0 ? 0 : Math.min(4, 1 + Math.floor((tot / max) * 3))
          return (
            <button
              key={date}
              type="button"
              className={`heat-cell l${level}`}
              title={`${date} · ${fmtTokens(tot)} tokens`}
              onMouseEnter={() => setHover(date)}
              onMouseLeave={() => setHover(null)}
            />
          )
        })}
      </div>
      <p className="heat-tip">
        {tip
          ? `${tip.date} · ${fmtTokens(tip.total)} tokens · ${tip.requests || 0} req`
          : 'Hover a day. Empty cells are days with no :9000 traffic in the store.'}
      </p>
    </div>
  )
}

export function UsagePanel({ live }) {
  const [tab, setTab] = useState('models')
  const usage = live.activity?.usage
  const summary = live.activity?.summary || {}
  const all = countsOf(usage?.windows?.all)
  const h24 = countsOf(usage?.windows?.['24h'])
  const d30 = countsOf(usage?.windows?.['30d'])
  const profiles = usage?.profiles || []
  const recent = live.activity?.recent || []
  const names = useMemo(() => {
    const m = new Map()
    for (const r of live.recipes || []) m.set(r.id, r.name || r.id)
    return m
  }, [live.recipes])

  return (
    <section className="usage-hero">
      <div className="hero-total">
        <div className="hero-num">{fmtTokens(all.total)}</div>
        <div className="hero-label">Lifetime tokens</div>
      </div>
      <div className="stat-strip">
        <div><b>{fmtTokens(h24.total)}</b><span>24h</span></div>
        <div><b>{fmtTokens(d30.total)}</b><span>30D</span></div>
        <div><b>{summary.sessions_1h ?? '—'}</b><span>Sessions / 1h</span></div>
        <div><b>{summary.active_clients ?? '—'}</b><span>Clients</span></div>
        <div><b>{summary.avg_tok_s ? Number(summary.avg_tok_s).toFixed(1) : '—'}</b><span>Tok/s / 1h</span></div>
      </div>
      <Heatmap days={usage?.days} />
      <div className="usage-tabs">
        <button type="button" className={tab === 'models' ? 'on' : ''} onClick={() => setTab('models')}>Models</button>
        <button type="button" className={tab === 'activity' ? 'on' : ''} onClick={() => setTab('activity')}>Activity</button>
      </div>
      {tab === 'models' ? (
        <>
          <p className="mix-line">
            <b>{fmtTokens(all.prompt)}</b> in · <b>{fmtTokens(all.completion)}</b> out
            <span className="sep">·</span>
            :9000 only
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
        </>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>App</th>
                <th>Tokens</th>
                <th>Tok/s</th>
              </tr>
            </thead>
            <tbody>
              {recent.length ? recent.map((r, i) => (
                <tr key={r.id || r.at || i}>
                  <td>{r.at ? new Date(r.at).toLocaleTimeString() : '—'}</td>
                  <td>{r.app || r.client || '—'}</td>
                  <td>{fmtTokens((r.prompt_tokens || 0) + (r.completion_tokens || 0))}</td>
                  <td>{r.tok_s != null ? Number(r.tok_s).toFixed(1) : '—'}</td>
                </tr>
              )) : (
                <tr><td className="muted" colSpan={4}>No recent :9000 sessions</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
