import { useEffect, useState } from 'react'
import { getLedger, putPricing } from '../lib/api.js'
import { matchComp } from '../lib/cloudComps.js'
import { fmtRate, fmtTokens, fmtUsd } from '../lib/fmt.js'
import { countsOf } from '../lib/usage.js'

const GRAINS = [
  { id: 'day', label: 'Day' },
  { id: 'month', label: 'Month' },
  { id: 'qtr', label: 'Quarter' },
  { id: 'year', label: 'Year' },
]

function rateFields(inVal, outVal, onIn, onOut, id) {
  return (
    <div className="rate-fields">
      <label>
        In $/M
        <input
          id={`${id}-in`}
          className="field"
          type="number"
          min="0"
          step="0.001"
          inputMode="decimal"
          value={inVal}
          onChange={(e) => onIn(e.target.value)}
        />
      </label>
      <label>
        Out $/M
        <input
          id={`${id}-out`}
          className="field"
          type="number"
          min="0"
          step="0.001"
          inputMode="decimal"
          value={outVal}
          onChange={(e) => onOut(e.target.value)}
        />
      </label>
    </div>
  )
}

function numOrZero(s) {
  const n = Number(s)
  return Number.isFinite(n) && n >= 0 ? n : 0
}

function sourceLabel(row) {
  if (row.override) return 'this view'
  if (row.source === 'mixed') return 'mixed'
  if (row.source === 'history') return 'at the time'
  if (row.source === 'default') return 'current'
  if (row.source === 'day') return 'day'
  if (row.source === 'month') return 'month'
  if (row.source === 'qtr') return 'quarter'
  if (row.source === 'year') return 'year'
  return row.source || 'current'
}

