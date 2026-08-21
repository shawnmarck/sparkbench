async function getJson(path, timeoutMs = 8000) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(path, { signal: ctrl.signal, cache: 'no-store' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.error || `${path} ${res.status}`)
    }
    return await res.json()
  } finally {
    clearTimeout(t)
  }
}

async function postJson(path, body, timeoutMs = 15000) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
      signal: ctrl.signal,
      cache: 'no-store',
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.error || `${path} ${res.status}`)
    return data
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

export function getInferenceLogs(lines = 50) {
  return getJson(`/api/inference/logs?lines=${lines}`)
}

export function switchProfile(profile, { confirmHeavy = false, ctx, kv, preset } = {}) {
  const body = {
    profile,
    confirm: true,
    confirm_heavy: confirmHeavy,
  }
  if (ctx != null && ctx !== '') body.ctx = Number(ctx)
  if (kv && kv !== 'auto') body.kv = kv
  if (preset) body.preset = preset
  return postJson('/api/inference/switch', body, 30_000)
}

export function getInferenceContext(profile) {
  return getJson(`/api/inference/context?profile=${encodeURIComponent(profile)}`)
}

export function stopInference() {
  return postJson('/api/inference/down', { confirm: true })
}

export function startBench() {
  return postJson('/api/inference/bench', {})
}

export function getHfStatus() {
  return getJson('/api/hf/status')
}

export function searchHf(q, limit = 24) {
  const qs = new URLSearchParams({ q, limit: String(limit), filter: 'text-generation' })
  return getJson(`/api/hf/search?${qs}`)
}

export function trendingHf(kind = 'trending') {
  return getJson(`/api/hf/${kind}?limit=24&filter=text-generation`)
}

export function getHfQueue() {
  return getJson('/api/hf/queue')
}

export function queueHfExplore(repo) {
  return postJson('/api/hf/queue', { action: 'explore', repo })
}

export function startHfDownload(itemId) {
  return postJson(`/api/hf/queue/${encodeURIComponent(itemId)}/download`, {})
}

export function removeHfQueueItem(itemId, queue) {
  return postJson(`/api/hf/queue/${encodeURIComponent(itemId)}/remove`, { queue })
}

export function getBenchmasterStatus() {
  return getJson('/api/benchmaster/status')
}

export function getBenchmasterQueue() {
  return getJson('/api/benchmaster/queue')
}

export function getBenchmasterRuns() {
  return getJson('/api/benchmaster/runs')
}

export function controlBenchmaster(action) {
  return postJson('/api/benchmaster/control', { action })
}

export function addBenchmasterJob({ type, profileId, inventoryPath }) {
  return postJson('/api/benchmaster/queue/add', {
    type,
    profile_id: profileId,
    inventory_path: inventoryPath || undefined,
  })
}

export function removeBenchmasterJob(jobId) {
  return postJson('/api/benchmaster/queue/remove', { job_id: jobId })
}

export async function getInventory() {
  return getJson('/models.json', 20_000)
}

export function getShelfStatus() {
  return getJson('/api/shelf/status')
}

export function setRecipeLifecycle(kind, profile) {
  const path = kind === 'testing'
    ? '/api/inference/recipes/testing'
    : kind === 'promote'
      ? '/api/inference/recipes/promote'
      : '/api/inference/recipes/discard'
  return postJson(path, { profile, confirm: true })
}

export function getHfModel(repo) {
  return getJson(`/api/hf/model/${repo}`)
}
