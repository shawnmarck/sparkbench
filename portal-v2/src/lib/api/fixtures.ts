import type {
  GpuMetrics,
  HfModelCard,
  HfQueuePayload,
  InferenceStatus,
  InstallStatus,
  InstallTarget,
  InventoryPayload,
  OperatorCheck,
  OperatorGoal,
  OperatorModelCatalog,
  OperatorProposal,
  OperatorStatus,
  OperatorTurn,
  Recipe,
} from './types'

export function fixtureRecipes(): Recipe[] {
  return [
    {
      id: 'nvidia-qwen3-30b-a3b-eugr',
      name: 'qwen3-30b-a3b (eugr)',
      engine: 'eugr',
      inventory_path: 'nvidia/qwen3-30b-a3b',
      tags: ['golden', 'eugr'],
      lifecycle: 'works',
      enabled: true,
      switchable: true,
      tok_s: 72.3,
      context: {
        default: 40960,
        presets: { golden: { label: 'Golden max fit', ctx: 40960, kv: 'fp8' } },
      },
    },
    {
      id: 'opencode-qwen36-250k',
      name: 'Qwen3.6 35B A3B · 250k',
      engine: 'eugr',
      inventory_path: 'nvidia/qwen3.6-35b-a3b',
      tags: ['golden', 'long-ctx'],
      lifecycle: 'works',
      enabled: true,
      switchable: true,
      tok_s: 68.2,
      context: {
        default: 262144,
        presets: { golden: { label: 'Golden max fit', ctx: 262144, kv: 'fp8' } },
      },
    },
    {
      id: 'google-gemma-4-12b-it-llama',
      name: 'Gemma 4 12B (llama)',
      engine: 'llama',
      inventory_path: 'google/gemma-4-12b-it',
      tags: ['golden', 'llama'],
      lifecycle: 'works',
      enabled: true,
      switchable: true,
      tok_s: 41.0,
      context: {
        default: 32768,
        presets: { golden: { label: 'Golden max fit', ctx: 32768, kv: 'q8_0' } },
      },
    },
    {
      id: 'draft-example-eugr',
      name: 'Draft example (eugr)',
      engine: 'eugr',
      inventory_path: 'example/draft-model',
      tags: ['draft'],
      lifecycle: 'draft',
      enabled: false,
      switchable: false,
    },
  ]
}

