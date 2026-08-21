import { useEffect, useMemo, useState } from 'react'
import { getInferenceLogs, setRecipeLifecycle } from '../lib/api.js'
import { engineLabel, fmtCtx, fmtTokS } from '../lib/fmt.js'

function ctxHint(recipe) {
  const ctx = recipe?.context || {}
  const ladder = ctx.ctx_ladder
  const keys = ladder && typeof ladder === 'object' ? Object.keys(ladder) : []
  const def = fmtCtx(ctx.default)
  if (!keys.length) return def
  return `${def} · ladder ${keys.join('/')}`
}

export function InferencePage({ live, actions }) {
  const activeId = live.inference?.active?.id
  const [q, setQ] = useState('')
  const [life, setLife] = useState('all')
  const [picked, setPicked] = useState(null)
  const [logs, setLogs] = useState(null)
  const [logErr, setLogErr] = useState(null)
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
        const data = await getInferenceLogs(60)
        if (!cancelled) {
          setLogs(data)
          setLogErr(null)
        }
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
  const switching = Boolean(logs?.switch?.running)
  const logLines = (() => {
    const fmt = (line) => (typeof line === 'string' ? line : JSON.stringify(line))
    const fromSections = (logs?.sections || []).flatMap((s) =>
      (s.lines || []).map((line) => `[${s.kind}] ${fmt(line)}`)
    )
    if (fromSections.length) return fromSections.join('\n')
    return (logs?.lines || []).map(fmt).join('\n')
  })()

  function askServe(recipe) {
    actions?.askSwitch(recipe)
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

  return (
    <div>
      <div className="page-head">
        <h1>Inference</h1>
        <p>Pick a recipe, confirm the switch, watch the engine log. Mutations evict whatever is serving now.</p>
      </div>

      <div className="toolbar">
        <input
          className="field"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter recipes…"
        />
        <select className="field" value={life} onChange={(e) => setLife(e.target.value)}>
          <option value="all">All lifecycle</option>
          <option value="production">production</option>
          <option value="works">works</option>
          <option value="testing">testing</option>
          <option value="draft">draft</option>
        </select>
        <button type="button" className="btn primary" disabled={!selected || selected.id === activeId || switching} onClick={() => askServe(selected)}>
          Serve selected
        </button>
        <button type="button" className="btn danger" disabled={!activeId || switching} onClick={() => actions?.askStop()}>
          Stop
        </button>
      </div>
      {actions?.flash ? <p className={actions.flash.ok ? 'flash ok' : 'flash err'}>{actions.flash.text}</p> : null}
      {switching ? <p className="flash warn">Switch in progress…</p> : null}

      <div className="grid inf-grid">
        <section className="card">
          <h2>{rows.length} recipes</h2>
          <div className="table-wrap" style={{ maxHeight: '58vh' }}>
            <table>
              <thead>
                <tr>
                  <th>Recipe</th>
                  <th>Engine</th>
                  <th>Life</th>
                  <th>Tok/s</th>
                  <th>Ctx</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    className={`${r.id === activeId ? 'active' : ''} ${selected?.id === r.id ? 'picked' : ''}`}
                    onClick={() => setPicked(r)}
                    onDoubleClick={() => askServe(r)}
                  >
                    <td title={r.id}>
                      <div className="pid">{r.name || r.id}</div>
                      <div className="pname">{r.id}</div>
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
          <h2>Selected</h2>
          {selected ? (
            <>
              <p className="hero-name">{selected.name || selected.id}</p>
              <p className="hero-meta">
                {engineLabel(selected.engine)} · {selected.lifecycle || 'works'}
                {selected.tier ? ` · ${selected.tier}` : ''}
              </p>
              <p className="hero-meta tall">{ctxHint(selected)}</p>
              {selected.notes ? <p className="muted">{selected.notes}</p> : null}
              <div className="toolbar tight" style={{ marginTop: '.8rem' }}>
                <button type="button" className="btn" disabled={lifeBusy} onClick={() => cycleLife('testing')}>Mark testing</button>
                <button type="button" className="btn" disabled={lifeBusy} onClick={() => cycleLife('promote')}>Promote</button>
                <button type="button" className="btn danger" disabled={lifeBusy} onClick={() => cycleLife('discard')}>Discard draft</button>
              </div>
              {lifeMsg ? <p className={lifeMsg.ok ? 'flash ok' : 'flash err'}>{lifeMsg.text}</p> : null}
            </>
          ) : (
            <p className="muted">No recipe selected.</p>
          )}
          <h2 style={{ marginTop: '1.1rem' }}>Engine log</h2>
          {logErr ? <p className="err">{logErr}</p> : null}
          <pre className="log">{logLines || '—'}</pre>
        </section>
      </div>

    </div>
  )
}
