export function countsOf(block) {
  const prompt = Number(block?.prompt_tokens) || 0
  const completion = Number(block?.completion_tokens) || 0
  return {
    requests: Number(block?.requests) || 0,
    prompt,
    completion,
    total: prompt + completion,
  }
}

export function shortProfileId(id) {
  const s = String(id || '')
  return s
    .replace(/-eugr$/, '')
    .replace(/-llama$/, '')
    .replace(/-llamacpp$/, '')
}

export function lastNDates(n, end = new Date()) {
  const out = []
  const d = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate()))
  for (let i = n - 1; i >= 0; i -= 1) {
    const x = new Date(d)
    x.setUTCDate(d.getUTCDate() - i)
    out.push(x.toISOString().slice(0, 10))
  }
  return out
}

export function weekdayOf(iso) {
  return new Date(`${iso}T00:00:00Z`).getUTCDay()
}
