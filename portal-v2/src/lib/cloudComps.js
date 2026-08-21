/** Hand-updated cheapest OpenRouter in/out ($ / 1M tokens). Edit when prices move. */

export const CLOUD_COMPS = [
  {
    id: 'qwen3.6-35b-a3b',
    match: ['qwen36-35b-a3b', 'qwen3.6-35b-a3b'],
    slug: 'qwen/qwen3.6-35b-a3b',
    inPerM: 0.08,
    outPerM: 0.75,
    provider: 'Darkbloom',
    asOf: '2026-08-21',
  },
  {
    id: 'ornith-1.5-35b-a3b',
    match: ['ornith-1-5-35b', 'ornith-1.5-35b', 'ornith-ai-ornith'],
    slug: 'qwen/qwen3.6-35b-a3b',
    inPerM: 0.08,
    outPerM: 0.75,
    provider: 'Darkbloom',
    asOf: '2026-08-21',
    proxy: 'Qwen3.6-35B-A3B (closest OpenRouter analog)',
  },
  {
    id: 'qwen3.8-27b',
    match: ['qwen3-8-27b', 'qwen3.8-27b', 'radixark-qwen3'],
    slug: 'qwen/qwen3.8-27b',
    inPerM: 0.40,
    outPerM: 3.00,
    provider: 'Chutes',
    asOf: '2026-08-21',
  },
]

export function matchComp(profileId) {
  const id = String(profileId || '').toLowerCase()
  if (!id) return null
  return CLOUD_COMPS.find((c) => c.match.some((m) => id.includes(m))) || null
}

export function estCloudUsd(promptTokens, completionTokens, comp) {
  if (!comp) return null
  const pin = Number(promptTokens) || 0
  const cout = Number(completionTokens) || 0
  if (pin + cout <= 0) return 0
  return (pin * comp.inPerM + cout * comp.outPerM) / 1e6
}

export function compTitle(comp) {
  if (!comp) return 'No OpenRouter analog on file'
  const rate = `$${comp.inPerM} / $${comp.outPerM} per M · ${comp.provider} · ${comp.asOf}`
  if (comp.proxy) return `${comp.proxy} · ${comp.slug} · ${rate}`
  return `${comp.slug} · ${rate}`
}
