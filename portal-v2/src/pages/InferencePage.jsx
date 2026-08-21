import { useEffect, useMemo, useState } from 'react'
import { getInferenceLogs, setRecipeLifecycle } from '../lib/api.js'
import {
  benchMethodLabel,
  engineLabel,
  fmtCtx,
  fmtTokS,
  shortName,
  stackLabel,
} from '../lib/fmt.js'

const LOG_NOISE = /\/v1\/models|\/metrics|healthz|GET \/health/i

function usefulLog(line) {
  const s = typeof line === 'string' ? line : JSON.stringify(line)
  return !LOG_NOISE.test(s)
}

export function InferencePage({ live, actions }) {
  const active = live.inference?.active
  const activeId = active?.id
  const [q, setQ] = useState('')
  const [life, setLife] = useState('all')
  const [picked, setPicked] = useState(null)
  const [logs, setLogs] = useState(null)
  const [logErr, setLogErr] = useState(null)
  const [logOpen, setLogOpen] = useState(false)
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
      .sort((a, b) => {
        if (a.id === activeId) return -1
        if (b.id === activeId) return 1
        return String(a.name || a.id).localeCompare(String(b.name || b.id))
      })
  }, [live.recipes, q, life, activeId])

  useEffect(() => {
    if (!picked && activeId) {
      const hit = (live.recipes || []).find((r) => r.id === activeId)
      if (hit) setPicked(hit)
    }
  }, [activeId, live.recipes, picked])

  useEffect(() => {
    let cancelled = false
    async function tick() {
      try {
        const data = await getInferenceLogs(80)
        if (cancelled) return
        setLogs(data)
        setLogErr(null)
        if (data?.switch?.running) setLogOpen(true)
      } catch (err) {
        if (!cancelled) setLogErr(err.message || 'logs unavailable')
      }
    }
    tick()
    const t = setInterval(tick, 3000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [])

  const selected = picked || rows[0]
  const inspectingOther = selected && activeId && selected.id !== activeId
  const switching = Boolean(logs?.switch?.running)
  const logLines = (() => {
    const fmt = (line) => (typeof line === 'string' ? line : JSON.stringify(line))
    const raw = (logs?.sections || []).flatMap((s) => (s.lines || []).map(fmt))
    const all = raw.length ? raw : (logs?.lines || []).map(fmt)
    return all.filter(usefulLog)
  })()

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

  return (
    <div>
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
          disabled={!activeId || switching}
          onClick={() => actions?.askStop()}
        >
          Stop
        </button>
      </section>
      {actions?.flash ? <p className={actions.flash.ok ? 'flash ok' : 'flash err'}>{actions.flash.text}</p> : null}
      {switching ? <p className="flash warn">Switch in progress… engine log is open below.</p> : null}

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
          <div className="table-wrap" style={{ maxHeight: '52vh' }}>
            <table className="pick-table">
              <thead>
                <tr>
                  <th>Recipe</th>
                  <th>Engine</th>
                  <th>Life</th>
                  <th>Bench</th>
                  <th>Context</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    className={`${r.id === activeId ? 'active' : ''} ${selected?.id === r.id ? 'picked' : ''}`}
                    onClick={() => setPicked(r)}
                    onDoubleClick={() => r.id !== activeId && actions?.askSwitch(r)}
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
                  <dt>Context</dt>
                  <dd>{fmtCtx(selected.context?.effective || selected.context?.default)} tokens</dd>
                </div>
                {selected.context?.kv_effective ? (
                  <div>
                    <dt>KV type</dt>
                    <dd>{selected.context.kv_effective}</dd>
                  </div>
                ) : null}
                {selected.context?.mem_avail_gb != null ? (
                  <div>
                    <dt>KV headroom</dt>
                    <dd>{Number(selected.context.mem_avail_gb).toFixed(1)} GB</dd>
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
              <div className="toolbar tight" style={{ marginTop: '.85rem' }}>
                <button
                  type="button"
                  className="btn primary"
                  disabled={!inspectingOther || switching}
                  onClick={() => actions?.askSwitch(selected)}
                >
                  Serve this recipe
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

          <button type="button" className="log-toggle" onClick={() => setLogOpen((v) => !v)}>
            Engine log {logOpen ? '· hide' : '· show'}
            {logLines.length ? ` · ${logLines.length} lines` : ''}
          </button>
          {logOpen ? (
            <>
              {logErr ? <p className="err">{logErr}</p> : null}
              <pre className="log">{logLines.length ? logLines.join('\n') : 'No non-health-check lines right now.'}</pre>
            </>
          ) : null}
        </section>
      </div>
    </div>
  )
}
