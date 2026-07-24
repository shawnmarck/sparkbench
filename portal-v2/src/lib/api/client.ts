import type {
  ActivityPayload,
  BenchmasterJob,
  BenchmasterRun,
  BenchmasterStatus,
  GpuMetrics,
  HfModelCard,
  HfQueueItem,
  HfQueuePayload,
  InferenceStatus,
  InstallJob,
  InstallStatus,
  InstallTarget,
  InventoryPayload,
  OperatorCheck,
  OperatorGoal,
  OperatorModelCatalog,
  OperatorProposal,
  OperatorSettings,
  OperatorStatus,
  OperatorTurn,
  Recipe,
  ShelfStatus,
} from './types'

const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === '1'
const ALLOW_FIXTURE_FALLBACK = import.meta.env.VITE_ALLOW_FIXTURE_FALLBACK === '1'

async function apiFetch<T>(path: string, init?: RequestInit, timeoutMs = 12_000): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(path, {
      cache: 'no-store',
      ...init,
      signal: init?.signal || controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init?.headers || {}),
      },
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error(`Request timed out: ${path}`)
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
  const text = await res.text().catch(() => '')
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { error: text }
    }
  }
  if (!res.ok) {
    const message =
      data && typeof data === 'object' && 'error' in data
        ? String(data.error)
        : `${res.status} ${res.statusText}`
    throw new Error(message)
  }
  return data as T
}

export async function getInventory(): Promise<InventoryPayload> {
  if (USE_FIXTURES) {
    const { fixtureInventory } = await import('./fixtures')
    return fixtureInventory()
  }
  try {
    return await apiFetch<InventoryPayload>('/models.json', undefined, 30_000)
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    const { fixtureInventory } = await import('./fixtures')
    return fixtureInventory()
  }
}

export async function getRecipes(): Promise<Recipe[]> {
  if (USE_FIXTURES) {
    const { fixtureRecipes } = await import('./fixtures')
    return fixtureRecipes()
  }
  try {
    const data = await apiFetch<{ recipes: Recipe[] }>('/api/inference/recipes', undefined, 30_000)
    return data.recipes || []
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    const { fixtureRecipes } = await import('./fixtures')
    return fixtureRecipes()
  }
}

export async function getGpu(): Promise<GpuMetrics> {
  if (USE_FIXTURES) {
    const { fixtureGpu } = await import('./fixtures')
    return fixtureGpu()
  }
  try {
    return await apiFetch<GpuMetrics>('/api/gpu')
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    const { fixtureGpu } = await import('./fixtures')
    return fixtureGpu()
  }
}

export async function getInferenceStatus(lite = false): Promise<InferenceStatus> {
  if (USE_FIXTURES) {
    const { fixtureInferenceStatus } = await import('./fixtures')
    return fixtureInferenceStatus()
  }
  try {
    return await apiFetch<InferenceStatus>(`/api/inference/status${lite ? '?lite=1' : ''}`)
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    const { fixtureInferenceStatus } = await import('./fixtures')
    return fixtureInferenceStatus()
  }
}

export async function getShelfStatus(): Promise<ShelfStatus> {
  if (USE_FIXTURES) {
    return { ok: true, mounted: false, path: '/mnt/model-shelf' }
  }
  try {
    const data = await apiFetch<ShelfStatus & {
      shelf_mounted?: boolean
      shelf_path?: string
      local_path?: string
    }>('/api/shelf/status')
    return {
      ...data,
      mounted: data.mounted ?? data.shelf_mounted ?? false,
      path: data.path ?? data.shelf_path,
    }
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    return { ok: false, mounted: false, path: '/mnt/model-shelf' }
  }
}

export async function switchProfile(profile: string, confirmHeavy = false): Promise<unknown> {
  if (USE_FIXTURES) {
    await delay(800)
    return { ok: true, profile }
  }
  return apiFetch('/api/inference/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, confirm: true, confirm_heavy: confirmHeavy }),
  })
}

