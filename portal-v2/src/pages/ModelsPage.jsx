import { useEffect, useMemo, useState } from 'react'
import { getInventory, getShelfStatus } from '../lib/api.js'
import { engineLabel, fmtTokS } from '../lib/fmt.js'

function sizeLabel(m) {
  if (m.size_human) return m.size_human
  if (m.size_gb) return `${Number(m.size_gb).toFixed(1)} GB`
  if (m.size_bytes) return `${(Number(m.size_bytes) / 1e9).toFixed(1)} GB`
  return '—'
}

function verifyLabel(m) {
  const v = m.spark_verify
  if (v && typeof v === 'object') return v.spark_status || '—'
  return m.verify || m.status || '—'
}

function engineOf(m) {
  if (m.engine) return m.engine
  if (Array.isArray(m.engines) && m.engines.length) return m.engines.join(', ')
  return ''
}

export function ModelsPage() {
  const [data, setData] = useState(null)
  const [shelf, setShelf] = useState(null)
  const [err, setErr] = useState(null)
  const [q, setQ] = useState('')
  const [engine, setEngine] = useState('all')

  useEffect(() => {
    getInventory()
      .then(setData)
      .catch((e) => setErr(e.message || 'models.json failed'))
    getShelfStatus()
      .then(setShelf)
      .catch(() => setShelf(null))
  }, [])

  const models = data?.models || []
  const engines = useMemo(() => {
    const set = new Set(models.flatMap((m) => m.engines || (m.engine ? [m.engine] : [])).filter(Boolean))
    return [...set].sort()
  }, [models])

  const rows = useMemo(() => {
    const query = q.trim().toLowerCase()
    return models.filter((m) => {
      if (engine !== 'all' && !(m.engines || []).includes(engine) && m.engine !== engine) return false
      if (!query) return true
      const hay = `${m.name || ''} ${m.id || ''} ${m.rel_path || ''} ${m.family || ''}`.toLowerCase()
      return hay.includes(query)
    })
  }, [models, q, engine])

  return (
    <div>
      <div className="page-head">
        <h1>Models</h1>
        <p>
          Local inventory{data?.generated_at ? ` · built ${new Date(data.generated_at).toLocaleString()}` : ''}
          {shelf?.shelf_mounted || data?.shelf_mounted ? ' · shelf mounted' : ' · shelf unmounted'}
          {shelf?.job?.running ? ` · shelf job ${shelf.job.action || 'running'}` : ''}.
        </p>
      </div>

      <div className="toolbar">
        <input
          className="field grow"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Filter weights…"
        />
        <select className="field" value={engine} onChange={(e) => setEngine(e.target.value)}>
          <option value="all">All engines</option>
          {engines.map((e) => <option key={e} value={e}>{engineLabel(e)}</option>)}
        </select>
        <a className="btn" href="/models.html" target="_blank" rel="noopener noreferrer">Full library</a>
      </div>
      {err ? <p className="flash err">{err}</p> : null}

      <section className="card">
        <h2>{rows.length} weights</h2>
        <div className="table-wrap" style={{ maxHeight: '70vh' }}>
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Engine</th>
                <th>Size</th>
                <th>Tok/s</th>
                <th>Verify</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id || m.rel_path}>
                  <td title={m.rel_path || m.path}>
                    <div className="pid">{m.name || m.id}</div>
                    <div className="pname">{m.rel_path || m.id}</div>
                  </td>
                  <td>{engineLabel(engineOf(m))}</td>
                  <td>{sizeLabel(m)}</td>
                  <td>{fmtTokS(m.best_bench_tok_s || m.tok_s)}</td>
                  <td>{verifyLabel(m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
