import type { InventoryModel, Recipe } from './api/types'
import { fetchModel, getInferenceStatus, queueHfDownload, runBench, switchProfile } from './api/client'

export type GetAndServeOptions = {
  recipe: Recipe
  model?: InventoryModel
  alsoBench: boolean
  onStep: (message: string) => void
}

export type GetAndServeResult =
  | { status: 'download_started'; profile: string }
  | { status: 'ready'; profile: string }

function weightsPresent(model?: InventoryModel) {
  if (!model) return false
  if (model.local?.present) return true
  return model.status === 'ready'
}

export async function getAndServe({
  recipe,
  model,
  alsoBench,
  onStep,
}: GetAndServeOptions): Promise<GetAndServeResult> {
  const profile = recipe.id
  if (!profile) throw new Error('Recipe has no profile id')

  if (!weightsPresent(model)) {
    const inventoryPath = model?.rel_path || recipe.inventory_path
    const repo = model?.hf_repo
    if (!inventoryPath && !repo) throw new Error('No inventory path or Hugging Face repo to download')
    onStep(`Starting weight download for ${inventoryPath || repo}…`)
    try {
      if (!inventoryPath) throw new Error('No inventory path for direct fetch')
      await fetchModel(inventoryPath)
    } catch (error) {
      if (!repo) throw error
      onStep('Host fetch unavailable — adding this model to the download queue…')
      await queueHfDownload(repo)
    }
    onStep('Download started. Serve becomes available after the weights finish downloading.')
    return { status: 'download_started', profile }
  }

  onStep('Weights are on disk')
  onStep(`Switching inference to ${profile}…`)
  await switchProfile(profile)

  onStep('Waiting for the engine to become ready. Large profiles can take several minutes…')
  const deadline = Date.now() + 8 * 60_000
  while (Date.now() < deadline) {
    const status = await getInferenceStatus(true)
    const activeProfile = status.active?.id || status.active?.profile
    if (activeProfile === profile && status.active?.ready) {
      if (alsoBench) {
        onStep('Running golden bench…')
        await runBench()
        onStep('Bench started')
      }
      onStep('Ready on gateway :9000')
      return { status: 'ready', profile }
    }
    await new Promise((r) => setTimeout(r, 2_000))
  }

  throw new Error('The engine did not become ready within 8 minutes. Check Health and the engine logs.')
}