export async function runBench(): Promise<unknown> {
  if (USE_FIXTURES) {
    await delay(600)
    return { ok: true }
  }
  return apiFetch('/api/inference/bench', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true }),
  })
}

export async function stopInference(): Promise<unknown> {
  if (USE_FIXTURES) {
    await delay(400)
    return { ok: true }
  }
  return apiFetch('/api/inference/down', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true }),
  })
}

export async function searchHf(
  query: string,
  opts?: { limit?: number; filters?: string[] },
): Promise<HfModelCard[]> {
  const limit = opts?.limit ?? 30
  const filter = (opts?.filters || []).join(',')
  const qs = new URLSearchParams({ q: query, limit: String(limit) })
  if (filter) qs.set('filter', filter)
  try {
    const data = await apiFetch<{ models?: HfModelCard[] }>(`/api/hf/search?${qs}`)
    return data.models || []
  } catch (err) {
    if (USE_FIXTURES) {
      const { fixtureHfModels } = await import('./fixtures')
      await delay(200)
      return fixtureHfModels(query)
    }
    throw err
  }
}

export async function trendingHf(opts?: { limit?: number; filters?: string[] }): Promise<HfModelCard[]> {
  const limit = opts?.limit ?? 30
  const filter = (opts?.filters || []).join(',')
  const qs = new URLSearchParams({ limit: String(limit) })
  if (filter) qs.set('filter', filter)
  try {
    const data = await apiFetch<{ models?: HfModelCard[] }>(`/api/hf/trending?${qs}`)
    return data.models || []
  } catch (err) {
    if (USE_FIXTURES) {
      const { fixtureHfModels } = await import('./fixtures')
      await delay(200)
      return fixtureHfModels()
    }
    throw err
  }
}

export async function newHf(opts?: { limit?: number; filters?: string[] }): Promise<HfModelCard[]> {
  const limit = opts?.limit ?? 30
  const filter = (opts?.filters || []).join(',')
  const qs = new URLSearchParams({ limit: String(limit) })
  if (filter) qs.set('filter', filter)
  try {
    const data = await apiFetch<{ models?: HfModelCard[] }>(`/api/hf/new?${qs}`)
    return data.models || []
  } catch (err) {
    if (USE_FIXTURES) {
      const { fixtureHfModels } = await import('./fixtures')
      await delay(200)
      return fixtureHfModels()
    }
    throw err
  }
}

export async function getHfQueue(): Promise<HfQueuePayload> {
  if (USE_FIXTURES) {
    const { fixtureHfQueue } = await import('./fixtures')
    return fixtureHfQueue()
  }
  try {
    return await apiFetch<HfQueuePayload>('/api/hf/queue')
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    const { fixtureHfQueue } = await import('./fixtures')
    return fixtureHfQueue()
  }
}

export async function queueHfDownload(
  repo: string,
  opts?: { intent?: string; files?: string[]; inventory_path?: string },
): Promise<{ ok?: boolean; item?: HfQueueItem }> {
  if (USE_FIXTURES) {
    await delay(400)
    return { ok: true, item: { id: 'fixture-dl-1', repo, intent: opts?.intent || 'gguf_best', state: 'queued' } }
  }
  return apiFetch('/api/hf/queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo,
      action: 'download',
      intent: opts?.intent || 'gguf_best',
      files: opts?.files,
      inventory_path: opts?.inventory_path,
    }),
  })
}

export async function queueHfExplore(
  repo: string,
  opts?: { intent?: string; variant_label?: string },
): Promise<{ ok?: boolean; item?: HfQueueItem }> {
  if (USE_FIXTURES) {
    await delay(300)
    return { ok: true, item: { id: 'fixture-ex-1', repo, intent: opts?.intent || 'gguf_best', status: 'saved' } }
  }
  return apiFetch('/api/hf/queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo,
      action: 'explore',
      intent: opts?.intent || 'gguf_best',
      variant_label: opts?.variant_label,
    }),
  })
}

