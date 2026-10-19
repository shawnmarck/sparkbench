import { useMemo, useState } from 'react'
import { engineLabel, fmtTokS } from '../lib/fmt.js'

const FILLS = [
  ['4k', '4k'],
  ['50k', '50k'],
  ['100k', '100k'],
]
const FILL_ORDER = ['4k', '50k', '100k']
const FILL_TOKENS = { '4k': 4096, '50k': 50000, '100k': 100000 }

const COLS = [
  { key: 'name', label: 'Model', cls: 'lb-name-col' },
  { key: 'use_cases', label: 'For', cls: 'lb-tags-col', plain: true },
  { key: 'params', label: 'Params', num: true },
  { key: 'released', label: 'Released', num: true, cls: 'lb-date-col' },
  { key: 'curve', label: 'Curve', cls: 'lb-curve-col' },
  { key: 'speed', label: 'Speed', num: true },
  { key: 'swe', label: 'SWE', num: true },
  { key: 'tb', label: 'TB', num: true },
]

const AGES = [
  ['all', 'Any age'],
  ['3m', '≤ 3 months'],
  ['6m', '≤ 6 months'],
  ['12m', '≤ 12 months'],
  ['24m', '≤ 24 months'],
]
const AGE_DAYS = { '3m': 92, '6m': 183, '12m': 365, '24m': 730 }

function releasedMs(r) {
  const t = Date.parse(r.released || '')
  return Number.isFinite(t) ? t : null
}

function ageLabel(ms) {
  if (ms == null) return '—'
  const days = (Date.now() - ms) / 86400000
  if (days < 0) return 'unreleased'
  if (days < 30) return `${Math.max(1, Math.round(days / 7))} wk`
  if (days < 365) return `${Math.round(days / 30.44)} mo`
  return `${(days / 365).toFixed(1)} yr`
}

function fmtB(n) {
  const v = Number(n)
  if (!Number.isFinite(v)) return '—'
  if (v >= 10) return `${Math.round(v)}B`
  return `${String(v.toFixed(1)).replace(/\.0$/, '')}B`
}

function paramsLabel(r) {
  const i = r.identity || {}
  const total = Number(i.param_b)
  const active = Number(i.param_active_b)
  if (!Number.isFinite(total) && !Number.isFinite(active)) return '—'
  if (Number.isFinite(active) && Number.isFinite(total) && active < total) {
    return `${fmtB(active)} / ${fmtB(total)}`
  }
  return fmtB(Number.isFinite(total) ? total : active)
}

function pbmPoints(pbm) {
  return FILL_ORDER
    .map((k) => ({ fill: k, tok: Number((pbm || {})[k]) }))
    .filter((p) => Number.isFinite(p.tok))
}

function Sparkline({ pbm }) {
  const pts = pbmPoints(pbm)
  if (pts.length < 2) {
    return pts.length === 1
      ? <span className="lb-empty" title={`Only a ${pts[0].fill} PBM fill — 50k/100k not measured`}>{pts[0].fill} only</span>
      : <span className="lb-empty">—</span>
  }
  const w = 64
  const h = 22
  const padX = 3
  const padY = 3
  const ys = pts.map((p) => p.tok)
  const yMin = Math.min(...ys)
  const yMax = Math.max(...ys)
  const ySpan = Math.max(yMax - yMin, 0.1)
  const xSpan = Math.max(pts.length - 1, 1)
  const coords = ys.map((y, i) => {
    const px = padX + (i / xSpan) * (w - 2 * padX)
    const py = h - padY - ((y - yMin) / ySpan) * (h - 2 * padY)
    return [Number(px.toFixed(1)), Number(py.toFixed(1))]
  })
  return (
    <svg className="lb-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" focusable="false">
      <polyline
        fill="none"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={coords.map((c) => `${c[0]},${c[1]}`).join(' ')}
      />
      {coords.map((c, i) => (
        <circle key={pts[i].fill} cx={c[0]} cy={c[1]} r="1.6" fill="var(--accent)" />
      ))}
    </svg>
  )
}

