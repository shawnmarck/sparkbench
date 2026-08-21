async function getJson(path, timeoutMs = 8000) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(path, { signal: ctrl.signal, cache: 'no-store' })
    if (!res.ok) throw new Error(`${path} ${res.status}`)
    return await res.json()
  } finally {
    clearTimeout(t)
  }
}

export function getGpu() {
  return getJson('/api/gpu')
}

export function getInferenceStatus() {
  return getJson('/api/inference/status?lite=1')
}

export function getRecipes() {
  return getJson('/api/inference/recipes', 30_000)
}

export function getActivity() {
  return getJson('/api/activity?window=1h')
}
