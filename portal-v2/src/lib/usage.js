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
  { id: '1y', label: 'Year', days: 365 },
]

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
