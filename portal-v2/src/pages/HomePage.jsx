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

function seqCols(cap) {
  if (cap <= 8) return cap
  if (cap % 8 === 0) return 8
  if (cap % 6 === 0) return 6
  return 8
}

function SeqCubes({ running, waiting, max }) {
  const cap = Math.max(0, Number(max) || 0)
  if (!cap) return <p className="hero-meta tall">Concurrency —</p>
  const run = Math.min(cap, Math.max(0, Number(running) || 0))
  const wait = Math.min(Math.max(0, cap - run), Math.max(0, Number(waiting) || 0))
  if (cap > 48) {
    return (
      <div className="meters">
        <div className="meter-row">
          <span>Concurrency</span>
          <b>{run}/{cap}{wait ? ` · ${wait} wait` : ''}</b>
        </div>
        <div className="bar kv" style={{ '--pct': Math.min(1, run / cap) }}><i /></div>
      </div>
    )
  }
  return (
    <div className="seq-cubes" title={`${run} running, ${wait} waiting, ${cap} concurrency slots`}>
      <div className="meter-row">
        <span>Concurrency</span>
        <b>{run}/{cap}{wait ? ` · ${wait} wait` : ''}</b>
      </div>
      <div className="seq-grid" style={{ '--cols': seqCols(cap) }}>
        {Array.from({ length: cap }, (_, i) => {
          const kind = i < run ? 'run' : i < run + wait ? 'wait' : 'idle'
          return <i key={i} className={kind} />
        })}
      </div>
    </div>
  )
}

function lastSessionRate(recent) {
  return (recent || []).find((r) => Number(r.tok_s) > 0 && Number(r.completion_tokens) > 0) || null
}

function AggSpark({ values, p99 }) {
  const series = Array.isArray(values) ? values.map((v) => Number(v) || 0) : []
  if (series.length < 2) return null
  const w = 240
  const h = 42
  const peak = Math.max(p99 || 0, ...series, 1)
  const pts = series.map((v, i) => {
    const x = (i / (series.length - 1)) * w
    const y = h - 2 - (v / peak) * (h - 4)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const p99y = p99 != null ? (h - 2 - (Number(p99) / peak) * (h - 4)) : null
  return (
    <svg className="agg-spark" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} aria-hidden="true">
      {p99y != null ? (
        <line className="p99" x1="0" y1={p99y} x2={w} y2={p99y} />
      ) : null}
      <polyline points={pts} />
    </svg>
  )
}

export function HomePage({ live }) {
  const active = live.inference?.active
  const gpu = live.gpu
  const load = gpu?.engine_load || {}
  const preset = inferPreset(active, load)
  const spec = specLabel(active)
  const lastSess = lastSessionRate(live.activity?.recent)
  const avg1h = live.activity?.summary?.avg_tok_s
  const up = sinceLabel(active?.started_at)

  return (
    <div className="home">
      <div className="home-scroll">
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
                <dl className="serve-facts">
                  <div>
                    <dt>Engine</dt>
                    <dd>{stackLabel(active.engine)}</dd>
                  </div>
                  {active.port ? (
                    <div>
                      <dt>API port</dt>
                      <dd>{active.port}</dd>
                    </div>
                  ) : null}
                  {spec ? (
                    <div title="Speculative decoding helper on this recipe">
                      <dt>Speculative</dt>
                      <dd>{spec}</dd>
                    </div>
                  ) : null}
                  <div title="Configured context window for this recipe">
                    <dt>Context</dt>
                    <dd>{fmtCtx(active.context?.effective || active.context?.default)} tokens</dd>
                  </div>
                  {active.context?.kv_effective ? (
                    <div title="Key-value cache precision the recipe launched with">
                      <dt>KV type</dt>
                      <dd>{active.context.kv_effective}</dd>
                    </div>
                  ) : null}
                  {load.max != null ? (
                    <div title="Max concurrent request slots this recipe allows">
                      <dt>Slot cap</dt>
                      <dd>{load.max}</dd>
                    </div>
                  ) : null}
                  {preset ? (
                    <div>
                      <dt>Preset</dt>
                      <dd>{preset.label}</dd>
                    </div>
                  ) : null}
                  <div title={active.id}>
                    <dt>Served as</dt>
                    <dd>{active.served_name || active.id}</dd>
                  </div>
                  <div title="Catalog bench, not live. PBM 4k is decode speed at a 4k fill.">
                    <dt>Bench speed</dt>
                    <dd>{fmtTokS(active.tok_s)} tok/s</dd>
                  </div>
                  <div>
                    <dt>Bench method</dt>
                    <dd>{benchMethodLabel(active.tok_s_method)}</dd>
                  </div>
                </dl>
              </div>
              <div className="serve-block live">
                <h3>Live</h3>
                <p className="hero-meta tall">
                  {active.ready ? 'ready' : active.starting ? 'starting' : 'not ready'}
                  {up ? ` · up ${up}` : ''}
                </p>
                <SeqCubes running={load.running} waiting={load.waiting} max={load.max} />
                {load.kv_cache_pct != null ? (
                  <div className="meters kv-meter">
                    <div className="meter-row">
                      <span>KV cache</span>
                      <b>({fmtPct(load.kv_cache_pct)}%)</b>
                    </div>
                    <div className="bar kv" style={{ '--pct': Math.min(1, (Number(load.kv_cache_pct) || 0) / 100) }}><i /></div>
                  </div>
                ) : null}
                <div
                  className="rate-one agg"
                  title="Engine decode over a fixed 2s window. Adds up across concurrent slots."
                >
                  <b>{fmtTokS(load.gen_tok_s)}</b>
                  <span>
                    Agg tok/s · 2s
                    {Number(load.running) > 1 ? ` · ${load.running} slots` : ''}
                  </span>
                </div>
                <div
                  className="agg-spark-wrap"
                  title="Last hour of engine agg tok/s. Dashed line is p99 of 1-second samples."
                >
                  <AggSpark values={load.gen_spark} p99={load.gen_tok_s_p99} />
                  <p className="agg-spark-cap">
                    1h p99 {fmtTokS(load.gen_tok_s_p99)} tok/s
                    {load.gen_spark_n ? ` · ${load.gen_spark_n} samples` : ''}
                  </p>
                </div>
                <div className="rate-stack">
                  <div title="Last finished :9000 request: completion tokens / wall clock. Includes prefill. One session, not engine-wide.">
                    <b>{fmtTokS(lastSess?.tok_s)}</b>
                    <span>Last sess. tok/s{lastSess ? ` · ${sinceLabel(lastSess.at) || ''}` : ''}</span>
                  </div>
                  <div title="Mean of finished :9000 session rates over the last hour. Per request, not concurrent aggregate.">
                    <b>{fmtTokS(avg1h)}</b>
                    <span>1h avg sess. tok/s</span>
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
      </div>
      <ActivityDock recent={live.activity?.recent} recipes={live.recipes} />
    </div>
  )
}
