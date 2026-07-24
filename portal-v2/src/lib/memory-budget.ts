import type { InventoryModel } from '@/lib/api/types'

/** DGX Spark GB10 unified LPDDR5x pool (decimal GB, matching advertised capacity). */
export const SPARK_POOL_GB = 128

/**
 * Headroom for OS + Grace + desktop/page-cache pressure.
 * On unified memory this sits *outside* the vLLM util claim and still shows in MemUsed.
 */
export const OS_RESERVE_GB = 10

/**
 * CUDA context, graphs, and serving runtime inside the engine process.
 * Memory-creep writeups put torch.compile/CUDA graphs alone near ~13 GB when enabled;
 * SparkBench eugr recipes are closer to ~6–10 GB with typical flags.
 */
export const FRAMEWORK_RESERVE_GB = 8

/**
 * Default `--gpu-memory-utilization` for eugr/ds4 recipes in this repo.
 * vLLM sizes the KV pool to fill this fraction of the unified pool after weights load —
 * that pre-allocation is what you see jump in `free -h`, not “one sequence of KV”.
 */
export const DEFAULT_GPU_MEM_UTIL = 0.85

const GB = 1e9

export type KvDtype = string

export type MemorySegmentId = 'os' | 'weights' | 'draft' | 'kv' | 'framework' | 'free'

export type MemorySegment = {
  id: MemorySegmentId
  label: string
  bytes: number
  note: string
}

export type FitVerdict = 'fit' | 'tight' | 'over'

export type MemoryBudget = {
  poolBytes: number
  usedBytes: number
  freeBytes: number
  overBytes: number
  verdict: FitVerdict
  segments: MemorySegment[]
  /** True when weights came from a rough param estimate, not on-disk size. */
  approximate: boolean
  /** Engine util used for the reservation model (eugr/ds4). */
  gpuMemUtil?: number
}

export type MemoryBudgetInput = {
  model?: InventoryModel | null
  draft?: InventoryModel | null
  ctx: number
  kv: KvDtype
  speculative?: boolean
  streams?: number
  /** Serving engine — eugr/ds4 use util pre-alloc; llama is closer to KV floor. */
  engine?: string | null
  /** Override `--gpu-memory-utilization` (0–1). Defaults to 0.85 for vLLM-family. */
  gpuMemUtil?: number
  poolGb?: number
  osReserveGb?: number
  frameworkGb?: number
}

export function kvDtypeBytes(kv: KvDtype): number {
  const k = (kv || 'auto').toLowerCase().replace(/[_-]/g, '')
  if (k === 'f16' || k === 'fp16' || k === 'bf16') return 2
  if (k === 'fp8' || k === 'e4m3' || k === 'e5m2') return 1
  if (k === 'q80' || k === 'int8' || k === 'i8') return 1
  if (k === 'q40' || k === 'q4' || k === 'int4' || k === 'i4') return 0.5
  // auto → assume fp8 on eugr/Spark golden path
  return 1
}

export function parseSizeHuman(human?: string | null): number | null {
  if (!human) return null
  const m = String(human)
    .trim()
    .match(/^([\d.]+)\s*([KMGTP]?i?B?)$/i)
  if (!m) return null
  const n = Number(m[1])
  if (!Number.isFinite(n)) return null
  const unit = (m[2] || 'B').toUpperCase()
  const mult =
    unit.startsWith('T') ? 1e12 : unit.startsWith('G') ? 1e9 : unit.startsWith('M') ? 1e6 : unit.startsWith('K') ? 1e3 : 1
  return n * mult
}

