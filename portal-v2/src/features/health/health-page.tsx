import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { getGpu, getInferenceStatus, getInstallStatus, getShelfStatus } from '@/lib/api/client'
import type { GpuMetrics, InferenceStatus, InstallStatus, ShelfStatus } from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EndpointGrid } from '@/components/endpoint-status'
import { Progress } from '@/components/ui/progress'

export function HealthPage() {
  const [gpu, setGpu] = useState<GpuMetrics | null>(null)
  const [inference, setInference] = useState<InferenceStatus | null>(null)
  const [install, setInstall] = useState<InstallStatus | null>(null)
  const [shelf, setShelf] = useState<ShelfStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState<string[]>([])

  async function refresh() {
    setLoading(true)
    const results = await Promise.allSettled([
      getGpu(),
      getInferenceStatus(false),
      getInstallStatus(),
      getShelfStatus(),
    ])
    const [g, i, s, sh] = results
    if (g.status === 'fulfilled') setGpu(g.value)
    if (i.status === 'fulfilled') setInference(i.value)
    if (s.status === 'fulfilled') setInstall(s.value)
    if (sh.status === 'fulfilled') setShelf(sh.value)
    setErrors(
      results.flatMap((result, index) =>
        result.status === 'rejected'
          ? [`${['GPU', 'Inference', 'Install agent', 'Shelf'][index]}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}`]
          : [],
      ),
    )
    setLoading(false)
  }

  useEffect(() => {
    void refresh()
    const id = setInterval(() => void refresh(), 10000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">Health</h1>
          <p className="max-w-2xl text-muted-foreground">
            Host vitals, API services, active inference, and engine stack updates.
          </p>
        </div>
        <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </header>

      {errors.length > 0 && (
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-4 text-sm">
          <div className="font-medium text-warning">Some live probes failed</div>
          <ul className="mt-1 list-inside list-disc text-muted-foreground">
            {errors.map((error) => <li key={error}>{error}</li>)}
          </ul>
        </div>
      )}

      {inference?.eugr_stack?.update_available && (
        <Card className="border-warning/40 bg-warning/10">
          <CardHeader>
            <CardTitle className="text-base">Engine update available</CardTitle>
            <CardDescription>{inference.eugr_stack.message || 'eugr stack has updates'}</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {inference.eugr_stack.runbook || 'Run spark engine eugr check on the host, then update from Setup.'}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="CPU" value={gpu?.cpu_util_pct} suffix="%" />
        <MetricCard label="GPU" value={gpu?.gpu_util_pct} suffix="%" />
        <MetricCard label="Memory" value={gpu?.memory_used_pct} suffix="%" />
        <MetricCard label="GPU temp" value={gpu?.gpu_temp_c} suffix="°C" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Inference</CardTitle>
            <CardDescription>Active profile and engines</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">Active</span>
              <span className="font-mono text-xs">{inference?.active?.id || inference?.active?.profile || 'none'}</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground">Ready</span>
              <Badge variant={inference?.active?.ready ? 'success' : 'warning'}>
                {inference?.active?.ready ? 'ready' : 'not ready'}
              </Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(inference?.engines || {}).map(([name, st]) => {
                const up = typeof st === 'boolean' ? st : !!(st.running || st.ready)
                return (
                  <Badge key={name} variant={up ? 'success' : 'secondary'}>
                    {name}: {up ? 'up' : 'down'}
                  </Badge>
                )
              })}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Services</CardTitle>
            <CardDescription>Install agent status probes</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {(install?.services || []).map((svc) => (
              <div key={svc.name} className="flex items-center justify-between gap-2 text-sm">
                <span>{svc.name}</span>
                <div className="flex items-center gap-2">
                  {svc.detail && <span className="text-xs text-muted-foreground">{svc.detail}</span>}
                  <Badge variant={svc.healthy ? 'success' : 'warning'}>
                    {svc.healthy ? 'ok' : 'down'}
                  </Badge>
                </div>
              </div>
            ))}
            <div className="flex items-center justify-between gap-2 text-sm pt-2">
              <span>Shelf mounted</span>
              <Badge variant={shelf?.mounted ? 'success' : 'secondary'}>
                {shelf?.mounted ? 'yes' : 'no'}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">API endpoints</CardTitle>
          <CardDescription>Gateway and engine OpenAI-compatible interfaces</CardDescription>
        </CardHeader>
        <CardContent>
          <EndpointGrid gpu={gpu} inference={inference} />
        </CardContent>
      </Card>
    </div>
  )
}

function MetricCard({ label, value, suffix }: { label: string; value?: number; suffix: string }) {
  const n = typeof value === 'number' ? value : 0
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl">
          {typeof value === 'number' ? value.toFixed(0) : '—'}
          <span className="text-sm font-normal text-muted-foreground">{suffix}</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Progress value={Math.min(100, Math.max(0, n))} />
      </CardContent>
    </Card>
  )
}
