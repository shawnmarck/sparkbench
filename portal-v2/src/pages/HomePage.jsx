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
    <div>
      <div className="page-head">
        <h1>Home</h1>
        <p>What is serving now, plus :9000 usage. Switch from Inference or Ctrl/K.</p>
      </div>

      <div className="grid">
        <section className="card">
          <h2>Serving</h2>
          {active ? (
            <>
              <p className="hero-name">{active.name || active.id}</p>
              <p className="hero-meta">
                {stackLabel(active.engine)}
                {active.port ? ` :${active.port}` : ''}
                {spec ? ` · ${spec}` : ''}
                {active.ready ? ' · ready' : active.starting ? ' · starting' : ' · not ready'}
                {up ? ` · up ${up}` : ''}
              </p>
              <p className="hero-meta tall">
                {fmtCtx(active.context?.effective || active.context?.default)} ctx
                {active.context?.kv_effective ? ` · KV ${active.context.kv_effective}` : ''}
                {preset ? ` · ${preset.label}` : ''}
              </p>
              <p className="hero-meta">
                {load.max != null ? `${load.running ?? 0}/${load.max} seqs` : 'seqs —'}
                {load.waiting ? ` · ${load.waiting} waiting` : ''}
                {load.kv_cache_pct != null ? ` · KV cache ${fmtPct(load.kv_cache_pct)}%` : ''}
              </p>
              <p className="pname" title={active.id}>{active.served_name || active.id}</p>

              <div className="rate-grid">
                <div title="Catalog bench, not live. PBM 4k is decode at a 4k fill.">
                  <b>{fmtTokS(active.tok_s)}</b>
                  <span>Bench · {benchMethodLabel(active.tok_s_method)}</span>
                </div>
                <div title="Last :9000 request: completion tokens / wall clock. Includes prefill.">
                  <b>{fmtTokS(liveTok.last?.tok_s)}</b>
                  <span>Last request{liveTok.last ? ` · ${sinceLabel(liveTok.last.at) || ''}` : ''}</span>
                </div>
                <div title="Mean of :9000 request rates in the last 5 minutes.">
                  <b>{fmtTokS(liveTok.avg5)}</b>
                  <span>Live 5m{liveTok.n5 ? ` · ${liveTok.n5} req` : ''}</span>
                </div>
                <div title="Mean of :9000 request rates over the last hour.">
                  <b>{fmtTokS(avg1h)}</b>
                  <span>1h avg :9000</span>
                </div>
              </div>
            </>
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
    </div>
  )
}
