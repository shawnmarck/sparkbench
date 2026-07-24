import { useEffect, useState } from 'react'
import {
  getInstallStatus,
  getInstallJob,
  getInstallTargets,
  getInstallToken,
  setInstallToken,
  startInstallJob,
} from '@/lib/api/client'
import type { InstallJob, InstallStatus, InstallTarget } from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'

export function SetupPage() {
  const [status, setStatus] = useState<InstallStatus | null>(null)
  const [targets, setTargets] = useState<InstallTarget[]>([])
  const [token, setToken] = useState(getInstallToken())
  const [log, setLog] = useState<string[]>([
    'First bootstrap still needs one CLI command on the Spark host:',
    '  curl -fsSL …/scripts/bootstrap-sparkbench.sh | sudo bash',
    'After that, use this page to install engines, gateway, and add-ons.',
  ])
  const [busy, setBusy] = useState(false)
  const [activeJob, setActiveJob] = useState<InstallJob | null>(null)
  const [error, setError] = useState('')

  async function refresh() {
    setError('')
    try {
      const [s, t] = await Promise.all([getInstallStatus(), getInstallTargets()])
      setStatus(s)
      setTargets(t)
      if (s.active_job) setActiveJob(s.active_job)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  useEffect(() => {
    const id = activeJob?.id
    if (!id || !['queued', 'running'].includes(activeJob.state)) return
    const timer = window.setInterval(async () => {
      try {
        const next = await getInstallJob(id)
        setActiveJob(next)
        if (!['queued', 'running'].includes(next.state)) {
          setLog((prev) => [
            ...prev,
            `Job ${next.id} ${next.state}${next.exit_code != null ? ` (exit ${next.exit_code})` : ''}`,
          ])
          setBusy(false)
          void refresh()
        }
      } catch (err) {
        setLog((prev) => [...prev, `Job poll failed: ${err instanceof Error ? err.message : String(err)}`])
        setActiveJob((current) => current ? { ...current, state: 'failed' } : current)
        setBusy(false)
      }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [activeJob?.id, activeJob?.state])

  async function runTarget(target: InstallTarget) {
    const caution = target.id === 'core'
      ? 'Core install can restart APIs and rewrite nginx. Do not run it while this box is actively serving. Continue?'
      : `Run “${target.label}” on this host? The target may restart its service.`
    if (!window.confirm(caution)) return
    setBusy(true)
    setInstallToken(token)
    setLog((prev) => [...prev, `Starting ${target.label}…`])
    try {
      const job = await startInstallJob(target.id, target.args || [])
      setActiveJob(job)
      setLog((prev) => [
        ...prev,
        `Job ${job.id} → ${job.state}`,
        ...(import.meta.env.VITE_USE_FIXTURES === '1'
          ? ['(fixtures) Simulated install completed.']
          : ['Tracking job status. Detailed log is available from the install agent stream.']),
      ])
      if (!['queued', 'running'].includes(job.state)) {
        setBusy(false)
        await refresh()
      }
    } catch (err) {
      setLog((prev) => [...prev, `Error: ${err instanceof Error ? err.message : String(err)}`])
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Setup</h1>
        <p className="max-w-2xl text-muted-foreground">
          Install and update SparkBench via the privileged install agent. Mutations require the host install token.
        </p>
      </header>

      {error && (
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
          <div className="font-medium text-warning">Install agent unavailable</div>
          <p className="mt-1 text-muted-foreground">{error}</p>
        </div>
      )}

      {activeJob && ['queued', 'running'].includes(activeJob.state) && (
        <div className="flex items-center justify-between gap-4 rounded-xl border border-primary/30 bg-primary/5 p-4 text-sm">
          <div>
            <div className="font-medium">Running {activeJob.target}</div>
            <div className="font-mono text-xs text-muted-foreground">{activeJob.id} · {activeJob.state}</div>
          </div>
          <Badge variant="warning">{activeJob.state}</Badge>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Install token</CardTitle>
          <CardDescription>
            Stored in this browser only. Read from <code className="text-xs">/etc/spark/install-token</code> on the host.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row">
          <div className="flex-1 space-y-2">
            <Label htmlFor="token">Token</Label>
            <Input
              id="token"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="paste install token"
            />
          </div>
          <Button
            className="sm:self-end"
            variant="outline"
            onClick={() => {
              setInstallToken(token)
              setLog((prev) => [...prev, 'Token saved in localStorage'])
            }}
          >
            Save
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Service health</CardTitle>
            <CardDescription>
              Token configured: {status?.install_token_configured ? 'yes' : 'no / unknown'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(status?.services || []).map((svc) => (
              <div key={svc.name} className="flex items-center justify-between text-sm">
                <span>{svc.name}</span>
                <Badge variant={svc.healthy ? 'success' : 'warning'}>{svc.healthy ? 'ok' : 'down'}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Install log</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-56 rounded-md border bg-muted/30 p-3 font-mono text-xs">
              {log.map((line, i) => (
                <div key={`${i}-${line}`}>{line}</div>
              ))}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {targets.map((target, idx) => (
          <Card key={`${target.id}-${idx}`}>
            <CardHeader>
              <CardTitle className="text-base">{target.label}</CardTitle>
              <CardDescription>{target.description}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button disabled={busy || !!error} onClick={() => void runTarget(target)}>
                Run target
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
