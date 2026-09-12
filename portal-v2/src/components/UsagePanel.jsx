import { useMemo, useState } from 'react'
import { ActivityCalendar } from './ActivityCalendar.jsx'
import { PriceLedger } from './PriceLedger.jsx'
import { TokenOdometer } from './TokenOdometer.jsx'
import { fmtRatePair, fmtTokens, fmtUsd } from '../lib/fmt.js'
import {
  CACHE_HIT_PRESETS,
  CACHE_READ_FRAC,
  DEFAULT_CACHE_HIT,
  cacheAdjustedUsd,
  countsOf,
} from '../lib/usage.js'

const HIT_STORE = 'spark-v2-cache-hit-v2'

const COLS = [
  { key: 'profile', label: 'Profile' },
  { key: 'req', label: 'Req' },
  { key: 'tokens', label: 'Tokens' },
  { key: 'h24', label: '24h' },
  { key: 'all', label: 'All' },
  { key: 'rate', label: '$/M', title: 'Token-weighted average in / out $/1M from the ledger' },
  { key: 'usd', label: '$', title: 'No-cache ceiling. Every prompt token at full in. Click $ to edit rates.' },
  { key: 'cache', label: 'w/ cache', title: 'If this share of prompt tokens billed at cache-read (~10% of in). Output stays full out.' },
]

function readHit() {
  try {
    const n = Number(window.localStorage.getItem(HIT_STORE))
    if (CACHE_HIT_PRESETS.includes(n)) return n
  } catch { /* ignore */ }
  return DEFAULT_CACHE_HIT
}

function cacheHint(hitPct) {
  const read = Math.round(CACHE_READ_FRAC * 100)
  return `If ${hitPct}% of ↑ tokens billed at cache-read (~${read}% of in). Output at full out. $ is the no-cache ceiling.`
}

function sortVal(p, key, names) {
  const a = countsOf(p.all)
  const c24 = countsOf(p['24h'])
  if (key === 'profile') return String(names.get(p.id) || p.id || '').toLowerCase()
  if (key === 'req') return a.requests <= 2 && a.total > 1e6 ? -1 : a.requests
  if (key === 'tokens' || key === 'all') return a.total
  if (key === 'h24') return c24.total
  if (key === 'rate') return p.priced ? Number(p.in_per_m) || 0 : -1
  if (key === 'usd') return p.priced && p.usd != null ? Number(p.usd) : -1
  if (key === 'cache') return p.priced && p.cacheUsd != null ? Number(p.cacheUsd) : -1
  return 0
}

function cmpRows(a, b, sort, names) {
  if (sort.key === 'usd' || sort.key === 'rate' || sort.key === 'cache') {
    const ap = Boolean(a.priced && (sort.key === 'rate' ? a.in_per_m != null : sort.key === 'cache' ? a.cacheUsd != null : a.usd != null))
    const bp = Boolean(b.priced && (sort.key === 'rate' ? b.in_per_m != null : sort.key === 'cache' ? b.cacheUsd != null : b.usd != null))
    if (ap !== bp) return ap ? -1 : 1
  }
  const av = sortVal(a, sort.key, names)
  const bv = sortVal(b, sort.key, names)
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
  if (n === 0 && sort.key === 'rate') {
    n = (Number(a.out_per_m) || 0) - (Number(b.out_per_m) || 0)
  }
  if (n === 0) n = String(a.id).localeCompare(String(b.id))
  return sort.dir === 'desc' ? -n : n
}

function TokenMix({ prompt, completion }) {
  const total = prompt + completion
  const pin = total ? prompt / total : 0
  return (
    <div className="tokmix">
      <div className="tokmix-bar">
        <i className="in" style={{ flex: pin || 0.0001 }} />
        <i className="out" style={{ flex: (1 - pin) || 0.0001 }} />
      </div>
      <div className="tokmix-n">
        <span>↑{fmtTokens(prompt)}</span>
        <span>↓{fmtTokens(completion)}</span>
      </div>
    </div>
  )
}

function requestLabel(requests, total) {
  if (requests <= 2 && total > 1e6) return { text: '—', title: 'Lifetime backfill; request count unknown' }
  return { text: fmtTokens(requests), title: '' }
}