export function PriceLedger({ profileId, profileName, onClose, onSaved }) {
  const [grain, setGrain] = useState('day')
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [defIn, setDefIn] = useState('')
  const [defOut, setDefOut] = useState('')
  const [selected, setSelected] = useState(null)
  const [ovIn, setOvIn] = useState('')
  const [ovOut, setOvOut] = useState('')
  const [history, setHistory] = useState([])
  const analog = matchComp(profileId)
  const grainLabel = GRAINS.find((g) => g.id === grain)?.label || 'Day'

  function applyLedger(ledger) {
    setData(ledger)
    setDefIn(String(ledger.default?.in_per_m ?? 0))
    setDefOut(String(ledger.default?.out_per_m ?? 0))
    setHistory((ledger.history || []).map((h) => ({
      from: h.from || '',
      to: h.to || '',
      in_per_m: String(h.in_per_m ?? 0),
      out_per_m: String(h.out_per_m ?? 0),
    })))
  }

  useEffect(() => {
    let cancelled = false
    setErr(null)
    getLedger(profileId, grain)
      .then((ledger) => {
        if (!cancelled) applyLedger(ledger)
      })
      .catch((e) => {
        if (!cancelled) setErr(e.message || 'failed to load ledger')
      })
    return () => { cancelled = true }
  }, [profileId, grain])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  function pickRow(row) {
    setSelected((cur) => (cur === row.key ? null : row.key))
    const inn = row.in_per_m != null ? row.in_per_m : data?.default?.in_per_m
    const out = row.out_per_m != null ? row.out_per_m : data?.default?.out_per_m
    setOvIn(String(inn ?? 0))
    setOvOut(String(out ?? 0))
  }

  async function run(body) {
    setBusy(true)
    setErr(null)
    try {
      const ledger = await putPricing({ ...body, profile: profileId, grain })
      applyLedger(ledger)
      onSaved?.()
    } catch (e) {
      setErr(e.message || 'save failed')
    } finally {
      setBusy(false)
    }
  }

  const sel = (data?.rows || []).find((r) => r.key === selected)
  const totals = data?.totals || {}
  const mix = countsOf({
    prompt_tokens: totals.prompt_tokens,
    completion_tokens: totals.completion_tokens,
    requests: totals.requests,
  })

  return (
    <div className="modal-scrim" onClick={busy ? undefined : onClose} role="presentation">
      <div
        className="modal ledger"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ledger-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="ledger-head">
          <div>
            <h3 id="ledger-title">{profileName || profileId}</h3>
            <p>
              Default is the current OpenRouter analog (new traffic). History periods price older
              days at the rate from that time. A {grainLabel.toLowerCase()} override still wins.
            </p>
          </div>
          <button type="button" className="btn" disabled={busy} onClick={onClose}>Close</button>
        </div>

        <div className="ledger-body">
          {err ? <p className="flash err">{err}</p> : null}

          <div className="ledger-block">
            <div className="ledger-block-head">
              <span>Current price</span>
              {analog ? (
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  title={`${analog.slug} · ${analog.provider} · ${analog.asOf}`}
                  onClick={() => {
                    setDefIn(String(analog.inPerM))
                    setDefOut(String(analog.outPerM))
                  }}
                >
                  Use analog
                </button>
              ) : null}
            </div>
            <div className="ledger-edit">
              {rateFields(defIn, defOut, setDefIn, setDefOut, 'def')}
              <button
                type="button"
                className="btn primary"
                disabled={busy}
                onClick={() => run({ default: { in_per_m: numOrZero(defIn), out_per_m: numOrZero(defOut) } })}
              >
                Save current
              </button>
            </div>
          </div>

          <div className="ledger-block">
            <div className="ledger-block-head">
              <span>Rate history</span>
              <button
                type="button"
                className="btn"
                disabled={busy}
                onClick={() => setHistory((cur) => [...cur, {
                  from: '',
                  to: '',
                  in_per_m: defIn,
                  out_per_m: defOut,
                }])}
              >
                Add period
              </button>
            </div>
            {history.length ? history.map((h, i) => (
              <div key={`${h.from}-${i}`} className="ledger-edit history-row">
                <label>
                  From
                  <input
                    className="field"
                    type="date"
                    value={h.from}
                    onChange={(e) => setHistory((cur) => cur.map((row, j) => (
                      j === i ? { ...row, from: e.target.value } : row
                    )))}
                  />
                </label>
                <label>
                  To
                  <input
                    className="field"
                    type="date"
                    value={h.to}
                    onChange={(e) => setHistory((cur) => cur.map((row, j) => (
                      j === i ? { ...row, to: e.target.value } : row
                    )))}
                  />
                </label>
                {rateFields(
                  h.in_per_m,
                  h.out_per_m,
                  (v) => setHistory((cur) => cur.map((row, j) => (j === i ? { ...row, in_per_m: v } : row))),
                  (v) => setHistory((cur) => cur.map((row, j) => (j === i ? { ...row, out_per_m: v } : row))),
                  `hist-${i}`,
                )}
                <button
                  type="button"
                  className="btn"
                  disabled={busy}
                  onClick={() => setHistory((cur) => cur.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </div>
            )) : (
              <p className="ledger-hint">No history yet. Add a period so older days use the price from that time.</p>
            )}
            {history.length ? (
              <div className="ledger-edit">
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy}
                  onClick={() => run({
                    history: history
                      .filter((h) => h.from && h.to)
                      .map((h) => ({
                        from: h.from,
                        to: h.to,
                        in_per_m: numOrZero(h.in_per_m),
                        out_per_m: numOrZero(h.out_per_m),
                      })),
                  })}
                >
                  Save history
                </button>
              </div>
            ) : null}
          </div>

          <div className="heat-ranges ledger-grains">
            {GRAINS.map((g) => (
              <button
                key={g.id}
                type="button"
                className={g.id === grain ? 'on' : ''}
                disabled={busy}
                onClick={() => { setGrain(g.id); setSelected(null) }}
              >
                {g.label}
              </button>
            ))}
          </div>

          <div className="table-wrap ledger-table-wrap">
            <table className="ledger-table">
              <thead>
                <tr>
                  <th>{grainLabel}</th>
                  <th>Req</th>
                  <th>In</th>
                  <th>Out</th>
                  <th>Rate</th>
                  <th>$</th>
                </tr>
              </thead>
              <tbody>
                {(data?.rows || []).length ? (data.rows || []).map((row) => (
                  <tr
                    key={row.key}
                    className={selected === row.key ? 'sel' : ''}
                    onClick={() => pickRow(row)}
                  >
                    <td>
                      <div className="pid">{row.label}</div>
                      <div className="pname">{sourceLabel(row)}{row.override ? ' override' : ''}</div>
                    </td>
                    <td>{fmtTokens(row.requests)}</td>
                    <td>{fmtTokens(row.prompt_tokens)}</td>
                    <td>{fmtTokens(row.completion_tokens)}</td>
                    <td>
                      {row.in_per_m == null
                        ? 'mixed'
                        : `${fmtRate(row.in_per_m)} / ${fmtRate(row.out_per_m)}`}
                    </td>
                    <td>{data?.priced ? fmtUsd(row.usd) : '—'}</td>
                  </tr>
                )) : (
                  <tr>
                    <td className="muted" colSpan={6}>No sessions in the stored day ledger for this profile.</td>
                  </tr>
                )}
              </tbody>
              {(data?.rows || []).length ? (
                <tfoot>
                  <tr>
                    <td>Total</td>
                    <td>{fmtTokens(mix.requests)}</td>
                    <td>{fmtTokens(mix.prompt)}</td>
                    <td>{fmtTokens(mix.completion)}</td>
                    <td />
                    <td>{data?.priced ? fmtUsd(totals.usd) : '—'}</td>
                  </tr>
                </tfoot>
              ) : null}
            </table>
          </div>

          {sel ? (
            <div className="ledger-block">
              <div className="ledger-block-head">
                <span>Override {sel.label}</span>
              </div>
              <div className="ledger-edit">
                {rateFields(ovIn, ovOut, setOvIn, setOvOut, 'ov')}
                <button
                  type="button"
                  className="btn primary"
                  disabled={busy}
                  onClick={() => run({
                    override: {
                      grain,
                      key: sel.key,
                      in_per_m: numOrZero(ovIn),
                      out_per_m: numOrZero(ovOut),
                    },
                  })}
                >
                  Save {grainLabel.toLowerCase()} override
                </button>
                {sel.override ? (
                  <button
                    type="button"
                    className="btn"
                    disabled={busy}
                    onClick={() => run({ clear_override: { grain, key: sel.key } })}
                  >
                    Clear override
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <p className="ledger-hint">Click a {grainLabel.toLowerCase()} to set an override for that interval.</p>
          )}
        </div>
      </div>
    </div>
  )
}