export async function startHfExploreDownload(itemId: string): Promise<{ ok?: boolean; item?: HfQueueItem }> {
  if (USE_FIXTURES) {
    await delay(400)
    return { ok: true, item: { id: itemId, repo: 'fixture/repo', state: 'queued' } }
  }
  return apiFetch(`/api/hf/queue/${encodeURIComponent(itemId)}/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
}

export async function removeHfQueueItem(
  itemId: string,
  queue: 'download' | 'explore' = 'explore',
): Promise<{ ok?: boolean }> {
  if (USE_FIXTURES) {
    await delay(200)
    return { ok: true }
  }
  return apiFetch(`/api/hf/queue/${encodeURIComponent(itemId)}/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queue }),
  })
}

export async function fetchModel(path: string): Promise<unknown> {
  if (USE_FIXTURES) {
    await delay(500)
    return { ok: true, path }
  }
  return apiFetch('/api/models/fetch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, confirm: true }),
  })
}

export async function shelfPull(path: string): Promise<unknown> {
  return apiFetch('/api/shelf/pull', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, confirm: true }),
  })
}

export async function shelfPush(path: string): Promise<unknown> {
  return apiFetch('/api/shelf/push', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, confirm: true }),
  })
}

export async function shelfRemoveLocal(path: string, force = false): Promise<unknown> {
  return apiFetch('/api/shelf/remove-local', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, confirm: true, force }),
  })
}

export async function promoteRecipe(profile: string): Promise<unknown> {
  return apiFetch('/api/inference/recipes/promote', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, confirm: true }),
  })
}

export async function discardRecipe(profile: string): Promise<unknown> {
  return apiFetch('/api/inference/recipes/discard', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, confirm: true }),
  })
}

export async function markRecipeTesting(profile: string): Promise<unknown> {
  return apiFetch('/api/inference/recipes/testing', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile, confirm: true }),
  })
}

export type RecipeUpdateFields = {
  profile: string
  name?: string
  notes?: string
  tier?: string
  tags?: string[]
  ctx?: number
  kv?: string
  golden_ctx?: number
  golden_kv?: string
  speculative?: false | { method?: string; sidecar_inventory?: string; num_speculative_tokens?: number }
}

export async function updateRecipe(fields: RecipeUpdateFields): Promise<{ ok?: boolean; recipe?: Recipe }> {
  if (USE_FIXTURES) {
    await delay(400)
    return {
      ok: true,
      recipe: {
        id: fields.profile,
        name: fields.name || fields.profile,
        engine: 'eugr',
        lifecycle: 'draft',
        notes: fields.notes,
        tier: fields.tier,
        tags: fields.tags,
        context: {
          default: fields.ctx,
          kv_default: fields.kv,
          presets: {
            golden: {
              label: 'Golden max fit',
              ctx: fields.golden_ctx ?? fields.ctx,
              kv: fields.golden_kv ?? fields.kv,
            },
          },
        },
      },
    }
  }
  return apiFetch('/api/inference/recipes/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fields, confirm: true }),
  })
}

export type ScaffoldOptions = {
  inventory_path: string
  engine?: 'auto' | 'eugr' | 'llamacpp' | 'ds4'
  name?: string
  tier?: 'fast' | 'heavy' | 'experimental'
}

