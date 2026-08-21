import { useEffect, useState } from 'react'
import { getActivity, getGpu, getInferenceStatus, getRecipes } from './api.js'

const empty = { gpu: null, inference: null, activity: null, recipes: [], error: null }

export function useLive(intervalMs = 4000) {
  const [state, setState] = useState(empty)

  useEffect(() => {
    let cancelled = false
    let timer = null
    let recipeAt = 0

    async function tick() {
      try {
        const needRecipes = Date.now() - recipeAt > 30_000
        const [gpu, inference, activity, recipePayload] = await Promise.all([
          getGpu(),
          getInferenceStatus(),
          getActivity(),
          needRecipes ? getRecipes().catch(() => null) : Promise.resolve(null),
        ])
        if (cancelled) return
        setState((prev) => {
          const next = { ...prev, gpu, inference, activity, error: null }
          if (recipePayload) {
            recipeAt = Date.now()
            next.recipes = Array.isArray(recipePayload)
              ? recipePayload
              : recipePayload.recipes || []
          }
          return next
        })
      } catch (err) {
        if (!cancelled) setState((prev) => ({ ...prev, error: err.message || 'offline' }))
      }
      timer = setTimeout(tick, intervalMs)
    }

    tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [intervalMs])

  return state
}