export function modelWeightBytes(model?: InventoryModel | null): { bytes: number; approximate: boolean } {
  if (!model) return { bytes: 0, approximate: true }
  if (model.size_bytes && model.size_bytes > 0) {
    return { bytes: model.size_bytes, approximate: false }
  }
  const fromHuman = parseSizeHuman(model.size_human)
  if (fromHuman && fromHuman > 0) {
    return { bytes: fromHuman, approximate: false }
  }
  // Fallback: assume NVFP4-ish ~4.5 bits/param when we only know param count.
  const paramsB = model.param_b || model.param_active_b
  if (paramsB && paramsB > 0) {
    return { bytes: paramsB * 1e9 * (4.5 / 8), approximate: true }
  }
  return { bytes: 0, approximate: true }
}

function normalizeEngine(engine?: string | null): 'eugr' | 'llama' | 'ds4' | 'unknown' {
  const e = (engine || '').toLowerCase()
  if (e === 'eugr' || e === 'vllm') return 'eugr'
  if (e === 'ds4') return 'ds4'
  if (e === 'llama' || e === 'llamacpp' || e === 'llama.cpp') return 'llama'
  if (e === 'auto' || !e) return 'eugr' // studio default / most SparkBench recipes
  return 'unknown'
}

/**
 * Theoretical KV for configured ctx × streams (capacity floor).
 * Uses a GQA-ish heuristic when architecture details aren't on the inventory card.
 */
export function estimateKvBytes(opts: {
  ctx: number
  kv: KvDtype
  model?: InventoryModel | null
  streams?: number
}): number {
  const ctx = Math.max(0, opts.ctx || 0)
  if (!ctx) return 0
  // When serving, engines keep headroom for more than one short chat — floor at 2 streams
  // unless the caller passes an explicit concurrency.
  const streams = Math.max(1, opts.streams ?? 2)
  const dtypeBytes = kvDtypeBytes(opts.kv)
  const paramB = opts.model?.param_b || opts.model?.param_active_b || 7
  const layers = Math.max(16, Math.min(80, Math.round(paramB * 1.6)))
  const kvHeads = paramB >= 20 ? 4 : 8
  const headDim = 128
  const perToken = 2 * layers * kvHeads * headDim * dtypeBytes
  return perToken * ctx * streams
}

export function formatGb(bytes: number, digits = 1): string {
  const gb = bytes / GB
  if (gb < 0.05) return '<0.1'
  return gb.toFixed(digits)
}

/**
 * Planned footprint when this recipe is *served*, not the theoretical minimum.
 *
 * For eugr/ds4 (vLLM-family), SparkBench recipes set gpu_memory_utilization ≈ 0.85.
 * After weights load, the engine pre-allocates KV blocks to fill that util budget —
 * so live MemUsed lands near OS + util×128 GB (~116 GB), not “weights + one KV sequence”.
 */
