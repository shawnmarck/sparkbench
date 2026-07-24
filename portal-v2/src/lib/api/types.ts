export type Recipe = {
  id: string
  name: string
  engine: string
  tier?: string
  port?: number
  served_name?: string
  inventory_path?: string
  model_family?: string
  tags?: string[]
  notes?: string
  lifecycle?: string
  enabled?: boolean
  switchable?: boolean
  tok_s?: number
  context?: {
    default?: number
    native?: number
    kv_default?: string
    presets?: Record<string, { label?: string; ctx?: number; kv?: string }>
  }
  speculative?: {
    method?: string
    sidecar_inventory?: string
    num_speculative_tokens?: number
  }
}

export type InventoryModel = {
  id: string
  lab: string
  name: string
  slug?: string
  rel_path?: string
  path?: string
  hf_repo?: string | null
  hf_url?: string | null
  status?: string
  size_human?: string
  size_bytes?: number
  is_golden?: boolean
  golden_profile?: string | null
  best_bench_tok_s?: number | null
  engines?: string[]
  architecture?: string | null
  param_b?: number | null
  param_active_b?: number | null
  max_context?: number | null
  summary?: string | null
  capabilities?: string[]
  variants?: Array<{ format?: string; path?: string }>
  model_kind?: string | null
  requires_target?: string | null
  local?: { present?: boolean; path?: string }
}

export type InventoryPayload = {
  generated_at?: string
  local_root?: string
  shelf_mounted?: boolean
  count?: number
  models: InventoryModel[]
}

export type GpuMetrics = {
  gpu_name?: string
  gpu_util_pct?: number
  gpu_available?: boolean
  cpu_util_pct?: number
  memory_used_pct?: number
  memory_used_mb?: number
  memory_total_mb?: number
  gpu_temp_c?: number
  gpu_power_w?: number
  hermes?: { running?: boolean; url?: string }
  containers?: Array<{ name: string; status?: string }>
  /** Nested inference probe from gpu-api (gateway + engine OpenAI /v1/models). */
  inference?: {
    up?: boolean
    model?: string | null
    engine?: string | null
    engines?: Array<{
      id: string
      label?: string
      port?: number
      up?: boolean
      model?: string | null
    }>
    gateway?: {
      port?: number
      path?: string
      url?: string
      local_url?: string
      up?: boolean
      model?: string | null
    }
  }
  history?: {
    gpu_util_pct?: number[]
    cpu_util_pct?: number[]
    memory_used_pct?: number[]
  }
}

export type EngineState = boolean | { running?: boolean; ready?: boolean }

export type ActiveInference = {
  id?: string
  profile?: string
  name?: string
  engine?: string
  tier?: string
  port?: number
  served_name?: string
  inventory_path?: string
  model_family?: string
  tags?: string[]
  notes?: string
  ready?: boolean
  starting?: boolean
  started_at?: string
  api_url?: string
  log_file?: string
  tok_s?: number
  context?: Recipe['context'] & { effective?: number; kv_effective?: string }
  speculative?: Recipe['speculative']
}

export type InferenceStatus = {
  ok?: boolean
  active?: ActiveInference | null
  loading?: {
    state?: string
    message?: string
    profile?: string
  } | null
  switch?: {
    running?: boolean
    profile?: string
    started_at?: string
  } | null
  engines?: Record<string, EngineState>
  eugr_stack?: {
    update_available?: boolean
    message?: string
    runbook?: string
  }
  urls?: {
    api?: string
    openwebui?: string
    portal?: string
  }
}

export type InstallTarget = {
  id: string
  label: string
  description: string
  args?: string[]
}

export type InstallStatus = {
  ok: boolean
  services: Array<{ name: string; healthy: boolean; detail?: string }>
  install_token_configured: boolean
  active_job?: InstallJob | null
}

export type InstallJob = {
  id: string
  target: string
  args: string[]
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  started_at?: string
  finished_at?: string
  exit_code?: number | null
  log_path?: string
}

export type ShelfStatus = {
  ok?: boolean
  mounted?: boolean
  path?: string
  job?: { running?: boolean; action?: string } | null
}

export type AddonId = 'chat' | 'hermes' | 'netdata'

export type AddonState = {
  id: AddonId
  name: string
  description: string
  url: string
  status: 'off' | 'on' | 'unknown'
  installTarget?: string
}

export type HfModelCard = {
  repo: string
  author?: string | null
  downloads?: number | null
  likes?: number | null
  pipeline_tag?: string | null
  tags?: string[]
  release_date?: string | null
  last_modified?: string | null
  has_gguf?: boolean
  has_nvfp4?: boolean
  has_mtp?: boolean
  has_moe?: boolean
  has_dense?: boolean
  has_vision?: boolean
  has_diffusion?: boolean
  hf_url?: string | null
  spark_warning?: string | null
}