export async function scaffoldRecipe(opts: ScaffoldOptions): Promise<{ ok?: boolean; recipe?: Recipe }> {
  if (USE_FIXTURES) {
    await delay(500)
    return {
      ok: true,
      recipe: {
        id: `${opts.inventory_path.replace(/\//g, '-')}-${opts.engine === 'auto' || !opts.engine ? 'eugr' : opts.engine}`,
        name: opts.name || `${opts.inventory_path.split('/').pop()} (draft)`,
        engine: opts.engine === 'llamacpp' ? 'llama' : opts.engine === 'auto' || !opts.engine ? 'eugr' : opts.engine,
        inventory_path: opts.inventory_path,
        lifecycle: 'draft',
        tags: ['draft'],
        enabled: false,
        switchable: false,
        tier: opts.tier || 'heavy',
      },
    }
  }
  const body: Record<string, unknown> = {
    inventory_path: opts.inventory_path,
    confirm: true,
    auto: !opts.engine || opts.engine === 'auto',
  }
  if (opts.engine && opts.engine !== 'auto') body.engine = opts.engine
  if (opts.name) body.name = opts.name
  if (opts.tier) body.tier = opts.tier
  return apiFetch('/api/inference/recipes/scaffold', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getInstallToken(): string {
  return localStorage.getItem('spark-install-token') || ''
}

export function setInstallToken(token: string) {
  localStorage.setItem('spark-install-token', token)
}

export async function getInstallStatus(): Promise<InstallStatus> {
  if (USE_FIXTURES) {
    const { fixtureInstallStatus } = await import('./fixtures')
    return fixtureInstallStatus()
  }
  try {
    return await apiFetch<InstallStatus>('/api/install/status')
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    const { fixtureInstallStatus } = await import('./fixtures')
    return fixtureInstallStatus()
  }
}

export async function getInstallTargets(): Promise<InstallTarget[]> {
  if (USE_FIXTURES) {
    const { fixtureInstallTargets } = await import('./fixtures')
    return fixtureInstallTargets()
  }
  try {
    const data = await apiFetch<{ targets: InstallTarget[] }>('/api/install/targets')
    return data.targets
  } catch (error) {
    if (!ALLOW_FIXTURE_FALLBACK) throw error
    const { fixtureInstallTargets } = await import('./fixtures')
    return fixtureInstallTargets()
  }
}

export async function startInstallJob(target: string, args: string[] = []): Promise<InstallJob> {
  if (USE_FIXTURES) {
    await delay(300)
    return {
      id: `job-${Date.now()}`,
      target,
      args,
      state: 'running',
      started_at: new Date().toISOString(),
    }
  }
  return apiFetch<InstallJob>('/api/install/jobs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Spark-Install-Token': getInstallToken(),
    },
    body: JSON.stringify({ target, args }),
  })
}

export async function getInstallJob(id: string): Promise<InstallJob> {
  if (USE_FIXTURES) {
    return {
      id,
      target: 'core',
      args: [],
      state: 'succeeded',
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
      exit_code: 0,
    }
  }
  return apiFetch<InstallJob>(`/api/install/jobs/${id}`)
}

export async function getActivity(window: '1h' | '24h' = '1h'): Promise<ActivityPayload> {
  if (USE_FIXTURES) {
    return {
      summary: { active_clients: 2, sessions_1h: 14, sessions_24h: 48, avg_tok_s: 37.4 },
      active: [
        { app: 'Cursor', client_ip: '192.168.1.42', last_seen: Date.now() / 1000 },
        { app: 'Open WebUI', client_ip: '192.168.1.18', last_seen: Date.now() / 1000 - 35 },
      ],
      recent: [
        {
          at: new Date(Date.now() - 90_000).toISOString(),
          app: 'Cursor',
          model: 'qwen3-coder',
          tok_s: 41.2,
          completion_tokens: 684,
        },
      ],
    }
  }
  return apiFetch<ActivityPayload>(`/api/activity?window=${window}`)
}

export async function getBenchmasterStatus(): Promise<BenchmasterStatus> {
  if (USE_FIXTURES) {
    return {
      ok: true,
      control: { mode: 'paused', stop_after_current: false, abort_requested: false },
      current_job: null,
      counts: { queued: 2, gpu_queued: 1, intel_queued: 1, failed: 0 },
      worker_alive: true,
      schedule_open: true,
    }
  }
  return apiFetch<BenchmasterStatus>('/api/benchmaster/status')
}

export async function getBenchmasterQueue(): Promise<{
  items: BenchmasterJob[]
  control: BenchmasterStatus['control']
}> {
  if (USE_FIXTURES) {
    return {
      control: { mode: 'paused' },
      items: [
        {
          id: 'bm-fixture-1',
          type: 'perf_sweep',
          profile_id: 'qwen3-coder-30b-eugr',
          inventory_path: 'qwen/qwen3-coder-30b',
          state: 'queued',
        },
        {
          id: 'bm-fixture-2',
          type: 'intel_eval',
          profile_id: 'qwen3-coder-30b-eugr',
          state: 'queued',
          awaiting: 'remote_worker',
        },
      ],
    }
  }
  return apiFetch('/api/benchmaster/queue')
}

