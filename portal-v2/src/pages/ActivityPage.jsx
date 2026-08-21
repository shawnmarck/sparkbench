import { fmtTokens, fmtTokS, sessionModelLabel } from '../lib/fmt.js'

function when(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch (_e) {
    return String(ts)
  }
}

export function ActivityPage({ live }) {
  const activity = live.activity || {}
  const summary = activity.summary || {}
  const recent = activity.recent || activity.events || []
  const apps = summary.apps || {}
  const appRows = Object.entries(apps)
  const names = new Map((live.recipes || []).map((r) => [r.id, r.name || r.id]))

  return (
    <div>
      <div className="page-head">
        <h1>Activity</h1>
        <p>Gateway :900x traffic only. {summary.active_clients ?? 0} clients now · {summary.sessions_1h ?? 0} sessions / 1h.</p>
      </div>

      <div className="stat-strip">
        <div><b>{summary.sessions_1h ?? '—'}</b><span>Sessions 1h</span></div>
        <div><b>{summary.sessions_24h ?? '—'}</b><span>Sessions 24h</span></div>
        <div><b>{summary.active_clients ?? '—'}</b><span>Clients</span></div>
        <div><b>{fmtTokS(summary.avg_tok_s)}</b><span>Avg tok/s</span></div>
        <div><b>{appRows.length || '—'}</b><span>Apps</span></div>
      </div>

      {appRows.length ? (
        <section className="card" style={{ marginBottom: '1rem' }}>
          <h2>Apps</h2>
          <div className="stack-list">
            {appRows.map(([name, n]) => (
              <div key={name} className="stack-row">
                <div className="pid">{name}</div>
                <div className="pname">{n}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="card">
        <h2>Recent</h2>
        <div className="table-wrap" style={{ maxHeight: '62vh' }}>
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>App</th>
                <th>Profile</th>
                <th>In</th>
                <th>Out</th>
                <th>Tok/s</th>
              </tr>
            </thead>
            <tbody>
              {recent.slice(0, 80).map((row, i) => (
                <tr key={row.id || row.ts || i}>
                  <td>{when(row.at || row.ts)}</td>
                  <td>{row.app || row.client_ip || '—'}</td>
                  <td title={row.requested_model ? `${row.profile || ''} · asked ${row.requested_model}` : row.profile}>
                    {sessionModelLabel(row, names)}
                  </td>
                  <td>{fmtTokens(row.prompt_tokens || row.prompt || 0)}</td>
                  <td>{fmtTokens(row.completion_tokens || row.completion || 0)}</td>
                  <td>{fmtTokS(row.tok_s || row.avg_tok_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
