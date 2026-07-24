import type { InventoryModel } from '@/lib/api/types'

export function isSidecarModel(m: InventoryModel) {
  if (m.model_kind === 'speculative_sidecar') return true
  const caps = new Set((m.capabilities || []).map((c) => String(c).toLowerCase()))
  return caps.has('dflash') || caps.has('speculative')
}

/** Find on-disk speculative sidecars that target this base model. */
export function findSidecarsForModel(models: InventoryModel[], inventoryPath: string): InventoryModel[] {
  const path = inventoryPath.trim().replace(/^\/+|\/+$/g, '')
  if (!path) return []
  const slug = path.includes('/') ? path.split('/', 2)[1] : path

  return models.filter((m) => {
    if (!isSidecarModel(m)) return false
    const present = m.local?.present || m.status === 'ready'
    if (!present) return false
    const sid = m.rel_path || m.id
    if (m.requires_target && m.requires_target === path) return true
    // Common Spark layout: z-lab/{same-slug} DFlash for base lab/{slug}
    if (m.lab === 'z-lab' && m.name === slug) return true
    if (sid === `z-lab/${slug}`) return true
    return false
  })
}

export function nativeContext(model?: InventoryModel, recipeNative?: number | null) {
  if (recipeNative != null && recipeNative > 0) return recipeNative
  if (model?.max_context != null && model.max_context > 0) return model.max_context
  return null
}
