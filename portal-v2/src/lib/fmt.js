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

export function engineLabel(engine) {
  if (engine === 'llamacpp') return 'llama'
  return engine || '—'
}