export async function getBenchmasterRuns(): Promise<BenchmasterRun[]> {
  if (USE_FIXTURES) {
    return [
      {
        job_id: 'bm-fixture-done',
        profile_id: 'nemotron-3-nano',
        type: 'perf_sweep',
        ok: true,
        finished_at: new Date(Date.now() - 3_600_000).toISOString(),
      },
    ]
  }
  const data = await apiFetch<{ runs: BenchmasterRun[] }>('/api/benchmaster/runs')
  return data.runs || []
}

export async function controlBenchmaster(
  action: 'pause' | 'resume' | 'stop_after_current' | 'abort_current_requeue_front',
): Promise<unknown> {
  if (USE_FIXTURES) {
    await delay(300)
    return { ok: true, action }
  }
  return apiFetch('/api/benchmaster/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  })
}

export async function addBenchmasterJob(input: {
  type: BenchmasterJob['type']
  profile_id: string
  inventory_path?: string
  note?: string
  front?: boolean
}): Promise<{ ok?: boolean; job?: BenchmasterJob }> {
  if (USE_FIXTURES) {
    await delay(300)
    return {
      ok: true,
      job: {
        id: `bm-fixture-${Date.now()}`,
        type: input.type,
        profile_id: input.profile_id,
        inventory_path: input.inventory_path,
        note: input.note,
        state: 'queued',
      },
    }
  }
  return apiFetch('/api/benchmaster/queue/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export async function removeBenchmasterJob(jobId: string): Promise<unknown> {
  if (USE_FIXTURES) {
    await delay(200)
    return { ok: true }
  }
  return apiFetch('/api/benchmaster/queue/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId }),
  })
}

export async function getOperatorStatus(): Promise<OperatorStatus> {
  if (USE_FIXTURES) {
    const { fixtureOperatorStatus } = await import('./fixtures')
    return fixtureOperatorStatus()
  }
  return apiFetch<OperatorStatus>('/api/operator/status')
}

export async function createOperatorTurn(message: string, sessionId?: string | null): Promise<OperatorTurn> {
  if (USE_FIXTURES) {
    await delay(600)
    const { fixtureOperatorTurn } = await import('./fixtures')
    return { ...fixtureOperatorTurn(), id: `turn-${Date.now()}`, message, session_id: sessionId || 'fixture-spark-session' }
  }
  return apiFetch<OperatorTurn>('/api/operator/turns', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId || undefined }),
  })
}

export async function getOperatorTurn(id: string): Promise<OperatorTurn> {
  return apiFetch<OperatorTurn>(`/api/operator/turns/${encodeURIComponent(id)}`)
}

export function streamOperatorTurn(
  id: string,
  onTurn: (turn: OperatorTurn) => void,
  onError: (error: Error) => void,
): () => void {
  if (USE_FIXTURES || typeof EventSource === 'undefined') return () => undefined
  const source = new EventSource(`/api/operator/turns/${encodeURIComponent(id)}/stream`)
  source.addEventListener('turn', (event) => {
    try {
      const turn = JSON.parse((event as MessageEvent<string>).data) as OperatorTurn
      onTurn(turn)
      if (['succeeded', 'failed', 'cancelled'].includes(turn.state)) source.close()
    } catch {
      onError(new Error('Spark returned an invalid turn update'))
      source.close()
    }
  })
  source.onerror = () => {
    onError(new Error('Spark live updates disconnected'))
    source.close()
  }
  return () => source.close()
}

export async function getOperatorGoals(): Promise<OperatorGoal[]> {
  if (USE_FIXTURES) {
    const { fixtureOperatorGoals } = await import('./fixtures')
    return fixtureOperatorGoals()
  }
  const data = await apiFetch<{ goals: OperatorGoal[] }>('/api/operator/goals')
  return data.goals || []
}