export function estimateMemoryBudget(input: MemoryBudgetInput): MemoryBudget {
  const poolBytes = (input.poolGb ?? SPARK_POOL_GB) * GB
  const osBytes = (input.osReserveGb ?? OS_RESERVE_GB) * GB
  const frameworkBytes = (input.frameworkGb ?? FRAMEWORK_RESERVE_GB) * GB
  const engine = normalizeEngine(input.engine)

  const weights = modelWeightBytes(input.model)
  const draftOn = !!(input.speculative && input.draft)
  const draft = draftOn ? modelWeightBytes(input.draft) : { bytes: 0, approximate: false }

  const kvFloor = estimateKvBytes({
    ctx: input.ctx,
    kv: input.kv,
    model: input.model,
    streams: input.streams,
  })

  const usesUtilPrealloc = engine === 'eugr' || engine === 'ds4' || engine === 'unknown'
  const util = Math.min(0.95, Math.max(0.15, input.gpuMemUtil ?? (usesUtilPrealloc ? DEFAULT_GPU_MEM_UTIL : 0)))

  let kvBytes: number
  let kvNote: string
  let gpuMemUtil: number | undefined

  if (usesUtilPrealloc && util > 0) {
    gpuMemUtil = util
    const engineBudget = poolBytes * util
    // What the engine still has for KV after weights/draft/runtime inside the util claim.
    const kvFromUtil = Math.max(0, engineBudget - weights.bytes - draft.bytes - frameworkBytes)
    kvBytes = Math.max(kvFloor, kvFromUtil)
    kvNote =
      kvBytes > kvFloor
        ? `Engine pre-alloc (~${Math.round(util * 100)}% gpu-memory-utilization): fills the util budget after weights — matches live MemUsed far more than “one sequence of KV”. Ctx ${input.ctx.toLocaleString()} still sets the *usable* cache depth inside that pool.`
        : `KV floor for ctx ${input.ctx.toLocaleString()} · kv ${input.kv || 'auto'} already exceeds the util remainder — this config is over budget.`
  } else {
    // llama.cpp: closer to demand-allocated KV; still pad framework + multi-stream floor.
    kvBytes = kvFloor
    kvNote = `llama.cpp-style estimate: ctx ${input.ctx.toLocaleString()} · kv ${input.kv || 'auto'} × streams (less pre-alloc than vLLM).`
  }

  const usedCore = osBytes + weights.bytes + draft.bytes + kvBytes + frameworkBytes
  const freeBytes = Math.max(0, poolBytes - usedCore)
  const overBytes = Math.max(0, usedCore - poolBytes)
  const plannedUsed = usedCore

  let verdict: FitVerdict = 'fit'
  if (plannedUsed > poolBytes) verdict = 'over'
  else if (plannedUsed > poolBytes * 0.92) verdict = 'tight'

  const segments: MemorySegment[] = [
    {
      id: 'os',
      label: 'OS reserve',
      bytes: osBytes,
      note: `~${OS_RESERVE_GB} GB for OS + Grace + page cache on the unified pool (outside the engine util claim).`,
    },
    {
      id: 'weights',
      label: 'Weights',
      bytes: weights.bytes,
      note: weights.approximate
        ? 'Estimated from parameter count (no on-disk size).'
        : 'On-disk / inventory weight size.',
    },
  ]

  if (draft.bytes > 0) {
    segments.push({
      id: 'draft',
      label: 'Draft',
      bytes: draft.bytes,
      note: 'Speculative decoding sidecar weights.',
    })
  }

  segments.push({
    id: 'kv',
    label: usesUtilPrealloc ? 'KV / engine pool' : 'KV cache',
    bytes: kvBytes,
    note: kvNote,
  })

  segments.push({
    id: 'framework',
    label: 'Framework',
    bytes: frameworkBytes,
    note: `~${FRAMEWORK_RESERVE_GB} GB CUDA + serving runtime (graphs, workers).`,
  })

  if (verdict !== 'over') {
    segments.push({
      id: 'free',
      label: 'Headroom',
      bytes: freeBytes,
      note: 'Remaining unified memory after this serve plan.',
    })
  }

  return {
    poolBytes,
    usedBytes: plannedUsed,
    freeBytes: verdict === 'over' ? 0 : freeBytes,
    overBytes,
    verdict,
    segments,
    approximate: weights.approximate || draft.approximate,
    gpuMemUtil,
  }
}

export function verdictLabel(verdict: FitVerdict): string {
  if (verdict === 'over') return 'Over'
  if (verdict === 'tight') return 'Tight'
  return 'Fit'
}

export function budgetCaption(budget: MemoryBudget): string {
  const used = formatGb(budget.usedBytes)
  const pool = formatGb(budget.poolBytes, 0)
  const utilHint =
    budget.gpuMemUtil != null ? ` · ~${Math.round(budget.gpuMemUtil * 100)}% util` : ''
  if (budget.verdict === 'over') {
    return `~${used} / ${pool} GB · Over by ~${formatGb(budget.overBytes)} GB — lower ctx, KV, or util`
  }
  if (budget.verdict === 'tight') {
    return `~${used} / ${pool} GB · Tight${utilHint} — matches a typical eugr serve`
  }
  return `~${used} / ${pool} GB · Fit${utilHint}`
}
