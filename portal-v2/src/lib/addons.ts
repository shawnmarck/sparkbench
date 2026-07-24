import type { AddonState, GpuMetrics, InstallStatus } from '@/lib/api/types'

const host = typeof window === 'undefined' ? 'sparky' : window.location.hostname

export const DEFAULT_ADDONS: AddonState[] = [
  {
    id: 'chat',
    name: 'Chat',
    description: 'Open WebUI pointed at the Spark gateway.',
    url: `http://${host}:3000/`,
    status: 'unknown',
    installTarget: 'openwebui',
  },
  {
    id: 'hermes',
    name: 'Spark operator',
    description: 'Hermes-powered portal agent with OOB inference, goals, and daily checks.',
    url: `http://${host}:9119/`,
    status: 'unknown',
    installTarget: 'hermes',
  },
  {
    id: 'netdata',
    name: 'Netdata',
    description: 'Host metrics UI. Usually installed with core.',
    url: `http://${host}:19999/v3/`,
    status: 'unknown',
  },
]

export function resolveAddonStates(gpu: GpuMetrics, install: InstallStatus): AddonState[] {
  const containers = new Set((gpu.containers || []).map((c) => c.name))
  const netdata = install.services.find((s) => s.name === 'netdata')

  return DEFAULT_ADDONS.map((a) => {
    if (a.id === 'chat') {
      const on = [...containers].some((n) => n.includes('open-webui') || n.includes('openwebui'))
      return { ...a, status: on ? 'on' : 'off' }
    }
    if (a.id === 'hermes') {
      return { ...a, status: gpu.hermes?.running ? 'on' : 'off' }
    }
    if (a.id === 'netdata') {
      return { ...a, status: netdata ? (netdata.healthy ? 'on' : 'off') : 'unknown' }
    }
    return a
  })
}

const STORAGE_KEY = 'spark-enabled-addons'

function getAddonPreferences(): Record<string, boolean> {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as unknown
    if (Array.isArray(parsed)) {
      return Object.fromEntries(parsed.map((id) => [String(id), true]))
    }
    return parsed && typeof parsed === 'object' ? parsed as Record<string, boolean> : {}
  } catch {
    return {}
  }
}

/** Add-ons explicitly pinned to navigation. Kept for compatibility with existing callers. */
export function getPreferredAddonIds(): string[] {
  return Object.entries(getAddonPreferences()).filter(([, enabled]) => enabled).map(([id]) => id)
}

export function getAddonNavPreference(id: string): boolean | null {
  const prefs = getAddonPreferences()
  return Object.prototype.hasOwnProperty.call(prefs, id) ? !!prefs[id] : null
}

export function setPreferredAddonEnabled(id: string, enabled: boolean) {
  const prefs = getAddonPreferences()
  prefs[id] = enabled
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs))
}
