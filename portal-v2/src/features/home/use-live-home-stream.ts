import { useEffect, useRef, useState } from 'react'
import { getGpu, getInferenceStatus, getInstallStatus, getInventory, getRecipes } from '@/lib/api/client'
import { resolveAddonStates } from '@/lib/addons'
import type {
  AddonState,
  GpuMetrics,
  InferenceStatus,
  InstallStatus,
  InventoryModel,
  Recipe,
} from '@/lib/api/types'

export type LiveHomeSnapshot = {
  gpu: GpuMetrics | null
  inference: InferenceStatus | null
  install: InstallStatus | null
  recipe: Recipe | null
  model: InventoryModel | null
  addons: AddonState[]
  goldenCount: number
  onDisk: number
  /** Wall-clock of last successful live tick (gpu or inference). */
  lastTickAt: number | null
  /** True while at least one poll stream is healthy. */
  live: boolean
  loading: boolean
  error: string | null
}

function findModel(models: InventoryModel[], path?: string | null) {
  if (!path) return null
  return models.find((m) => (m.rel_path || m.id) === path) || null
}

/**
 * Streams Home vitals by polling existing APIs (no WebSocket on SparkBench yet).
 * GPU ~1s, inference lite ~2s, install ~15s. Pauses when the tab is hidden.
 */
export function useLiveHomeStream(): LiveHomeSnapshot {
  const [gpu, setGpu] = useState<GpuMetrics | null>(null)
  const [inference, setInference] = useState<InferenceStatus | null>(null)
  const [install, setInstall] = useState<InstallStatus | null>(null)
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [models, setModels] = useState<InventoryModel[]>([])
  const [addons, setAddons] = useState<AddonState[]>([])
  const [lastTickAt, setLastTickAt] = useState<number | null>(null)
  const [live, setLive] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const recipesRef = useRef(recipes)
  const modelsRef = useRef(models)
  recipesRef.current = recipes
  modelsRef.current = models

  useEffect(() => {
    let cancelled = false
    let gpuTimer: ReturnType<typeof setTimeout> | null = null
    let infTimer: ReturnType<typeof setTimeout> | null = null
    let installTimer: ReturnType<typeof setTimeout> | null = null

    const visible = () => document.visibilityState === 'visible'

    async function tickGpu() {
      if (cancelled) return
      try {
        const g = await getGpu()
        if (cancelled) return
        setGpu(g)
        setLastTickAt(Date.now())
        setLive(true)
        setError(null)
        setInstall((prev) => {
          setAddons(
            resolveAddonStates(
              g,
              prev || { ok: false, services: [], install_token_configured: false },
            ),
          )
          return prev
        })
      } catch (err) {
        if (!cancelled) {
          setLive(false)
          setError(err instanceof Error ? err.message : String(err))
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
          gpuTimer = setTimeout(() => void tickGpu(), visible() ? 1000 : 8000)
        }
      }
    }

    async function tickInference() {
      if (cancelled) return
      try {
        const i = await getInferenceStatus(true)
        if (cancelled) return
        setInference(i)
        setLastTickAt(Date.now())
        setLive(true)
      } catch {
        /* gpu tick owns the error banner */
      } finally {
        if (!cancelled) {
          infTimer = setTimeout(() => void tickInference(), visible() ? 2000 : 10000)
        }
      }
    }

    async function tickInstall() {
      if (cancelled) return
      try {
        const s = await getInstallStatus()
        if (cancelled) return
        setInstall(s)
        setGpu((g) => {
          if (g) setAddons(resolveAddonStates(g, s))
          return g
        })
      } catch {
        /* non-fatal */
      } finally {
        if (!cancelled) {
          installTimer = setTimeout(() => void tickInstall(), visible() ? 15000 : 60000)
        }
      }
    }

    async function loadStatic() {
      try {
        const [r, inv] = await Promise.all([getRecipes(), getInventory()])
        if (cancelled) return
        setRecipes(r)
        setModels(inv.models)
      } catch {
        /* fixtures / offline */
      }
    }

    void loadStatic()
    void tickGpu()
    void tickInference()
    void tickInstall()

    const onVis = () => {
      if (!visible()) return
      // Kick an immediate refresh when returning to the tab.
      if (gpuTimer) clearTimeout(gpuTimer)
      if (infTimer) clearTimeout(infTimer)
      gpuTimer = setTimeout(() => void tickGpu(), 50)
      infTimer = setTimeout(() => void tickInference(), 50)
    }
    document.addEventListener('visibilitychange', onVis)

    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVis)
      if (gpuTimer) clearTimeout(gpuTimer)
      if (infTimer) clearTimeout(infTimer)
      if (installTimer) clearTimeout(installTimer)
    }
  }, [])

  const active = inference?.active
  const profileId = active?.id || active?.profile || null
  const recipe =
    (profileId && recipes.find((r) => r.id === profileId)) ||
    (active
      ? ({
          id: active.id || active.profile || '',
          name: active.name || active.profile || '',
          engine: active.engine || '',
          inventory_path: active.inventory_path,
          tags: active.tags,
          context: active.context,
          speculative: active.speculative,
          tok_s: active.tok_s,
          tier: active.tier,
        } as Recipe)
      : null)

  const model = findModel(models, active?.inventory_path || recipe?.inventory_path)

  return {
    gpu,
    inference,
    install,
    recipe,
    model,
    addons,
    goldenCount: recipes.filter((r) => (r.tags || []).includes('golden') || r.lifecycle === 'works').length,
    onDisk: models.filter((m) => m.local?.present || m.status === 'ready').length,
    lastTickAt,
    live,
    loading,
    error,
  }
}

export function engineIsUp(engines: InferenceStatus['engines'], name: string): boolean {
  if (!engines) return false
  const aliases = name === 'llama' ? ['llama', 'llamacpp'] : [name]
  for (const key of aliases) {
    const st = engines[key]
    if (st == null) continue
    if (typeof st === 'boolean') return st
    return !!(st.running || st.ready)
  }
  return false
}
