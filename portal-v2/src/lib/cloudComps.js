/** Hand-updated cheapest OpenRouter in/out ($ / 1M tokens). Edit when prices move. */

export const CLOUD_COMPS = [
  {
    id: 'qwen3.6-35b-a3b',
    match: ['qwen36-35b-a3b', 'qwen3.6-35b-a3b'],
    slug: 'qwen/qwen3.6-35b-a3b',
    inPerM: 0.05,
    outPerM: 0.70,
    provider: 'Darkbloom',
    asOf: '2026-09-09',
  },
  {
    id: 'ornith-1.5-35b-a3b',
    match: ['ornith-1-5-35b', 'ornith-1.5-35b', 'ornith-ai-ornith'],
    slug: 'qwen/qwen3.6-35b-a3b',
    inPerM: 0.05,
    outPerM: 0.70,
    provider: 'Darkbloom',
    asOf: '2026-09-09',
    proxy: 'Qwen3.6-35B-A3B (closest OpenRouter analog)',
  },
  {
    id: 'qwen3.8-27b',
    match: ['qwen3-8-27b', 'qwen3.8-27b', 'radixark-qwen3'],
    slug: 'qwen/qwen3.8-27b',
    inPerM: 0.15,
    outPerM: 2.00,
    provider: 'Darkbloom',
    asOf: '2026-09-09',
  },
  {
    id: 'qwen3.8-flash-next',
    match: ['qwen3.8-flash-next', 'flash-next', 'mia-ailab-qwen3.8-flash'],
    slug: 'qwen/qwen3.8-flash',
    inPerM: 0.15,
    outPerM: 0.47,
    provider: 'QwenCloud',
    asOf: '2026-09-11',
    proxy: 'Qwen3.8-Flash (QwenCloud production name for Flash-Next)',
  },
  {
    id: 'deepseek-v4-flash',
    match: ['deepseek-v4-flash', '0xsero-deepseek'],
    slug: 'deepseek/deepseek-v4-flash-0731',
    inPerM: 0.05,
    outPerM: 0.16,
    provider: 'OpenInference',
    asOf: '2026-09-09',
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