function sortValue(r, key, fill) {
  const evals = r.evals || {}
  if (key === 'name') return String(r.name || r.id || '').toLowerCase()
  if (key === 'use_cases') return (r.use_cases || []).join(' ').toLowerCase()
  if (key === 'params') {
    const i = r.identity || {}
    const total = Number(i.param_b)
    if (Number.isFinite(total)) return total
    const active = Number(i.param_active_b)
    return Number.isFinite(active) ? active : null
  }
  if (key === 'released') return releasedMs(r)
  if (key === 'curve') {
    const pts = pbmPoints(r.pbm)
    return pts.length ? pts[0].tok : null
  }
  if (key === 'speed') {
    const v = Number((r.pbm || {})[fill])
    return Number.isFinite(v) ? v : null
  }
  if (key === 'swe') {
    const v = Number((evals.swe || {}).score)
    return Number.isFinite(v) ? v : null
  }
  if (key === 'tb') {
    const v = Number((evals.tb || {}).score)
    return Number.isFinite(v) ? v : null
  }
  return null
}

function compare(a, b, key, dir, fill) {
  const av = sortValue(a, key, fill)
  const bv = sortValue(b, key, fill)
  const aMiss = av === null || av === undefined || (typeof av === 'number' && !Number.isFinite(av))
  const bMiss = bv === null || bv === undefined || (typeof bv === 'number' && !Number.isFinite(bv))
  let n = 0
  if (aMiss && bMiss) n = 0
  else if (aMiss) n = 1
  else if (bMiss) n = -1
  else if (typeof av === 'number' && typeof bv === 'number') n = av - bv
  else n = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' })
  if (n === 0) n = String(a.name || a.id || '').localeCompare(String(b.name || b.id || ''))
  return dir === 'desc' ? -n : n
}