export function fixtureInventory(): InventoryPayload {
  return {
    generated_at: new Date().toISOString(),
    local_root: '/models',
    shelf_mounted: false,
    count: 3,
    models: [
      {
        id: 'nvidia/qwen3-30b-a3b',
        lab: 'nvidia',
        name: 'qwen3-30b-a3b',
        rel_path: 'nvidia/qwen3-30b-a3b',
        path: '/models/nvidia/qwen3-30b-a3b',
        hf_repo: 'nvidia/Qwen3-30B-A3B',
        hf_url: 'https://huggingface.co/nvidia/Qwen3-30B-A3B',
        status: 'ready',
        size_human: '18.2G',
        size_bytes: 18.2e9,
        is_golden: true,
        golden_profile: 'nvidia-qwen3-30b-a3b-eugr',
        best_bench_tok_s: 72.3,
        engines: ['eugr'],
        architecture: 'Qwen3MoeForCausalLM',
        param_b: 30,
        param_active_b: 3,
        max_context: 40960,
        summary: 'NVIDIA Qwen3 30B-A3B MoE — primary Spark golden path.',
        capabilities: ['tools', 'reasoning'],
        variants: [{ format: 'nvfp4', path: '/models/nvidia/qwen3-30b-a3b/nvfp4' }],
        local: { present: true, path: '/models/nvidia/qwen3-30b-a3b' },
      },
      {
        id: 'nvidia/qwen3.6-35b-a3b',
        lab: 'nvidia',
        name: 'qwen3.6-35b-a3b',
        rel_path: 'nvidia/qwen3.6-35b-a3b',
        path: '/models/nvidia/qwen3.6-35b-a3b',
        hf_repo: 'nvidia/Qwen3.6-35B-A3B',
        hf_url: 'https://huggingface.co/nvidia/Qwen3.6-35B-A3B',
        status: 'missing',
        size_human: '—',
        is_golden: true,
        golden_profile: 'opencode-qwen36-250k',
        best_bench_tok_s: 68.2,
        engines: ['eugr'],
        architecture: 'Qwen3MoeForCausalLM',
        param_b: 35,
        max_context: 262144,
        summary: 'Long-context Qwen3.6 35B A3B.',
        capabilities: ['tools', 'long-ctx'],
        variants: [{ format: 'nvfp4' }],
        local: { present: false },
      },
      {
        id: 'google/gemma-4-12b-it',
        lab: 'google',
        name: 'gemma-4-12b-it',
        rel_path: 'google/gemma-4-12b-it',
        path: '/models/google/gemma-4-12b-it',
        hf_repo: 'google/gemma-4-12b-it',
        hf_url: 'https://huggingface.co/google/gemma-4-12b-it',
        status: 'ready',
        size_human: '7.4G',
        size_bytes: 7.4e9,
        is_golden: true,
        golden_profile: 'google-gemma-4-12b-it-llama',
        best_bench_tok_s: 41.0,
        engines: ['llama'],
        architecture: 'Gemma4ForCausalLM',
        param_b: 12,
        max_context: 262144,
        summary: 'Gemma 4 12B instruct — llama.cpp GGUF path.',
        capabilities: ['tools'],
        variants: [{ format: 'gguf', path: '/models/google/gemma-4-12b-it/gguf' }],
        local: { present: true, path: '/models/google/gemma-4-12b-it' },
      },
      {
        id: 'example/draft-model',
        lab: 'example',
        name: 'draft-model',
        rel_path: 'example/draft-model',
        path: '/models/example/draft-model',
        hf_repo: 'example/draft-model',
        hf_url: 'https://huggingface.co/example/draft-model',
        status: 'ready',
        size_human: '4.1G',
        size_bytes: 4.1e9,
        engines: ['eugr'],
        max_context: 32768,
        architecture: 'LlamaForCausalLM',
        param_b: 8,
        variants: [{ format: 'nvfp4' }],
        local: { present: true },
      },
      {
        id: 'z-lab/qwen3.6-27b',
        lab: 'z-lab',
        name: 'qwen3.6-27b',
        rel_path: 'z-lab/qwen3.6-27b',
        path: '/models/z-lab/qwen3.6-27b',
        status: 'ready',
        size_human: '1.2G',
        size_bytes: 1.2e9,
        engines: ['eugr'],
        model_kind: 'speculative_sidecar',
        requires_target: 'nvidia/qwen3-30b-a3b',
        capabilities: ['dflash', 'speculative'],
        variants: [{ format: 'dflash', path: '/models/z-lab/qwen3.6-27b/dflash' }],
        summary: 'DFlash draft sidecar for nvidia/qwen3-30b-a3b (fixture).',
        local: { present: true },
      },
      {
        id: 'z-lab/qwen3.6-35b-a3b',
        lab: 'z-lab',
        name: 'qwen3.6-35b-a3b',
        rel_path: 'z-lab/qwen3.6-35b-a3b',
        path: '/models/z-lab/qwen3.6-35b-a3b',
        status: 'ready',
        size_human: '0.9G',
        engines: ['eugr'],
        model_kind: 'speculative_sidecar',
        requires_target: 'nvidia/qwen3.6-35b-a3b',
        capabilities: ['dflash', 'speculative'],
        variants: [{ format: 'dflash' }],
        local: { present: true },
      },
    ],
  }
}

export function fixtureGpu(): GpuMetrics {
  const t = Date.now() / 1000
  const memPct = 72 + Math.sin(t / 8) * 3
  const totalMb = 128 * 1024
  const usedMb = Math.round((memPct / 100) * totalMb)
  return {
    gpu_name: 'NVIDIA GB10',
    gpu_util_pct: Math.max(0, Math.round(18 + Math.sin(t / 3) * 12)),
    gpu_available: true,
    cpu_util_pct: Math.max(0, Math.round(14 + Math.cos(t / 4) * 8)),
    memory_used_pct: Math.round(memPct * 10) / 10,
    memory_used_mb: usedMb,
    memory_total_mb: totalMb,
    gpu_temp_c: 42,
    gpu_power_w: 28,
    hermes: { running: false },
    containers: [{ name: 'open-webui', status: 'exited' }],
    inference: {
      up: true,
      model: 'nvidia-qwen3-30b-a3b-eugr',
      engine: 'vllm',
      engines: [
        { id: 'vllm', label: 'vLLM', port: 8000, up: true, model: 'nvidia-qwen3-30b-a3b-eugr' },
        { id: 'llamacpp', label: 'llama.cpp', port: 8081, up: false, model: null },
      ],
      gateway: {
        port: 9000,
        path: '/v1',
        url: 'http://sparky:9000/v1',
        local_url: 'http://127.0.0.1:9000/v1',
        up: true,
        model: 'nvidia-qwen3-30b-a3b-eugr',
      },
    },
  }
}

