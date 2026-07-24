import { useEffect, useState } from 'react'
import { ExternalLink, Loader2 } from 'lucide-react'
import { getGpu, getInstallStatus, startInstallJob } from '@/lib/api/client'
import type { AddonState } from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import {
  DEFAULT_ADDONS,
  getAddonNavPreference,
  resolveAddonStates,
  setPreferredAddonEnabled,
} from '@/lib/addons'

export function AddonsPage() {
  const [addons, setAddons] = useState<AddonState[]>(DEFAULT_ADDONS)
  const [message, setMessage] = useState('')
  const [navPrefs, setNavPrefs] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(DEFAULT_ADDONS.map((addon) => [
      addon.id,
      getAddonNavPreference(addon.id) ?? false,
    ])),
  )
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')

  async function refresh() {
    setError('')
    const [gpuResult, installResult] = await Promise.allSettled([getGpu(), getInstallStatus()])
    if (gpuResult.status === 'fulfilled') {
      const install =
        installResult.status === 'fulfilled'
          ? installResult.value
          : { ok: false, services: [], install_token_configured: false }
      const resolved = resolveAddonStates(gpuResult.value, install)
      setAddons(resolved)
      setNavPrefs(Object.fromEntries(resolved.map((addon) => [
        addon.id,
        getAddonNavPreference(addon.id) ?? addon.status === 'on',
      ])))
    }
    const failures = [gpuResult, installResult]
      .filter((result) => result.status === 'rejected')
      .map((result) => result.status === 'rejected' && result.reason instanceof Error
        ? result.reason.message
        : 'probe unavailable')
    if (failures.length) {
      setError(failures.join(' · '))
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function install(addon: AddonState) {
    if (!addon.installTarget) return
    if (!window.confirm(`Install or update ${addon.name} on this host?`)) return
    setBusy(addon.id)
    setMessage(`Starting ${addon.name} install…`)
    try {
      const job = await startInstallJob(addon.installTarget)
      setMessage(`Install job ${job.id} started for ${addon.installTarget}`)
    } catch (err) {
      setMessage(`Install failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy(null)
    }
  }

  function setNavVisible(addon: AddonState, visible: boolean) {
    setPreferredAddonEnabled(addon.id, visible)
    setNavPrefs((current) => ({ ...current, [addon.id]: visible }))
    window.dispatchEvent(new Event('spark-addons-changed'))
    setMessage(`${addon.name} ${visible ? 'shown in' : 'hidden from'} navigation. Service state was not changed.`)
  }

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Add-ons</h1>
        <p className="max-w-2xl text-muted-foreground">
          Optional services and external tools. Navigation visibility is separate from the live service state.
        </p>
      </header>

      {error && (
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
          <div className="font-medium text-warning">Add-on probes unavailable</div>
          <p className="mt-1 text-muted-foreground">{error}</p>
        </div>
      )}
      {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}

      <div className="grid gap-4 md:grid-cols-3">
        {addons.map((addon) => (
          <Card key={addon.id} className="flex flex-col">
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-base">{addon.name}</CardTitle>
                <Badge variant={addon.status === 'on' ? 'success' : 'secondary'}>{addon.status}</Badge>
              </div>
              <CardDescription>{addon.description}</CardDescription>
            </CardHeader>
            <CardContent className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Show in navigation</span>
              <Switch
                checked={!!navPrefs[addon.id]}
                onCheckedChange={(on) => setNavVisible(addon, on)}
              />
            </CardContent>
            <CardFooter className="mt-auto gap-2">
              {addon.installTarget && addon.status !== 'on' && (
                <Button
                  variant="outline"
                  className="flex-1"
                  disabled={busy === addon.id}
                  onClick={() => void install(addon)}
                >
                  {busy === addon.id && <Loader2 className="animate-spin" />}
                  Install
                </Button>
              )}
              <Button asChild variant="outline" className="flex-1" disabled={addon.status !== 'on'}>
                <a href={addon.status === 'on' ? addon.url : undefined} target="_blank" rel="noreferrer">
                  <ExternalLink className="h-4 w-4" />
                  Open
                </a>
              </Button>
            </CardFooter>
          </Card>
        ))}
      </div>
    </div>
  )
}