export function Leaderboard({ recipes, onInspect }) {
  const [fill, setFill] = useState('4k')
  const [q, setQ] = useState('')
  const [age, setAge] = useState('all')
  const [measuredOnly, setMeasuredOnly] = useState(true)
  const [sort, setSort] = useState({ key: 'speed', dir: 'desc' })

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const maxAge = AGE_DAYS[age]
    const now = Date.now()
    return (recipes || [])
      .filter((r) => {
        if (measuredOnly && !Number.isFinite(Number((r.pbm || {})[fill]))) return false
        if (maxAge) {
          const ms = releasedMs(r)
          if (ms == null || (now - ms) / 86400000 > maxAge) return false
        }
        if (!needle) return true
        const hay = [
          r.name, r.id, (r.identity || {}).lab, (r.identity || {}).family,
          (r.identity || {}).variant, (r.identity || {}).quant, r.engine,
          ...(r.use_cases || []),
        ].filter(Boolean).join(' ').toLowerCase()
        return hay.includes(needle)
      })
      .sort((a, b) => compare(a, b, sort.key, sort.dir, fill))
  }, [recipes, q, measuredOnly, sort, fill, age])

  const maxSpeed = useMemo(() => {
    const vals = rows.map((r) => Number((r.pbm || {})[fill])).filter((v) => Number.isFinite(v))
    return vals.length ? Math.max(...vals) : 0
  }, [rows, fill])

  const withSpeed = rows.filter((r) => Number.isFinite(Number((r.pbm || {})[fill]))).length

  function toggleSort(key) {
    setSort((prev) => (
      prev.key === key
        ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: key === 'speed' || key === 'swe' || key === 'tb' || key === 'params' || key === 'curve' || key === 'released' ? 'desc' : 'asc' }
    ))
  }

  return (
    <section className="card lb-card">
      <div className="lb-head">
        <h2>Leaderboard · {withSpeed} of {rows.length} measured</h2>
        <span className="lb-note">
          PBM decode tok/s after prefilling a fixed context. SWE / TB are published vendor
          figures for the base model — not measured on this Spark.
        </span>
      </div>

      <div className="toolbar tight">
        <input
          className="field grow"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search models, labs, quants, use cases…"
        />
        <span className="lb-fill" role="group" aria-label="Context fill for ranking">
          {FILLS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`chip${fill === key ? ' on' : ''}`}
              title={`Rank by decode tok/s at ${FILL_TOKENS[key].toLocaleString()} tokens of context fill`}
              onClick={() => setFill(key)}
            >
              {label}
            </button>
          ))}
        </span>
        <button
          type="button"
          className={`chip${measuredOnly ? ' on' : ''}`}
          onClick={() => setMeasuredOnly((v) => !v)}
          title="Hide recipes with no PBM measurement at this fill"
        >
          Measured only
        </button>
        <select
          className="field"
          value={age}
          onChange={(e) => setAge(e.target.value)}
          title="Only show models released within this window"
          aria-label="Model age filter"
        >
          {AGES.map(([key, label]) => (
            <option key={key} value={key}>{label}</option>
          ))}
        </select>
      </div>

      <div className="table-wrap lb-wrap">
        <table className="pick-table lb-table">
          <thead>
            <tr>
              <th className="lb-rank-col">#</th>
              {COLS.map((col) => {
                const on = sort.key === col.key
                return (
                  <th
                    key={col.key}
                    className={`${col.num ? 'num' : ''}${col.cls ? ` ${col.cls}` : ''}`}
                    aria-sort={on ? (sort.dir === 'desc' ? 'descending' : 'ascending') : 'none'}
                  >
                    {col.plain ? col.label : (
                      <button
                        type="button"
                        className={`th-sort${on ? ' on' : ''}`}
                        onClick={() => toggleSort(col.key)}
                      >
                        {col.label}
                        {col.key === 'speed' ? ` @ ${fill}` : ''}
                        {on ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : ''}
                      </button>
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length ? rows.map((r, idx) => {
              const i = r.identity || {}
              const evals = r.evals || {}
              const swe = evals.swe || null
              const tb = evals.tb || null
              const speed = Number((r.pbm || {})[fill])
              const pct = Number.isFinite(speed) && maxSpeed > 0 ? (speed / maxSpeed) * 100 : 0
              return (
                <tr
                  key={r.id}
                  className={r.id === undefined ? '' : ''}
                  onClick={onInspect ? () => onInspect(r) : undefined}
                  title={onInspect ? 'Open in the recipe picker' : undefined}
                >
                  <td className="lb-rank-col"><span className="lb-rank-num">{String(idx + 1).padStart(2, '0')}</span></td>
                  <td className="lb-name-col">
                    <div className="pid">{r.name || r.id}</div>
                    <div className="pname">
                      {i.lab}{i.quant ? ` · ${i.quant}` : ''}{r.engine ? ` · ${engineLabel(r.engine)}` : ''}
                    </div>
                  </td>
                  <td className="lb-tags-col">
                    {(r.use_cases || []).length
                      ? (r.use_cases || []).map((uc) => <span key={uc} className="lb-tag">{uc}</span>)
                      : <span className="lb-empty">—</span>}
                  </td>
                  <td className="num">{paramsLabel(r)}</td>
                  <td
                    className="num lb-date-col"
                    title={r.released
                      ? `${String(r.released).slice(0, 10)}${r.released_source ? ` · ${r.released_source}` : ''}`
                      : 'release date unknown'}
                  >
                    {releasedMs(r) != null ? ageLabel(releasedMs(r)) : <span className="lb-empty">—</span>}
                  </td>
                  <td className="lb-curve-col">
                    <Sparkline pbm={r.pbm} />
                  </td>
                  <td className="num lb-speed-col">
                    {Number.isFinite(speed) ? (
                      <>
                        <span className="lb-bar"><span className="lb-bar-fill" style={{ width: `${Math.max(3, pct)}%` }} /></span>
                        <span className="lb-speed">
                          {fmtTokS(speed)}<span className="lb-unit">t/s</span>
                        </span>
                      </>
                    ) : <span className="lb-empty">—</span>}
                  </td>
                  <td className="num">
                    {swe ? (
                      <a
                        className={`lb-eval${evals.inherited ? ' lb-eval-inherited' : ''}`}
                        href={swe.source_url || undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        title={`${swe.source_name}${swe.as_of ? ` · ${swe.as_of}` : ''}${evals.inherited ? ` — published for ${evals.base}, not this pack` : ''}`}
                      >
                        {swe.score}<span className="lb-unit">%</span>
                      </a>
                    ) : <span className="lb-empty">—</span>}
                  </td>
                  <td className="num">
                    {tb ? (
                      <a
                        className={`lb-eval${evals.inherited ? ' lb-eval-inherited' : ''}`}
                        href={tb.source_url || undefined}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        title={`${tb.source_name}${tb.suite ? ` · suite ${tb.suite}` : ''}${tb.as_of ? ` · ${tb.as_of}` : ''}${evals.inherited ? ` — published for ${evals.base}, not this pack` : ''}`}
                      >
                        {tb.score}<span className="lb-unit">%</span>
                      </a>
                    ) : <span className="lb-empty">—</span>}
                  </td>
                </tr>
              )
            }) : (
              <tr>
                <td className="pick-empty" colSpan={COLS.length + 1}>
                  Nothing matches.
                  {measuredOnly ? (
                    <button type="button" className="btn" onClick={() => setMeasuredOnly(false)}>Include unmeasured</button>
                  ) : null}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
