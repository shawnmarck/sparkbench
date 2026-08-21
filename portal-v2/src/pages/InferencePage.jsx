import { useEffect, useMemo, useState } from 'react'
import { EngineLogDock } from '../components/EngineLog.jsx'
import { getInferenceContext, setRecipeLifecycle } from '../lib/api.js'
import {
  benchMethodLabel,
  engineLabel,
  fmtCtx,
  fmtTokS,
  shortName,
  stackLabel,
} from '../lib/fmt.js'

const KV_LABELS = {
  auto: 'auto',
  fp8: 'fp8 (vLLM)',
  q8_0: 'q8_0 (llama.cpp)',
  q4_0: 'q4_0 (llama.cpp)',
  f16: 'f16',
}

const COLS = [
  { key: 'recipe', label: 'Recipe' },
  { key: 'engine', label: 'Engine' },
  { key: 'life', label: 'Life' },
  { key: 'bench', label: 'Bench' },
  { key: 'ctx', label: 'Context' },
]

function kvOptionsForEngine(engine) {
  if (engine === 'eugr') return ['auto', 'fp8']
  if (engine === 'llamacpp') return ['auto', 'q8_0', 'q4_0', 'f16']
  if (engine === 'ds4') return ['auto']
  return ['auto', 'fp8', 'q8_0', 'q4_0']
}

function sortVal(r, key) {
  if (key === 'engine') return String(r.engine || '')
  if (key === 'life') return String(r.lifecycle || 'works')
  if (key === 'bench') return Number(r.tok_s)
  if (key === 'ctx') return Number(r.context?.default) || 0
  return String(r.name || r.id || '').toLowerCase()
}

function cmpRows(a, b, sort) {
  const av = sortVal(a, sort.key)
  const bv = sortVal(b, sort.key)
  const aNum = typeof av === 'number'
  const bNum = typeof bv === 'number'
  let n = 0
  if (aNum || bNum) {
    const an = Number.isFinite(av) ? av : -1
    const bn = Number.isFinite(bv) ? bv : -1
    n = an - bn
  } else {
    n = String(av).localeCompare(String(bv))
  }
  return sort.dir === 'desc' ? -n : n
}

function launchPayload(launch) {
  if (!launch) return {}
  const out = {}
  const ctx = Number(launch.ctx)
  if (Number.isFinite(ctx) && ctx > 0) out.ctx = ctx
  if (launch.kv && launch.kv !== 'auto') out.kv = launch.kv
  if (launch.preset) out.preset = launch.preset
  return out
}

