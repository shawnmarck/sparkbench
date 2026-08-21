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
      <div className="seq-strip">
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

function sparkPoint(i, v, n, peak, w, h) {
  const x = n <= 1 ? 0 : (i / (n - 1)) * w
  const y = h - 2 - (v / peak) * (h - 4)
  return `${x.toFixed(1)},${y.toFixed(1)}`
}

function AggSpark({ values, p99 }) {
  const series = Array.isArray(values) ? values : []
  const nums = series.map((v) => (v == null || v === '' ? null : Number(v)))
  const known = nums.filter((v) => v != null && Number.isFinite(v))
  if (known.length < 2) return null
  const w = 240
  const h = 42
  const peak = Math.max(Number(p99) || 0, ...known, 1)
  const segs = []
  let cur = []
  nums.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) {
      if (cur.length) segs.push(cur)
      cur = []
      return
    }
    cur.push(sparkPoint(i, v, nums.length, peak, w, h))
  })
  if (cur.length) segs.push(cur)
  const p99y = p99 != null && Number.isFinite(Number(p99))
    ? (h - 2 - (Number(p99) / peak) * (h - 4))
    : null
  return (
    <svg className="agg-spark" viewBox={`0 0 ${w} ${h}`} width="100%" height={h} aria-hidden="true">
      {p99y != null ? (
        <line className="p99" x1="0" y1={p99y} x2={w} y2={p99y} />
      ) : null}
      {segs.map((pts, i) => (
        pts.length === 1
          ? <circle key={i} className="dot" cx={pts[0].split(',')[0]} cy={pts[0].split(',')[1]} r="1.4" />
          : <polyline key={i} points={pts.join(' ')} />
      ))}
    </svg>
  )
}

export function HomePage({ live }) {
  const active = live.inference?.active
  const gpu = live.gpu
  const load = gpu?.engine_load || {}
  const preset = inferPreset(active, load)
  const lastSess = lastSessionRate(live.activity?.recent)
  const avg1h = live.activity?.summary?.avg_tok_s_weighted ?? live.activity?.summary?.avg_tok_s
  const sparkSpan = Number(load.gen_spark_span_s) || 0
  const p99Ready = sparkSpan >= 3300
  const up = sinceLabel(active?.started_at)

  return (
    <div className="home">
      <div className="home-scroll">
      <div className="home-stack">
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
                  {preset ? (
                    <div>
                      <dt>Preset</dt>
                      <dd>{preset.label}</dd>
                    </div>
                  ) : null}
                  <div className="catalog" title="Catalog bench, not live. PBM 4k is decode speed at a 4k fill.">
                    <dt>Catalog bench</dt>
                    <dd>
                      {fmtTokS(active.tok_s)}
                      <small> {benchMethodLabel(active.tok_s_method)}, not live</small>
                    </dd>
                  </div>
                </dl>
              </div>
              <div className="serve-block live">
                <h3>Live</h3>
                <p className="hero-meta tall">
                  {active.ready ? (up ? `up ${up}` : 'ready') : active.starting ? 'starting' : 'not ready'}
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
                <div className="rate-pair">
                  <div
                    className="rate-one agg"
                    title="Peak engine decode over the last 10 seconds. Adds up across concurrent slots."
                  >
                    <b>{fmtTokS(load.gen_tok_s)}</b>
                    <span>Agg peak · 10s</span>
                  </div>
                  <div className="rate-sess">
                    <div title="Last finished :9000 request: completion tokens / wall clock. Includes prefill. One session, not engine-wide.">
                      <b>{fmtTokS(lastSess?.tok_s)}</b>
                      <span>Last sess.{lastSess ? ` · ${sinceLabel(lastSess.at) || ''}` : ''}</span>
                    </div>
                    <div title="Token-weighted: sum of completion tokens / sum of wall clock over finished :9000 sessions in the last hour.">
                      <b>{fmtTokS(avg1h)}</b>
                      <span>1h sess.</span>
                    </div>
                  </div>
                </div>
                <div
                  className="agg-spark-wrap"
                  title="Last hour of engine agg tok/s. Gaps are missing history, floor is idle. Dashed line is p99 of busy seconds."
                >
                  <AggSpark values={load.gen_spark} p99={load.gen_tok_s_p99} />
                  {p99Ready ? (
                    <p className="agg-spark-cap">1h p99 {fmtTokS(load.gen_tok_s_p99)} tok/s</p>
                  ) : null}
                </div>
              </div>
            </div>
          ) : (
            <p className="hero-name muted">Idle</p>
          )}
        </section>
      </div>

      <UsagePanel live={live} />
      </div>
      <ActivityDock recent={live.activity?.recent} recipes={live.recipes} />
    </div>
  )
}