export type HfQueueItem = {
  id: string
  repo: string
  intent?: string
  state?: string
  status?: string
  created_at?: string
  added_at?: string
  finished_at?: string
  note?: string
  variant_label?: string
  inventory_path?: string
  plan?: {
    dest?: string
    files?: string[]
    size_bytes?: number
    size_human?: string
  }
}

export type HfQueuePayload = {
  ok?: boolean
  download: HfQueueItem[]
  explore: HfQueueItem[]
  active?: {
    repo?: string
    state?: string
    progress_pct?: number
    queued_count?: number
  } | null
  can_start?: { ok?: boolean; reason?: string } | boolean
}

export type ActivityClient = {
  client_ip?: string
  app?: string
  last_seen?: number
}

export type ActivitySession = {
  at?: string
  app?: string
  client_ip?: string
  model?: string
  profile?: string
  tok_s?: number
  prompt_tokens?: number
  completion_tokens?: number
  status?: number
}

export type ActivityPayload = {
  summary: {
    active_clients: number
    sessions_1h: number
    sessions_24h: number
    avg_tok_s: number
  }
  active: ActivityClient[]
  recent: ActivitySession[]
}

export type BenchmasterControl = {
  mode: 'paused' | 'running' | 'stopped'
  current_job_id?: string | null
  stop_after_current?: boolean
  abort_requested?: boolean
  schedule?: {
    enabled?: boolean
    start_hour?: number
    end_hour?: number
  }
}

export type BenchmasterPhase = {
  id?: string
  label?: string
  state?: 'pending' | 'running' | 'done' | 'failed'
  detail?: string
  hint?: string
  substeps?: Array<{
    id?: string
    label?: string
    state?: 'pending' | 'running' | 'done' | 'failed'
    detail?: string
  }>
}

export type BenchmasterJob = {
  id: string
  type: 'perf_sweep' | 'ctx_ladder' | 'kv_sweep' | 'golden_workflow' | 'intel_eval'
  profile_id: string
  inventory_path?: string
  quant?: string
  note?: string
  state: 'queued' | 'running' | 'done' | 'failed'
  created_at?: string
  started_at?: string
  finished_at?: string
  error?: string
  awaiting?: string
  claimed_by?: string
  progress?: {
    phase?: string
    step?: number
    total_steps?: number
    message?: string
  }
  live_phases?: BenchmasterPhase[]
}

export type BenchmasterStatus = {
  ok?: boolean
  control: BenchmasterControl
  current_job?: BenchmasterJob | null
  attention_job?: BenchmasterJob | null
  counts?: {
    queued?: number
    running?: number
    done?: number
    failed?: number
    gpu_queued?: number
    intel_queued?: number
  }
  worker_alive?: boolean
  schedule_open?: boolean
  intel_claimable?: boolean
}

export type BenchmasterRun = {
  id?: string
  job_id?: string
  profile_id?: string
  type?: string
  ok?: boolean
  aborted?: boolean
  started_at?: string
  finished_at?: string
  error?: string
}

export type OperatorStatus = {
  ok: boolean
  available: boolean
  name: string
  runtime: 'hermes'
  container?: string
  container_running: boolean
  configured: boolean
  provider?: string | null
  model?: string | null
  goals: number
  checks: number
  pending_actions: number
}

export type OperatorProposal = {
  id: string
  turn_id?: string | null
  action: string
  args: Record<string, unknown>
  title: string
  impact: string
  summary: string
  state: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'expired'
  source?: 'portal' | 'hermes'
  created_at: string
  expires_at?: string
  confirmed_at?: string
  finished_at?: string
  result?: unknown
  error?: string
}

export type OperatorTurn = {
  id: string
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  session_id?: string | null
  message: string
  response?: string | null
  error?: string | null
  proposals: OperatorProposal[]
  created_at: string
  started_at?: string
  finished_at?: string
}

export type OperatorGoal = {
  id: string
  title: string
  notes?: string
  status: 'active' | 'paused' | 'done'
  created_at: string
  updated_at: string
}

export type OperatorCheck = {
  id: string
  name: string
  prompt: string
  schedule?: string
  enabled: boolean
  state?: string
  last_status?: string
  last_run_at?: string
  next_run_at?: string
  goal_id?: string | null
}

export type OperatorSettings = {
  provider?: string | null
  model?: string | null
  base_url?: string | null
  api_key_configured: boolean
  oauth_configured: boolean
  dashboard_url: string
}

export type OperatorModelProvider = {
  id: string
  name: string
  authenticated: boolean
  auth_type?: string | null
  warning?: string | null
  source?: string | null
  total_models: number
  is_user_defined?: boolean
}

export type OperatorProviderModel = {
  id: string
  name: string
  description?: string | null
  context_window?: number | null
  pricing?: unknown
  capabilities?: unknown
}

export type OperatorModelCatalog = {
  provider?: string | null
  selected?: OperatorModelProvider | null
  providers: OperatorModelProvider[]
  models: OperatorProviderModel[]
  current_provider?: string | null
  current_model?: string | null
}
