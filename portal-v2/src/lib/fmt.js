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