export async function saveOperatorGoal(
  input: Pick<OperatorGoal, 'title' | 'status'> & { notes?: string },
  id?: string,
): Promise<OperatorGoal> {
  if (USE_FIXTURES) {
    await delay(200)
    return {
      id: id || `goal-${Date.now()}`,
      ...input,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
  }
  return apiFetch<OperatorGoal>(`/api/operator/goals${id ? `/${encodeURIComponent(id)}` : ''}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export async function deleteOperatorGoal(id: string): Promise<void> {
  if (USE_FIXTURES) return
  await apiFetch(`/api/operator/goals/${encodeURIComponent(id)}/delete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
}

export async function getOperatorChecks(): Promise<OperatorCheck[]> {
  if (USE_FIXTURES) {
    const { fixtureOperatorChecks } = await import('./fixtures')
    return fixtureOperatorChecks()
  }
  const data = await apiFetch<{ checks: OperatorCheck[] }>('/api/operator/checks')
  return data.checks || []
}

export async function createOperatorProposal(
  action: string,
  args: Record<string, unknown>,
): Promise<OperatorProposal> {
  if (USE_FIXTURES) {
    const { fixtureOperatorProposal } = await import('./fixtures')
    return { ...fixtureOperatorProposal(), id: `proposal-${Date.now()}`, action, args }
  }
  return apiFetch<OperatorProposal>('/api/operator/proposals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, args }),
  })
}

export async function resolveOperatorProposal(
  id: string,
  resolution: 'confirm' | 'cancel',
): Promise<OperatorProposal> {
  if (USE_FIXTURES) {
    await delay(300)
    return {
      id,
      action: 'fixture_action',
      args: {},
      title: 'Fixture action',
      impact: 'Fixture only.',
      summary: 'Fixture action resolved.',
      state: resolution === 'confirm' ? 'succeeded' : 'cancelled',
      created_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
    }
  }
  return apiFetch<OperatorProposal>(
    `/api/operator/proposals/${encodeURIComponent(id)}/${resolution}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Spark-Install-Token': getInstallToken(),
      },
      body: '{}',
    },
    360_000,
  )
}

export async function getOperatorSettings(): Promise<OperatorSettings> {
  if (USE_FIXTURES) {
    return {
      provider: 'openrouter',
      model: 'deepseek/deepseek-v4-flash',
      base_url: 'https://openrouter.ai/api/v1',
      api_key_configured: true,
      oauth_configured: false,
      dashboard_url: `http://${window.location.hostname}:9119/`,
    }
  }
  return apiFetch<OperatorSettings>('/api/operator/settings')
}

export async function getOperatorModelCatalog(
  provider = '',
  refresh = false,
): Promise<OperatorModelCatalog> {
  if (USE_FIXTURES) {
    const { fixtureOperatorModelCatalog } = await import('./fixtures')
    await delay(refresh ? 500 : 100)
    return fixtureOperatorModelCatalog(provider || 'zai')
  }
  const query = new URLSearchParams()
  if (provider) query.set('provider', provider)
  if (refresh) query.set('refresh', '1')
  return apiFetch<OperatorModelCatalog>(
    `/api/operator/models${query.size ? `?${query}` : ''}`,
    undefined,
    refresh ? 190_000 : 100_000,
  )
}

export async function updateOperatorSettings(input: {
  provider: string
  model: string
}): Promise<OperatorSettings> {
  if (USE_FIXTURES) {
    await delay(500)
    return {
      provider: input.provider,
      model: input.model,
      api_key_configured: true,
      oauth_configured: input.provider === 'xai-oauth',
      dashboard_url: `http://${window.location.hostname}:9119/`,
    }
  }
  return apiFetch<OperatorSettings>('/api/operator/settings', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Spark-Install-Token': getInstallToken(),
    },
    body: JSON.stringify({ ...input, confirm: true }),
  }, 120_000)
}

function delay(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}