export function InferencePage({ live, actions }) {
  const active = live.inference?.active
  const activeId = active?.id
  const [q, setQ] = useState('')
  const [life, setLife] = useState('all')
  const [picked, setPicked] = useState(null)
  const [sort, setSort] = useState({ key: 'recipe', dir: 'asc' })
  const [plan, setPlan] = useState(null)
  const [launch, setLaunch] = useState({ preset: 'default', ctx: '', kv: 'auto' })
  const [lifeMsg, setLifeMsg] = useState(null)
  const [lifeBusy, setLifeBusy] = useState(false)

  const rows = useMemo(() => {
    const query = q.trim().toLowerCase()
    return [...(live.recipes || [])]
      .filter((r) => {
        if (life !== 'all' && (r.lifecycle || 'works') !== life) return false
        if (!query) return true
        const hay = `${r.name || ''} ${r.id || ''} ${r.engine || ''}`.toLowerCase()
        return hay.includes(query)
      })
      .sort((a, b) => cmpRows(a, b, sort))
  }, [live.recipes, q, life, sort])

  useEffect(() => {
    if (!picked && activeId) {
      const hit = (live.recipes || []).find((r) => r.id === activeId)
      if (hit) setPicked(hit)
    }
  }, [activeId, live.recipes, picked])

  const selected = picked || rows[0]
  const inspectingOther = selected && activeId && selected.id !== activeId

  useEffect(() => {
    if (!selected?.id) {
      setPlan(null)
      return
    }
    let cancelled = false
    getInferenceContext(selected.id)
      .then((d) => {
        if (cancelled) return
        setPlan(d)
        const c = d.context || {}
        const ctx = c.effective ?? c.default ?? ''
        const kv = c.kv_effective || c.kv_default || 'auto'
        const match = (c.presets || []).find((p) => p.ctx === ctx && (!p.kv || p.kv === kv || kv === 'auto'))
        setLaunch({
          preset: match?.id || 'default',
          ctx,
          kv,
        })
      })
      .catch(() => {
        if (!cancelled) setPlan(null)
      })
    return () => {
      cancelled = true
    }
  }, [selected?.id])

  const ctx = plan?.context || {}
  const planReady = plan?.profile === selected?.id
  const presets = ctx.presets || []
  const kvChoices = (ctx.kv_tested && ctx.kv_tested.length)
    ? ctx.kv_tested
    : kvOptionsForEngine(plan?.engine || selected?.engine)
  const liveCtx = Number(ctx.effective ?? ctx.default)
  const liveKv = ctx.kv_effective || ctx.kv_default || 'auto'
  const dirty = planReady && (
    Number(launch.ctx) !== liveCtx
    || (launch.kv || 'auto') !== liveKv
  )
  const isLive = selected && selected.id === activeId
  const canServe = Boolean(selected) && planReady && (inspectingOther || (isLive && dirty))

  function toggleSort(key) {
    setSort((prev) => (
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'bench' || key === 'ctx' ? 'desc' : 'asc' }
    ))
  }

  function pickPreset(p) {
    setLaunch({ preset: p.id, ctx: p.ctx, kv: p.kv || 'auto' })
  }

  function serveSelected(recipe = selected) {
    if (!recipe) return
    actions?.askSwitch(recipe, launchPayload(recipe.id === selected?.id ? launch : null))
  }

  async function cycleLife(kind) {
    if (!selected?.id) return
    if (kind === 'discard' && !window.confirm(`Discard draft ${selected.id}?`)) return
    if (kind !== 'discard' && !window.confirm(`${kind} ${selected.id}?`)) return
    setLifeBusy(true)
    setLifeMsg(null)
    try {
      await setRecipeLifecycle(kind, selected.id)
      setLifeMsg({ ok: true, text: `${kind} ${selected.id}` })
      live.refresh?.()
    } catch (err) {
      setLifeMsg({ ok: false, text: err.message || 'lifecycle failed' })
    } finally {
      setLifeBusy(false)
    }
  }

  const lc = selected?.lifecycle || 'works'
  const showDiscard = lc === 'draft'
  const showTesting = lc === 'draft' || lc === 'works'
  const showPromote = lc === 'testing' || lc === 'draft'
  const recLines = (ctx.recommendations || [])
    .map((r) => `${r.label}: ${fmtCtx(r.ctx)} — ${r.reason}`)
    .join(' ')
  const mem = ctx.mem_avail_gb != null && ctx.weight_gb != null
    ? ` ~${Math.round(ctx.weight_gb)} GB weights · ${ctx.mem_avail_gb} GB free.`
    : ''
  const ds4Hint = plan?.engine === 'ds4'
    ? ' ds4: ship ctx 32k (OOM-safe); cap 128k.'
    : ''

  return (
    <div className="inf-page">
      <div className="inf-scroll">
        <div className="page-head">
          <h1>Inference</h1>
          <p>What is on the GPU, then pick another recipe. Switch evicts the current one.</p>
        </div>

        <section className={`card serve-now${active ? '' : ' idle'}`}>
          <div className="serve-now-main">
            <h2>Now serving</h2>
            {active ? (
              <>
                <p className="hero-name">{active.name || active.id}</p>
                <p className="hero-meta">
                  {stackLabel(active.engine)}
                  {active.ready ? ' · ready' : active.starting ? ' · starting' : ' · not ready'}
                  {` · ${fmtCtx(active.context?.effective || active.context?.default)} context`}
                  {active.tok_s != null ? ` · bench ${fmtTokS(active.tok_s)} tok/s` : ''}
                </p>
              </>
            ) : (
              <p className="hero-name muted">Idle</p>
            )}
          </div>
          <button
            type="button"
            className="btn danger"
            disabled={!activeId}
            onClick={() => actions?.askStop()}
          >
            Stop
          </button>
        </section>
        {actions?.flash ? <p className={actions.flash.ok ? 'flash ok' : 'flash err'}>{actions.flash.text}</p> : null}

        <div className="grid inf-grid">
          <section className="card">
            <h2>Pick a recipe · {rows.length}</h2>
            <div className="toolbar tight">
              <input
                className="field grow"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Filter by name, id, engine…"
              />
              <select className="field" value={life} onChange={(e) => setLife(e.target.value)}>
                <option value="all">All lifecycle</option>
                <option value="production">production</option>
                <option value="works">works</option>
                <option value="testing">testing</option>
                <option value="draft">draft</option>
                <option value="failed">failed</option>
              </select>
            </div>
            <div className="table-wrap pick-wrap">
              <table className="pick-table">
                <thead>
                  <tr>
                    {COLS.map((col) => {
                      const on = sort.key === col.key
                      return (
                        <th key={col.key} aria-sort={on ? (sort.dir === 'desc' ? 'descending' : 'ascending') : 'none'}>
                          <button
                            type="button"
                            className={`th-sort${on ? ' on' : ''}`}
                            onClick={() => toggleSort(col.key)}
                          >
                            {col.label}
                            {on ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : ''}
                          </button>
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.id}
                      className={`${r.id === activeId ? 'active' : ''} ${selected?.id === r.id ? 'picked' : ''}`}
                      onClick={() => setPicked(r)}
                      onDoubleClick={() => r.id !== activeId && serveSelected(r)}
                    >
                      <td title={r.id}>
                        <div className="pid">
                          {r.name || r.id}
                          {r.id === activeId ? <span className="live-tag">live</span> : null}
                        </div>
                      </td>
                      <td>{engineLabel(r.engine)}</td>
                      <td>{r.lifecycle || 'works'}</td>
                      <td>{fmtTokS(r.tok_s)}</td>
                      <td>{fmtCtx(r.context?.default)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2>{inspectingOther ? 'Inspecting' : 'This recipe'}</h2>
            {selected ? (
              <>
                {inspectingOther ? (
                  <p className="flash warn">
                    Not on the GPU. {shortName(active?.name, activeId)} is still serving.
                  </p>
                ) : activeId ? (
                  <p className="flash ok">This is what is serving now.</p>
                ) : null}
                <p className="hero-name">{selected.name || selected.id}</p>
                <dl className="serve-facts">
                  <div>
                    <dt>Engine</dt>
                    <dd>{stackLabel(selected.engine)}</dd>
                  </div>
                  <div>
                    <dt>Lifecycle</dt>
                    <dd>{selected.lifecycle || 'works'}</dd>
                  </div>
                  {selected.tier ? (
                    <div>
                      <dt>Tier</dt>
                      <dd>{selected.tier}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Bench speed</dt>
                    <dd>{fmtTokS(selected.tok_s)} tok/s</dd>
                  </div>
                  <div>
                    <dt>Bench method</dt>
                    <dd>{benchMethodLabel(selected.tok_s_method)}</dd>
                  </div>
                </dl>
                {selected.notes ? <p className="notes">{selected.notes}</p> : null}

                <div className="ctx-panel">
                  <div className="ctx-head">
                    <span>Context window</span>
                    <em>
                      {ctx.native ? `native ${fmtCtx(ctx.native)}` : 'native unknown'}
                      {ctx.default ? ` · default ${fmtCtx(ctx.default)}` : ''}
                    </em>
                  </div>
                  <div className="ctx-presets">
                    {presets.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`ctx-preset${launch.preset === p.id ? ' on' : ''}${p.source === 'ctx_ladder' ? ' tested' : ''}`}
                        title={`${p.label} · ${fmtCtx(p.ctx)}${p.kv && p.kv !== 'auto' ? ` kv ${p.kv}` : ''}`}
                        onClick={() => pickPreset(p)}
                      >
                        {p.label} {fmtCtx(p.ctx)}
                      </button>
                    ))}
                  </div>
                  <div className="ctx-row">
                    <label>
                      Max context
                      <input
                        className="field"
                        type="number"
                        min="4096"
                        step="1024"
                        max={plan?.engine === 'ds4' ? '131072' : undefined}
                        placeholder={plan?.engine === 'ds4' ? '32768' : '65536'}
                        value={launch.ctx}
                        onChange={(e) => setLaunch((prev) => ({ ...prev, ctx: e.target.value, preset: null }))}
                      />
                    </label>
                    <label>
                      KV cache
                      <select
                        className="field"
                        value={launch.kv}
                        disabled={plan?.engine === 'ds4'}
                        onChange={(e) => setLaunch((prev) => ({ ...prev, kv: e.target.value }))}
                      >
                        {kvChoices.map((k) => (
                          <option key={k} value={k}>
                            {plan?.engine === 'ds4' && k === 'auto' ? 'auto (ds4 packed FP8/FP4)' : (KV_LABELS[k] || k)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <p className="ctx-hint">{recLines}{mem}{ds4Hint}</p>
                </div>

                <div className="toolbar tight" style={{ marginTop: '.85rem' }}>
                  <button
                    type="button"
                    className="btn primary"
                    disabled={!canServe}
                    onClick={() => serveSelected(selected)}
                  >
                    {isLive ? 'Relaunch with these settings' : 'Serve this recipe'}
                  </button>
                </div>
                {(showTesting || showPromote || showDiscard) ? (
                  <details className="life-box">
                    <summary>Lifecycle</summary>
                    <div className="toolbar tight">
                      {showTesting ? (
                        <button type="button" className="btn" disabled={lifeBusy} onClick={() => cycleLife('testing')}>
                          Mark testing
                        </button>
                      ) : null}
                      {showPromote ? (
                        <button type="button" className="btn" disabled={lifeBusy} onClick={() => cycleLife('promote')}>
                          Promote
                        </button>
                      ) : null}
                      {showDiscard ? (
                        <button type="button" className="btn danger" disabled={lifeBusy} onClick={() => cycleLife('discard')}>
                          Discard draft
                        </button>
                      ) : null}
                    </div>
                  </details>
                ) : null}
                {lifeMsg ? <p className={lifeMsg.ok ? 'flash ok' : 'flash err'}>{lifeMsg.text}</p> : null}
              </>
            ) : (
              <p className="muted">No recipe selected.</p>
            )}
          </section>
        </div>
      </div>
      <EngineLogDock />
    </div>
  )
}
