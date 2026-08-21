import { ActivityDock } from '../components/ActivityDock.jsx'
import { UsagePanel } from '../components/UsagePanel.jsx'
import { benchMethodLabel, fmtCtx, fmtPct, fmtTokS, sinceLabel, stackLabel } from '../lib/fmt.js'

function inferPreset(active, load) {
  const ctx = active?.context || {}
  const presets = ctx.presets || []
  const effective = ctx.effective || ctx.default
  return presets.find((p) => {
    const ctxMatch = !p.ctx || p.ctx === effective
    const seqMatch = p.max_num_seqs == null || p.max_num_seqs === load.max
    return ctxMatch && seqMatch
  })
}

function specLabel(active) {
  const spec = active?.speculative
  if (!spec || typeof spec !== 'object') return null
  if (spec.method === 'mtp') return `MTP ×${spec.num_speculative_tokens ?? 1}`
  return spec.method
}

function liveRates(recent) {
  const rows = (recent || []).filter((r) => Number(r.tok_s) > 0 && Number(r.completion_tokens) > 0)
  const last = rows[0] || null
  const cutoff = Date.now() - 5 * 60 * 1000
  const windowed = rows.filter((r) => {
    const t = new Date(r.at || 0).getTime()
    return Number.isFinite(t) && t >= cutoff
  })
  const avg5 = windowed.length
    ? windowed.reduce((sum, r) => sum + Number(r.tok_s), 0) / windowed.length
    : null
  return { last, avg5, n5: windowed.length }
}

export function HomePage({ live }) {
  const active = live.inference?.active
  const gpu = live.gpu
  const load = gpu?.engine_load || {}
  const preset = inferPreset(active, load)
  const spec = specLabel(active)
  const liveTok = liveRates(live.activity?.recent)
  const avg1h = live.activity?.summary?.avg_tok_s
  const up = sinceLabel(active?.started_at)

  return (
    <div className="home">
      <div className="page-head">
        <h1>Home</h1>
        <p>What is serving now, plus :9000 usage. Switch from Inference or Ctrl/K.</p>
      </div>

      <div className="grid">
        <section className="card">
          <h2>Serving</h2>
          {active ? (
            <div className="serve-split">
              <div className="serve-block">
                <h3>Recipe</h3>
                <p className="hero-name">{active.name || active.id}</p>
                <p className="hero-meta">
                  {stackLabel(active.engine)}
                  {active.port ? ` :${active.port}` : ''}
                  {spec ? ` · ${spec}` : ''}
                </p>
                <p className="hero-meta">
                  {fmtCtx(active.context?.effective || active.context?.default)} ctx
                  {active.context?.kv_effective ? ` · KV ${active.context.kv_effective}` : ''}
                  {load.max != null ? ` · ${load.max} seq cap` : ''}
                </p>
                {preset ? <p className="hero-meta">{preset.label}</p> : null}
                <p className="pname" title={active.id}>{active.served_name || active.id}</p>
                <div
                  className="rate-one"
                  title="Catalog bench, not live. PBM 4k is decode at a 4k fill."
                >
                  <b>{fmtTokS(active.tok_s)}</b>
                  <span>Bench · {benchMethodLabel(active.tok_s_method)}</span>
                </div>
              </div>
              <div className="serve-block live">
                <h3>Live</h3>
                <p className="hero-meta tall">
                  {active.ready ? 'ready' : active.starting ? 'starting' : 'not ready'}
                  {up ? ` · up ${up}` : ''}
                </p>
                <p className="hero-meta tall">
                  {load.max != null ? `${load.running ?? 0}/${load.max} seqs` : 'seqs —'}
                  {load.waiting ? ` · ${load.waiting} waiting` : ''}
                </p>
                {load.kv_cache_pct != null ? (
                  <div className="meters kv-meter">
                    <div className="meter-row">
                      <span>KV cache</span>
                      <b>({fmtPct(load.kv_cache_pct)}%)</b>
                    </div>
                    <div className="bar kv" style={{ '--pct': Math.min(1, (Number(load.kv_cache_pct) || 0) / 100) }}><i /></div>
                  </div>
                ) : null}
                <div className="rate-stack">
                  <div title="Last :9000 request: completion tokens / wall clock. Includes prefill.">
                    <b>{fmtTokS(liveTok.last?.tok_s)}</b>
                    <span>Last request{liveTok.last ? ` · ${sinceLabel(liveTok.last.at) || ''}` : ''}</span>
                  </div>
                  <div title="Mean of :9000 request rates in the last 5 minutes.">
                    <b>{fmtTokS(liveTok.avg5)}</b>
                    <span>5m{liveTok.n5 ? ` · ${liveTok.n5} req` : ''}</span>
                  </div>
                  <div title="Mean of :9000 request rates over the last hour.">
                    <b>{fmtTokS(avg1h)}</b>
                    <span>1h avg :9000</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="hero-name muted">Idle</p>
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
      <ActivityDock recent={live.activity?.recent} />
    </div>
  )
}
