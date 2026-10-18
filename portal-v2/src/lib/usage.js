/** OpenRouter cache-read is typically ~10% of listed input. */
export const CACHE_READ_FRAC = 0.1
export const CACHE_HIT_PRESETS = [70, 83, 90]
export const DEFAULT_CACHE_HIT = 83

export function cacheAdjustedUsd(usd, promptTokens, inPerM, hitPct = DEFAULT_CACHE_HIT, cacheReadFrac = CACHE_READ_FRAC) {
  if (usd == null || Number.isNaN(Number(usd))) return null
  if (inPerM == null || Number.isNaN(Number(inPerM))) return null
  const prompt = Number(promptTokens) || 0
  const inn = Number(inPerM) || 0
  const hit = Math.min(1, Math.max(0, (Number(hitPct) || 0) / 100))
  const frac = Math.min(1, Math.max(0, Number(cacheReadFrac) || 0))
  const save = prompt * hit * inn * (1 - frac) / 1e6
  return Math.max(0, Number(usd) - save)
}

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

export function countsForDay(row, filterId) {
  if (!row) return countsOf(null)
  if (filterId) return countsOf(row.profiles?.[filterId])
  return countsOf(row)
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

function utcDay(iso) {
  return new Date(`${iso}T00:00:00Z`)
}

export function addDays(iso, n) {
  const d = utcDay(iso)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

export function weekdaySun(iso) {
  return utcDay(iso).getUTCDay()
}

export const HEAT_RANGES = [
  { id: '31d', label: '31 days', days: 31 },
  { id: '90d', label: '3 months', days: 90 },
  { id: 'ytd', label: 'YTD' },
  { id: '1y', label: 'Year', days: 365 },
]

export function ytdDates(end = new Date()) {
  const year = end.getUTCFullYear()
  const from = `${year}-01-01`
  const last = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate()))
  const to = last.toISOString().slice(0, 10)
  const out = []
  let cur = from
  while (cur <= to) {
    out.push(cur)
    cur = addDays(cur, 1)
  }
  return out
}

export function calendarWeeks(fromIso, toIso) {
  const start = addDays(fromIso, -weekdaySun(fromIso))
  let end = toIso
  while (weekdaySun(end) !== 6) end = addDays(end, 1)
  const weeks = []
  let cur = start
  while (cur <= end) {
    const week = []
    for (let i = 0; i < 7; i += 1) {
      week.push(cur)
      cur = addDays(cur, 1)
    }
    weeks.push(week)
  }
  return weeks
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function monthLabel(iso) {
  return MONTHS[utcDay(iso).getUTCMonth()]
}
