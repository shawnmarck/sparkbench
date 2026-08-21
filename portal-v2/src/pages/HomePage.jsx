import { fmtCtx, fmtPct, fmtTokens, fmtTokS } from '../lib/fmt.js'

function usageBlock(usage) {
  const w = usage?.windows || {}
  return {
    h24: (Number(w['24h']?.prompt_tokens) || 0) + (Number(w['24h']?.completion_tokens) || 0),
    d30: (Number(w['30d']?.prompt_tokens) || 0) + (Number(w['30d']?.completion_tokens) || 0),
    all: (Number(w.all?.prompt_tokens) || 0) + (Number(w.all?.completion_tokens) || 0),
  }
}

export function HomePage({ live }) {
  const active = live.inference?.active
  const gpu = live.gpu
  const usage = usageBlock(live.activity?.usage)
  const load = gpu?.engine_load || {}
  const top = [...(live.recipes || [])]
    .filter((r) => r.switchable)
    .sort((a, b) => (Number(b.tok_s) || 0) - (Number(a.tok_s) || 0))
    .slice(0, 8)

  return (
    <div>
      <div className="page-head">
        <h1>Command center</h1>
        <p>Live box. Same APIs as the legacy portal. Switch stays on Inference.</p>
      </div>

      <div className="grid">
        <section className="card">
          <h2>Serving</h2>
          {active ? (
            <>
              <p className="hero-name">{active.name || active.id}</p>
              <p className="hero-meta">
                {active.engine} · {fmtCtx(active.context?.effective || active.context?.default)} ctx
                {active.tok_s ? ` · ${fmtTokS(active.tok_s)} tok/s` : ''}
                {load.max ? ` · ${load.running ?? 0}/${load.max} seqs` : ''}
              </p>
            </>
          ) : (
            <p className="hero-name muted">GPU idle</p>
          )}
        </section>
        <section className="card">
          <h2>Hardware</h2>
          <div className="meters">
            <div>
              <div className="meter-row"><span>GPU</span><b>{fmtPct(gpu?.gpu_util_pct)}%</b></div>
              <div className="bar gpu" style={{ '--pct': Math.min(1, (Number(gpu?.gpu_util_pct) || 0) / 100) }}><i /></div>
            </div>
            <div>
              <div className="meter-row"><span>Memory</span><b>{fmtPct(gpu?.memory_used_pct)}%</b></div>
              <div className="bar mem" style={{ '--pct': Math.min(1, (Number(gpu?.memory_used_pct) || 0) / 100) }}><i /></div>
            </div>
            <div className="meter-row">
              <span>Temps</span>
              <b>GPU {gpu?.gpu_temp_c ?? '—'}° · CPU {gpu?.cpu_temp_c ?? '—'}°</b>
            </div>
            <div className="meter-row">
              <span>Uptime</span>
              <b>{gpu?.uptime_human || '—'}</b>
            </div>
          </div>
        </section>
      </div>

      <section className="card" style={{ marginTop: '1rem' }}>
        <h2>Usage · :9000</h2>
        <p className="usage-line">
          24h <b>{fmtTokens(usage.h24)}</b>
          <span className="sep">·</span>
          30D <b>{fmtTokens(usage.d30)}</b>
          <span className="sep">·</span>
          All <b>{fmtTokens(usage.all)}</b>
        </p>
      </section>

      <section className="card" style={{ marginTop: '1rem' }}>
        <h2>Fastest switchable recipes</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Recipe</th>
                <th>Engine</th>
                <th>Tok/s</th>
                <th>Ctx</th>
              </tr>
            </thead>
            <tbody>
              {top.length ? top.map((r) => (
                <tr key={r.id} className={r.id === active?.id ? 'active' : ''}>
                  <td>{r.name || r.id}</td>
                  <td>{r.engine}</td>
                  <td>{fmtTokS(r.tok_s)}</td>
                  <td>{fmtCtx(r.context?.default)}</td>
                </tr>
              )) : (
                <tr><td className="muted" colSpan={4}>Loading recipes…</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
