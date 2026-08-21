import { UsagePanel } from '../components/UsagePanel.jsx'
import { fmtCtx, fmtPct, fmtTokS } from '../lib/fmt.js'

export function HomePage({ live }) {
  const active = live.inference?.active
  const gpu = live.gpu
  const load = gpu?.engine_load || {}

  return (
    <div>
      <div className="page-head">
        <h1>Command center</h1>
        <p>Live box. Usage is gateway :9000 only.</p>
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
          </div>
        </section>
      </div>

      <UsagePanel live={live} />
    </div>
  )
}
