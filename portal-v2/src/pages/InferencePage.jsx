import { engineLabel, fmtCtx, fmtTokS } from '../lib/fmt.js'

export function InferencePage({ live }) {
  const activeId = live.inference?.active?.id
  const rows = [...(live.recipes || [])].sort((a, b) => {
    if (a.id === activeId) return -1
    if (b.id === activeId) return 1
    return String(a.name || a.id).localeCompare(String(b.name || b.id))
  })

  return (
    <div>
      <div className="page-head">
        <h1>Inference</h1>
        <p>Read-only this phase. Switch still happens in the legacy UI or via <code>spark inference up</code>.</p>
      </div>
      <section className="card">
        <h2>{rows.length} recipes</h2>
        <div className="table-wrap" style={{ maxHeight: '70vh' }}>
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
                <tr key={r.id} className={r.id === activeId ? 'active' : ''}>
                  <td title={r.id}>{r.name || r.id}</td>
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
    </div>
  )
}