export function UsagePanel({ live }) {
  const usage = live.activity?.usage
  const summary = live.activity?.summary || {}
  const all = countsOf(usage?.windows?.all)
  const h24 = countsOf(usage?.windows?.['24h'])
  const d30 = countsOf(usage?.windows?.['30d'])
  const [filterId, setFilterId] = useState(null)
  const [ledgerId, setLedgerId] = useState(null)
  const [sort, setSort] = useState({ key: 'h24', dir: 'desc' })
  const [hitPct, setHitPct] = useState(readHit)
  const names = useMemo(() => {
    const m = new Map()
    for (const r of live.recipes || []) m.set(r.id, r.name || r.id)
    return m
  }, [live.recipes])
  const profiles = useMemo(() => {
    const rows = (usage?.profiles || []).map((p) => {
      const a = countsOf(p.all)
      return {
        ...p,
        cacheUsd: p.priced ? cacheAdjustedUsd(p.usd, a.prompt, p.in_per_m, hitPct) : null,
      }
    })
    rows.sort((a, b) => cmpRows(a, b, sort, names))
    return rows
  }, [usage?.profiles, sort, names, hitPct])
  const filterLabel = filterId ? (names.get(filterId) || filterId) : ''
  const ledgerName = ledgerId ? (names.get(ledgerId) || ledgerId) : ''

  function toggleFilter(id) {
    setFilterId((cur) => (cur === id ? null : id))
  }

  function toggleSort(key) {
    setSort((cur) => {
      if (cur.key === key) return { key, dir: cur.dir === 'desc' ? 'asc' : 'desc' }
      return { key, dir: key === 'profile' ? 'asc' : 'desc' }
    })
  }

  const totals = useMemo(() => {
    let prompt = 0
    let completion = 0
    let day24 = 0
    let requests = 0
    let reqKnown = true
    let usd = 0
    let usdKnown = false
    let cacheUsd = 0
    let cacheKnown = false
    let inNum = 0
    let outNum = 0
    let inTok = 0
    let outTok = 0
    for (const p of profiles) {
      const a = countsOf(p.all)
      const c24 = countsOf(p['24h'])
      prompt += a.prompt
      completion += a.completion
      day24 += c24.total
      if (a.requests <= 2 && a.total > 1e6) reqKnown = false
      else requests += a.requests
      if (p.priced && p.usd != null) {
        usd += Number(p.usd) || 0
        usdKnown = true
      }
      if (p.priced && p.cacheUsd != null) {
        cacheUsd += Number(p.cacheUsd) || 0
        cacheKnown = true
      }
      if (p.in_per_m != null && a.prompt) {
        inNum += a.prompt * Number(p.in_per_m)
        inTok += a.prompt
      }
      if (p.out_per_m != null && a.completion) {
        outNum += a.completion * Number(p.out_per_m)
        outTok += a.completion
      }
    }
    return {
      prompt,
      completion,
      total: prompt + completion,
      day24,
      requests,
      reqKnown,
      usd: usdKnown ? usd : null,
      cacheUsd: cacheKnown ? cacheUsd : null,
      in_per_m: inTok ? inNum / inTok : null,
      out_per_m: outTok ? outNum / outTok : null,
    }
  }, [profiles])

  function setHit(n) {
    setHitPct(n)
    try { window.localStorage.setItem(HIT_STORE, String(n)) } catch { /* ignore */ }
  }

  return (
    <section className="usage-hero">
      <div className="hero-row">
        <div className="hero-stat life">
          {usage ? <TokenOdometer value={all.total} /> : <div className="odometer">—</div>}
          <span>Lifetime tokens</span>
        </div>
        <div className="hero-stats">
          <div className="hero-stat">
            <b>{fmtTokens(h24.total)}</b>
            <span>24h</span>
          </div>
          <div className="hero-stat">
            <b>{fmtTokens(d30.total)}</b>
            <span>30D</span>
          </div>
          <div className="hero-stat">
            <b>{summary.sessions_1h ?? '—'}</b>
            <span>Sessions</span>
          </div>
          <div className="hero-stat">
            <b>{summary.active_clients ?? '—'}</b>
            <span>Clients</span>
          </div>
        </div>
      </div>
      <ActivityCalendar days={usage?.days} filterId={filterId} filterLabel={filterLabel} />
      <div className="mix-line">
        <p>
          <b>{fmtTokens(all.prompt)}</b> in · <b>{fmtTokens(all.completion)}</b> out
        </p>
        <div className="heat-ranges cache-hits" title={cacheHint(hitPct)}>
          <span>cache hit</span>
          {CACHE_HIT_PRESETS.map((n) => (
            <button
              key={n}
              type="button"
              className={n === hitPct ? 'on' : ''}
              onClick={() => setHit(n)}
            >
              {n}%
            </button>
          ))}
        </div>
      </div>
      <div className="table-wrap">
        <table className="pick-table">
          <thead>
              <tr>
                {COLS.map((col) => {
                  const on = sort.key === col.key
                  return (
                    <th
                      key={col.key}
                      title={col.title}
                      aria-sort={on ? (sort.dir === 'desc' ? 'descending' : 'ascending') : 'none'}
                    >
                      <button
                        type="button"
                        className={`th-sort${on ? ' on' : ''}`}
                        onClick={() => toggleSort(col.key)}
                      >
                        {col.key === 'cache' ? `w/ ${hitPct}%` : col.label}
                        {on ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : ''}
                      </button>
                    </th>
                  )
                })}
              </tr>
          </thead>
          <tbody>
            {profiles.length ? profiles.map((p) => {
              const a = countsOf(p.all)
              const c24 = countsOf(p['24h'])
              const req = requestLabel(a.requests, a.total)
              const label = names.get(p.id) || p.id
              const on = filterId === p.id
              return (
                <tr
                  key={p.id}
                  className={on ? 'picked' : ''}
                  aria-pressed={on}
                  title={on ? 'Show all models on the calendar' : `Show ${label} on the calendar`}
                  onClick={() => toggleFilter(p.id)}
                >
                  <td title={p.id}>
                    <div className="pid">{label}</div>
                  </td>
                  <td title={req.title}>{req.text}</td>
                  <td><TokenMix prompt={a.prompt} completion={a.completion} /></td>
                  <td>{c24.total ? fmtTokens(c24.total) : '—'}</td>
                  <td>{fmtTokens(a.total)}</td>
                  <td
                    className="rate-cell"
                    title={p.priced ? 'Token-weighted avg from ledger rates' : 'Set rates in the ledger'}
                  >
                    {p.priced ? fmtRatePair(p.in_per_m, p.out_per_m) : '—'}
                  </td>
                  <td>
                    <button
                      type="button"
                      className={`usd-link${p.priced ? '' : ' muted'}`}
                      title={`Open ledger for ${label}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        setLedgerId(p.id)
                      }}
                    >
                      {p.priced ? fmtUsd(p.usd) : 'Set'}
                    </button>
                  </td>
                  <td className="cache-cell" title={p.priced ? cacheHint(hitPct) : 'Set rates in the ledger'}>
                    {p.priced ? fmtUsd(p.cacheUsd) : '—'}
                  </td>
                </tr>
              )
            }) : (
              <tr><td className="muted" colSpan={8}>No usage yet</td></tr>
            )}
          </tbody>
          {profiles.length ? (
            <tfoot>
              <tr>
                <td><div className="pid">Total</div></td>
                <td title={totals.reqKnown ? '' : 'Excludes lifetime backfill; request count unknown'}>
                  {totals.requests ? fmtTokens(totals.requests) : '—'}
                </td>
                <td><TokenMix prompt={totals.prompt} completion={totals.completion} /></td>
                <td>{totals.day24 ? fmtTokens(totals.day24) : '—'}</td>
                <td>{fmtTokens(totals.total)}</td>
                <td
                  className="rate-cell"
                  title="Token-weighted average across priced profiles"
                >
                  {fmtRatePair(totals.in_per_m, totals.out_per_m)}
                </td>
                <td title="Sum of per-profile ledger totals">
                  {fmtUsd(totals.usd)}
                </td>
                <td className="cache-cell" title={cacheHint(hitPct)}>
                  {fmtUsd(totals.cacheUsd)}
                </td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>
      {ledgerId ? (
        <PriceLedger
          profileId={ledgerId}
          profileName={ledgerName}
          onClose={() => setLedgerId(null)}
          onSaved={() => live.refresh?.()}
        />
      ) : null}
    </section>
  )
}
