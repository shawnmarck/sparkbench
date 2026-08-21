import { useMemo, useState } from 'react'
import { fmtTokens } from '../lib/fmt.js'
import { countsOf, lastNDates, shortProfileId, weekdayOf } from '../lib/usage.js'

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

function Heatmap({ days }) {
  const byDate = useMemo(() => {
    const m = new Map()
    for (const row of days || []) m.set(row.date, countsOf(row))
    return m
  }, [days])
  const dates = lastNDates(35)
  const max = Math.max(1, ...dates.map((d) => byDate.get(d)?.total || 0))
  const pad = weekdayOf(dates[0])
  const cells = [...Array(pad).fill(null), ...dates]
  const [hover, setHover] = useState(null)
  const tip = hover && {
    date: hover,
    ...(byDate.get(hover) || { total: 0, requests: 0 }),
  }

  return (
    <div className="heat">
      <div className="heat-head">
        <span>Past 31 days</span>
        <span className="heat-legend">Less <i /><i /><i /><i /> More</span>
      </div>
      <div className="heat-grid">
        {cells.map((date, i) => {
          if (!date) return <span key={`p${i}`} className="heat-cell empty" />
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
          ? `${tip.date} · ${fmtTokens(tip.total)} tokens · ${tip.requests || 0} requests`
          : 'Gateway :9000 only. Direct engine hits are not counted.'}
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
        <div className="hero-label">Lifetime tokens · :9000</div>
      </div>
      <div className="stat-strip">
        <div><b>{fmtTokens(all.requests)}</b><span>Requests</span></div>
        <div><b>{summary.sessions_24h ?? '—'}</b><span>Sessions / 24h</span></div>
        <div><b>{summary.active_clients ?? '—'}</b><span>Clients now</span></div>
        <div><b>{fmtTokens(h24.total)}</b><span>24h tokens</span></div>
        <div><b>{fmtTokens(d30.total)}</b><span>30D tokens</span></div>
      </div>
      <Heatmap days={usage?.days} />
      <div className="usage-tabs">
        <button type="button" className={tab === 'models' ? 'on' : ''} onClick={() => setTab('models')}>Models</button>
        <button type="button" className={tab === 'activity' ? 'on' : ''} onClick={() => setTab('activity')}>Activity</button>
      </div>
      {tab === 'models' ? (
        <>
          <p className="mix-line">
            Token mix <b>{fmtTokens(all.prompt)}</b> in · <b>{fmtTokens(all.completion)}</b> out
            <span className="sep">·</span>
            {fmtTokens(all.total)} total
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Profile</th>
                  <th>Requests</th>
                  <th>Tokens</th>
                  <th>24h</th>
                  <th>All</th>
                </tr>
              </thead>
              <tbody>
                {profiles.length ? profiles.map((p) => {
                  const a = countsOf(p.all)
                  const c24 = countsOf(p['24h'])
                  return (
                    <tr key={p.id}>
                      <td title={p.id}>
                        <div className="pid">{shortProfileId(p.id)}</div>
                        <div className="pname">{names.get(p.id) || ''}</div>
                      </td>
                      <td>{fmtTokens(a.requests)}</td>
                      <td><TokenMix prompt={a.prompt} completion={a.completion} /></td>
                      <td>{fmtTokens(c24.total)}</td>
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