export function fixtureInferenceStatus(): InferenceStatus {
  return {
    ok: true,
    active: {
      id: 'nvidia-qwen3-30b-a3b-eugr',
      profile: 'nvidia-qwen3-30b-a3b-eugr',
      name: 'qwen3-30b-a3b (eugr)',
      engine: 'eugr',
      tier: 'heavy',
      port: 8000,
      served_name: 'nvidia-qwen3-30b-a3b-eugr',
      inventory_path: 'nvidia/qwen3-30b-a3b',
      tags: ['golden', 'eugr'],
      ready: true,
      starting: false,
      api_url: 'http://sparky:8000/v1',
      tok_s: 72.3,
      context: {
        default: 40960,
        kv_default: 'fp8',
        presets: { golden: { label: 'Golden max fit', ctx: 40960, kv: 'fp8' } },
      },
    },
    engines: {
      eugr: true,
      llamacpp: false,
      ds4: false,
    },
    switch: { running: false },
    loading: { state: 'idle' },
    urls: {
      api: 'http://sparky:8000/v1',
      portal: 'http://sparky/',
    },
    eugr_stack: { update_available: false, message: 'eugr stack up to date' },
  }
}

export function fixtureInstallStatus(): InstallStatus {
  return {
    ok: true,
    install_token_configured: true,
    services: [
      { name: 'portal', healthy: true },
      { name: 'gpu-api', healthy: true },
      { name: 'inference-api', healthy: true },
      { name: 'hf-api', healthy: true },
      { name: 'shelf-api', healthy: true },
      { name: 'gateway', healthy: false, detail: 'not installed' },
      { name: 'install-api', healthy: true },
    ],
    active_job: null,
  }
}

export function fixtureInstallTargets(): InstallTarget[] {
  return [
    { id: 'quickstart', label: 'Quickstart', description: 'Bootstrap + core (portal, APIs, CLI)' },
    { id: 'core', label: 'Core', description: 'Portal, APIs, CLI, model inventory' },
    { id: 'engine', label: 'Engine: eugr', description: 'Install eugr vLLM engine', args: ['eugr'] },
    { id: 'engine', label: 'Engine: llama', description: 'Install llama.cpp engine', args: ['llama'] },
    { id: 'engine', label: 'Engine: ds4', description: 'Install ds4 engine', args: ['ds4'] },
    { id: 'gateway', label: 'Gateway', description: 'OpenAI gateway on :9000' },
    { id: 'openwebui', label: 'Open WebUI', description: 'Chat UI add-on' },
    { id: 'nas', label: 'NAS shelf', description: 'CIFS model shelf mount' },
  ]
}

export function fixtureHfModels(query = ''): HfModelCard[] {
  const all: HfModelCard[] = [
    {
      repo: 'unsloth/Qwen3-30B-A3B-GGUF',
      author: 'unsloth',
      downloads: 120000,
      likes: 420,
      pipeline_tag: 'text-generation',
      tags: ['gguf', 'qwen', 'moe'],
      has_gguf: true,
      has_moe: true,
      has_dense: false,
      hf_url: 'https://huggingface.co/unsloth/Qwen3-30B-A3B-GGUF',
    },
    {
      repo: 'bartowski/Llama-3.3-70B-Instruct-GGUF',
      author: 'bartowski',
      downloads: 89000,
      likes: 310,
      pipeline_tag: 'text-generation',
      tags: ['gguf', 'llama'],
      has_gguf: true,
      has_dense: true,
      hf_url: 'https://huggingface.co/bartowski/Llama-3.3-70B-Instruct-GGUF',
    },
    {
      repo: 'nvidia/Llama-3.1-Nemotron-Nano-8B-v1',
      author: 'nvidia',
      downloads: 45000,
      likes: 180,
      pipeline_tag: 'text-generation',
      tags: ['transformers', 'nvidia'],
      has_dense: true,
      hf_url: 'https://huggingface.co/nvidia/Llama-3.1-Nemotron-Nano-8B-v1',
    },
  ]
  const q = query.trim().toLowerCase()
  if (!q) return all
  return all.filter((m) => m.repo.toLowerCase().includes(q) || m.tags?.some((t) => t.includes(q)))
}

