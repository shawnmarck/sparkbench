export function fmtPct(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return `${Math.round(Number(n))}`
}

export function fmtTokens(n) {
  const x = Number(n) || 0
  if (x >= 1e9) return `${(x / 1e9).toFixed(2)}B`
  if (x >= 1e6) return `${(x / 1e6).toFixed(1)}M`
  if (x >= 1e3) return `${(x / 1e3).toFixed(1)}k`
  return String(Math.round(x))
}

export function fmtFull(n) {
  return Math.round(Number(n) || 0).toLocaleString('en-US')
}

export function fmtUsd(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const x = Number(n)
  if (x === 0) return '$0'
  if (Math.abs(x) < 10) {
    return `$${x.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }
  return `$${Math.round(x).toLocaleString('en-US')}`
}

export function fmtRate(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  const x = Number(n)
  if (x === 0) return '0'
  if (Math.abs(x) < 0.01) return x.toFixed(3)
  if (Math.abs(x) < 1) return x.toFixed(3)
  return x.toFixed(2)
}

export function fmtRatePair(inn, out) {
  if (inn == null && out == null) return '—'
  return `${fmtRate(inn)} / ${fmtRate(out)}`
}

export function fmtTokS(n) {
  if (n == null || Number.isNaN(Number(n))) return '—'
  return Number(n).toFixed(1)
}

export function fmtCtx(n) {
  const x = Number(n)
  if (!x) return '—'
  if (x >= 1_000_000) return `${(x / 1_000_000).toFixed(x % 1_000_000 ? 1 : 0)}M`
  if (x >= 1000) return `${Math.round(x / 1000)}k`
  return String(x)
}

export function shortName(name, id) {
  const s = String(name || id || 'offline')
  return s.length > 42 ? `${s.slice(0, 40)}…` : s
}

export function sessionModelLabel(row, names) {
  const prof = row?.profile || ''
  const named = names instanceof Map ? names.get(prof) : ''
  if (named) return shortName(named, prof)
  const model = String(row?.model || '')
  const req = String(row?.requested_model || model).toLowerCase()
  if (prof && (req.startsWith('sparky') || model.toLowerCase().startsWith('sparky'))) {
    return shortName(null, prof)
  }
  return shortName(null, model || prof)
}

export function engineLabel(engine) {
  if (engine === 'llamacpp') return 'llama'
  return engine || '—'
}

export function stackLabel(engine) {
  if (engine === 'eugr') return 'eugr / vLLM'
  if (engine === 'ds4') return 'ds4 / vLLM'
  if (engine === 'llamacpp') return 'llama.cpp'
  return engine || '—'
}

export function modalitiesLabel(mm) {
  if (!mm || mm.vision == null) return null
  return mm.vision ? 'text · vision' : 'text'
}

export function visionCapLabel(mm) {
  if (!mm?.vision) return null
  const bits = []
  const px = Number(mm.image_max_pixels)
  if (Number.isFinite(px) && px > 0) bits.push(`${Math.round(Math.sqrt(px))}² px`)
  const img = Number(mm.image_per_request)
  if (Number.isFinite(img) && img > 0) bits.push(`${img} img/req`)
  const vid = Number(mm.video_per_request)
  if (Number.isFinite(vid) && vid > 0) bits.push(`${vid} vid/req`)
  return bits.length ? bits.join(' · ') : null
}

export function benchMethodLabel(method) {
  if (method === 'perfbench-metrics') return 'PBM 4k'
  if (method === 'bench-v2') return 'bench v2'
  return method || 'catalog'
}

export function fmtDur(ms) {
  const n = Number(ms)
  if (!Number.isFinite(n) || n < 0) return '—'
  if (n < 1000) return `${Math.round(n)}ms`
  return `${(n / 1000).toFixed(1)}s`
}

export function fmtEtaS(s) {
  const n = Math.max(0, Math.round(Number(s) || 0))
  if (!Number.isFinite(n)) return '—'
  if (n < 60) return `${n}s`
  const m = Math.floor(n / 60)
  const r = n % 60
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export function sinceLabel(iso) {
  if (!iso) return null
  const ms = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(ms) || ms < 0) return null
  const mins = Math.floor(ms / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 48) return `${hours}h ${mins % 60}m`
  return `${Math.floor(hours / 24)}d`
}