export function fixtureHfQueue(): HfQueuePayload {
  return {
    ok: true,
    download: [
      {
        id: 'dl-1',
        repo: 'unsloth/Qwen3-30B-A3B-GGUF',
        intent: 'gguf_best',
        state: 'queued',
        created_at: new Date().toISOString(),
        plan: { size_human: '18.2 GB', files: ['Qwen3-30B-A3B-Q4_K_M.gguf'] },
      },
    ],
    explore: [
      {
        id: 'ex-1',
        repo: 'bartowski/Llama-3.3-70B-Instruct-GGUF',
        intent: 'gguf_best',
        status: 'saved',
        added_at: new Date().toISOString(),
        variant_label: 'Q4_K_M',
      },
    ],
    active: null,
    can_start: { ok: true },
  }
}

export function fixtureOperatorStatus(state: 'online' | 'offline' = 'online'): OperatorStatus {
  return {
    ok: true,
    available: state === 'online',
    name: 'Spark',
    runtime: 'hermes',
    container_running: state === 'online',
    configured: state === 'online',
    provider: state === 'online' ? 'openrouter' : null,
    model: state === 'online' ? 'deepseek/deepseek-v4-flash' : null,
    goals: 1,
    checks: 1,
    pending_actions: 0,
  }
}

export function fixtureOperatorProposal(state: OperatorProposal['state'] = 'pending'): OperatorProposal {
  return {
    id: 'proposal-fixture',
    turn_id: 'turn-fixture',
    action: 'inference_switch',
    args: { profile: 'opencode-qwen36-250k' },
    title: 'Serve inference profile',
    impact: 'Evicts the active engine and loads another profile.',
    summary: 'Serve inference profile: profile=opencode-qwen36-250k. Evicts the active engine and loads another profile.',
    state,
    source: 'hermes',
    created_at: new Date().toISOString(),
  }
}

export function fixtureOperatorTurn(
  state: OperatorTurn['state'] = 'succeeded',
  withProposal = false,
): OperatorTurn {
  return {
    id: 'turn-fixture',
    state,
    session_id: 'fixture-spark-session',
    message: 'What needs my attention?',
    response: state === 'succeeded'
      ? 'The lab is healthy. Inference is ready and Benchmaster has two jobs queued.'
      : state === 'running'
        ? 'Checking the lab…'
        : null,
    error: state === 'failed' ? 'The out-of-band provider is unavailable.' : null,
    proposals: withProposal ? [fixtureOperatorProposal()] : [],
    created_at: new Date().toISOString(),
  }
}

export function fixtureOperatorGoals(): OperatorGoal[] {
  return [{
    id: 'goal-fixture',
    title: 'Keep golden recipes benchmarked',
    notes: 'Review stale benchmark results weekly.',
    status: 'active',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }]
}

export function fixtureOperatorChecks(): OperatorCheck[] {
  return [{
    id: 'check-fixture',
    name: 'Daily SparkBench health',
    prompt: 'Check service, GPU, inference, shelf, and Benchmaster health. Report only actionable exceptions.',
    schedule: '0 8 * * *',
    enabled: true,
    state: 'scheduled',
  }]
}

export function fixtureOperatorModelCatalog(provider = 'zai'): OperatorModelCatalog {
  const providers = [
    { id: 'zai', name: 'Z.AI', authenticated: true, total_models: 5 },
    { id: 'openrouter', name: 'OpenRouter', authenticated: true, total_models: 4 },
    { id: 'xai-oauth', name: 'xAI Grok OAuth', authenticated: true, total_models: 3 },
    { id: 'anthropic', name: 'Anthropic', authenticated: false, total_models: 0, auth_type: 'api_key' },
    { id: 'custom', name: 'Custom OpenAI-compatible', authenticated: false, total_models: 0, is_user_defined: true },
  ]
  const modelsByProvider: Record<string, string[]> = {
    zai: ['glm-5-turbo', 'glm-5', 'glm-4.7', 'glm-4.7-flash', 'glm-4.5-air'],
    openrouter: ['deepseek/deepseek-v4-flash', 'anthropic/claude-sonnet-4.5', 'openai/gpt-5.2', 'google/gemini-2.5-pro'],
    'xai-oauth': ['grok-4-fast-reasoning', 'grok-4', 'grok-code-fast-1'],
  }
  return {
    provider,
    selected: providers.find((item) => item.id === provider) || null,
    providers,
    models: (modelsByProvider[provider] || []).map((id) => ({ id, name: id })),
    current_provider: 'zai',
    current_model: 'glm-5-turbo',
  }
}
