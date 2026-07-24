import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  Activity,
  ArrowRight,
  Bot,
  CircleStop,
  HeartPulse,
  Radio,
  Sparkles,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { estimateMemoryBudget, formatGb } from '@/lib/memory-budget'
import { cn } from '@/lib/utils'
import { useLiveHomeStream } from '@/features/home/use-live-home-stream'
import { getActivity, getBenchmasterStatus, stopInference } from '@/lib/api/client'
import type {
  ActiveInference,
  ActivityPayload,
  BenchmasterStatus,
  GpuMetrics,
} from '@/lib/api/types'

export function HomePage() {
  const {
    gpu,
    inference,
    install,
    recipe,
    model,
    live,
    loading,
    error,
  } = useLiveHomeStream()
  const [activity, setActivity] = useState<ActivityPayload | null>(null)
  const [benchmaster, setBenchmaster] = useState<BenchmasterStatus | null>(null)
  const [stopping, setStopping] = useState(false)
  const [actionMessage, setActionMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    async function refreshOperations() {
      const [nextActivity, nextBenchmaster] = await Promise.allSettled([
        getActivity('1h'),
        getBenchmasterStatus(),
      ])
      if (cancelled) return
      if (nextActivity.status === 'fulfilled') setActivity(nextActivity.value)
      if (nextBenchmaster.status === 'fulfilled') setBenchmaster(nextBenchmaster.value)
    }
    void refreshOperations()
    const id = window.setInterval(() => void refreshOperations(), 10_000)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [])

  const coreDown = (install?.services || []).filter((s) => !s.healthy && s.name !== 'gateway').length
  const needsSetup = coreDown > 0
  const active = inference?.active
  const switching = !!inference?.switch?.running
  const profileId = active?.id || active?.profile
  const recentGateway = activity?.recent?.length || 0
  const gatewayBusy = !!activity?.summary.active_clients || recentGateway > 0
  const benchActive = benchmaster?.current_job || benchmaster?.attention_job
  const benchQueued =
    benchmaster?.counts?.queued ||
    (benchmaster?.counts?.gpu_queued || 0) + (benchmaster?.counts?.intel_queued || 0)
  const benchBusy = !!benchActive || benchQueued > 0 || benchmaster?.control?.mode === 'running'

  async function stopActiveInference() {
    if (!window.confirm('Stop the active inference engine and release the GPU?')) return
    setStopping(true)
    setActionMessage('Stopping inference…')
    try {
      await stopInference()
      setActionMessage('Inference stop requested')
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setStopping(false)
    }
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
            <Sparkles className="h-3.5 w-3.5" />
            Command center
          </div>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Your model lab, at a glance.</h1>
          <p className="max-w-2xl text-muted-foreground">
            Serve, monitor, and benchmark models without dropping into an SSH session.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <LiveBadge live={live} error={error} />
          <Button asChild variant="outline" size="sm">
            <Link to="/operator">
              <Bot className="h-4 w-4" />
              Ask Spark
            </Link>
          </Button>
          {profileId ? (
            <Button variant="outline" size="sm" disabled={stopping} onClick={() => void stopActiveInference()}>
              <CircleStop className="h-4 w-4" />
              {stopping ? 'Stopping…' : 'Stop model'}
            </Button>
          ) : (
            <Button asChild size="sm">
              <Link to="/catalog">
                Serve a model
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          )}
        </div>
      </header>

      {actionMessage && (
        <div role="status" className="rounded-lg border bg-card px-4 py-3 text-sm">
          {actionMessage}
        </div>
      )}

      {needsSetup && (
        <Card className="border-warning/40 bg-warning/10">
          <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
            <div>
              <CardTitle className="text-base">Setup incomplete</CardTitle>
              <CardDescription>
                {coreDown} core service{coreDown === 1 ? '' : 's'} unreachable. Finish install before serving
                models.
              </CardDescription>
            </div>
            <Button asChild>
              <Link to="/setup">
                Open Setup
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </CardHeader>
        </Card>
      )}

      {switching && (
        <Card className="border-primary/30 bg-primary/5">
          <CardContent className="flex items-center gap-3 py-4 text-sm">
            <Activity className="h-4 w-4 animate-pulse text-primary" />
            Switching to{' '}
            <span className="font-mono">{inference?.switch?.profile || '…'}</span>
            {inference?.loading?.message ? ` — ${inference.loading.message}` : '…'}
          </CardContent>
        </Card>
      )}

      <Card className={cn(profileId && 'border-primary/30 shadow-[0_0_40px_var(--glow-soft)]')}>
        <CardHeader>
          <CardTitle className="text-base">Runtime</CardTitle>
          <CardDescription>Serving state, recipe, and unified-memory pressure</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 xl:grid-cols-[1.35fr_0.9fr] xl:divide-x">
            <section className="space-y-5 xl:pr-6">
              <div>
                <h2 className="text-sm font-medium">Now serving</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">Active stack · engine · model · recipe</p>
              </div>
              {loading && !active ? (
                <p className="text-sm text-muted-foreground">Connecting to live status…</p>
              ) : profileId ? (
                <ServingPanel active={active!} recipeName={recipe?.name} modelLabel={modelLabel(active, model?.lab)} />
              ) : (
                <div className="space-y-4">
                  <p className="text-sm text-muted-foreground">GPU available. Nothing is serving.</p>
                  <Button asChild>
                    <Link to="/catalog">
                      Browse golden recipes
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </Button>
                </div>
              )}
            </section>

            <section className="space-y-4 xl:pl-6">
              <div>
                <h2 className="text-sm font-medium">Unified memory</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">Live pool with planned recipe overlay</p>
              </div>
              <LiveMemoryBreakdown gpu={gpu} active={active} model={model} />
              <div className="grid grid-cols-3 gap-3 text-center">
                <MiniVital label="GPU" value={gpu?.gpu_util_pct} suffix="%" />
                <MiniVital label="CPU" value={gpu?.cpu_util_pct} suffix="%" />
                <MiniVital label="Temp" value={gpu?.gpu_temp_c} suffix="°C" />
              </div>
              <Button asChild variant="ghost" size="sm" className="px-0">
                <Link to="/health">
                  Full health
                  <HeartPulse className="h-4 w-4" />
                </Link>
              </Button>
            </section>
          </div>
        </CardContent>
      </Card>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium">Active operations</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">Traffic and automated lab work that need attention now</p>
          </div>
        </div>
        {gatewayBusy || benchBusy ? (
          <div className={cn('grid gap-4', gatewayBusy && benchBusy && 'xl:grid-cols-[1.25fr_0.75fr]')}>
            {gatewayBusy && <ActivityPanel activity={activity} />}
            {benchBusy && <BenchmasterPanel status={benchmaster} />}
          </div>
        ) : (
          <IdleOperations activity={activity} status={benchmaster} />
        )}
      </section>
    </div>
  )
}

function modelLabel(active: ActiveInference | null | undefined, lab?: string) {
  const path = active?.inventory_path
  if (!path) return active?.served_name || active?.model_family || '—'
  if (lab) return `${lab}/${path.split('/').pop()}`
  return path
}

function ServingPanel({
  active,
  recipeName,
  modelLabel: modelText,
}: {
  active: ActiveInference
  recipeName?: string
  modelLabel: string
}) {
  const engine = active.engine || '—'
  const ready = !!active.ready
  const starting = !!active.starting
  const ctx =
    active.context?.effective ??
    active.context?.default ??
    active.context?.presets?.golden?.ctx
  const kv = active.context?.kv_effective ?? active.context?.kv_default ?? active.context?.presets?.golden?.kv

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={ready ? 'success' : starting ? 'warning' : 'secondary'}>
          {ready ? 'ready' : starting ? 'starting' : 'not ready'}
        </Badge>
        <Badge variant="secondary">{engine}</Badge>
        {active.tier && <Badge variant="outline">{active.tier}</Badge>}
        {active.tok_s != null && <Badge variant="outline">{active.tok_s} tok/s</Badge>}
      </div>

      <dl className="grid gap-3 sm:grid-cols-2 text-sm">
        <Fact label="Recipe" value={recipeName || active.name || active.id || active.profile || '—'} mono />
        <Fact label="Profile id" value={active.id || active.profile || '—'} mono />
        <Fact label="Model" value={modelText} mono />
        <Fact label="Served name" value={active.served_name || '—'} mono />
        <Fact
          label="Context / KV"
          value={
            ctx != null || kv
              ? `${ctx != null ? ctx.toLocaleString() : '—'} · ${kv || '—'}`
              : '—'
          }
        />
        <Fact label="Engine API" value={active.api_url || '—'} mono />
      </dl>

      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm">
          <Link to={`/recipes?recipe=${encodeURIComponent(active.id || active.profile || '')}`}>
            Manage recipe
          </Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link to="/catalog">Switch from catalog</Link>
        </Button>
      </div>
    </div>
  )
}

function Fact({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0 space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('truncate', mono && 'font-mono text-xs')}>{value}</dd>
    </div>
  )
}

function LiveMemoryBreakdown({
  gpu,
  active,
  model,
}: {
  gpu: GpuMetrics | null
  active: ActiveInference | null | undefined
  model: import('@/lib/api/types').InventoryModel | null
}) {
  const totalMb = gpu?.memory_total_mb ?? 128 * 1024
  const usedMb = gpu?.memory_used_mb ?? Math.round(((gpu?.memory_used_pct || 0) / 100) * totalMb)
  const freeMb = Math.max(0, totalMb - usedMb)
  const usedPct = totalMb ? (usedMb / totalMb) * 100 : 0

  const plan =
    active && model
      ? estimateMemoryBudget({
          model,
          ctx: active.context?.effective ?? active.context?.default ?? 32768,
          kv: active.context?.kv_effective ?? active.context?.kv_default ?? 'fp8',
          speculative: !!active.speculative,
          engine: active.engine,
          draft: null,
        })
      : null

  const weightBytes = plan ? plan.segments.find((s) => s.id === 'weights')?.bytes || 0 : 0
  // gpu-api reports MiB (meminfo kB / 1024)
  const weightsMiB = weightBytes / (1024 * 1024)
  const restMiB = Math.max(0, usedMb - weightsMiB)

  return (
    <div className="space-y-3">
      <div className="flex h-4 w-full overflow-hidden rounded-md border bg-muted/40">
        {weightsMiB > 0 && (
          <div
            className="h-full bg-primary transition-[width] duration-500 ease-out"
            style={{ width: `${Math.min(100, (weightsMiB / totalMb) * 100)}%` }}
            title={`Weights ~${formatGb(weightBytes)} GB`}
          />
        )}
        <div
          className="h-full bg-[var(--warning)]/80 transition-[width] duration-500 ease-out"
          style={{
            width: `${Math.min(100 - (weightsMiB / totalMb) * 100, (restMiB / totalMb) * 100)}%`,
          }}
          title={`Runtime + KV + OS ~${(restMiB / 1024).toFixed(1)} GiB`}
        />
        <div
          className="h-full bg-muted transition-[width] duration-500 ease-out"
          style={{ width: `${Math.max(0, (freeMb / totalMb) * 100)}%` }}
          title={`Available ~${(freeMb / 1024).toFixed(1)} GiB`}
        />
      </div>
      <div className="flex justify-between text-sm">
        <span className="text-muted-foreground">
          {(usedMb / 1024).toFixed(1)} / {(totalMb / 1024).toFixed(0)} GiB used
        </span>
        <span className="tabular-nums">{usedPct.toFixed(0)}%</span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {weightsMiB > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm bg-primary" />
            Weights {(weightsMiB / 1024).toFixed(1)}
          </span>
        )}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-[var(--warning)]/80" />
          Live rest {(restMiB / 1024).toFixed(1)}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-muted border" />
          Free {(freeMb / 1024).toFixed(1)}
        </span>
      </div>
      <Progress value={Math.min(100, usedPct)} className="h-1.5" />
    </div>
  )
}

function ActivityPanel({ activity }: { activity: ActivityPayload | null }) {
  const recent = activity?.recent?.slice(0, 4) || []
  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">Gateway activity</CardTitle>
          <CardDescription>Clients using the model in the last hour</CardDescription>
        </div>
        <Badge variant={activity?.summary.active_clients ? 'success' : 'secondary'}>
          {activity?.summary.active_clients || 0} active
        </Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-2">
          <MiniVital label="Sessions" value={activity?.summary.sessions_1h} suffix="" />
          <MiniVital label="Avg speed" value={activity?.summary.avg_tok_s} suffix=" tok/s" />
          <MiniVital
            label="Recent tok"
            value={recent.reduce(
              (sum, row) => sum + (row.prompt_tokens || 0) + (row.completion_tokens || 0),
              0,
            )}
            suffix=""
          />
        </div>
        {recent.length ? (
          <div className="divide-y rounded-lg border">
            {recent.map((row, index) => (
              <div key={`${row.at}-${index}`} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-semibold">
                  {(row.app || '?').slice(0, 1).toUpperCase()}
                  <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border border-card bg-success" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{row.app || 'Unknown client'}</div>
                  <div className="truncate text-xs text-muted-foreground">{row.model || row.profile || 'gateway request'}</div>
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  {row.tok_s != null && <div className="font-medium text-foreground">{row.tok_s.toFixed(1)} tok/s</div>}
                  <div>{relativeTime(row.at)}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            No recent gateway sessions.
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function BenchmasterPanel({ status }: { status: BenchmasterStatus | null }) {
  const active = status?.current_job || status?.attention_job
  const mode = status?.control?.mode || 'offline'
  const queued = status?.counts?.queued || (status?.counts?.gpu_queued || 0) + (status?.counts?.intel_queued || 0)
  const step = active?.progress?.step || 0
  const total = active?.progress?.total_steps || 0
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">Benchmaster</CardTitle>
            <CardDescription>Automated lab queue</CardDescription>
          </div>
          <Badge variant={mode === 'running' ? 'success' : mode === 'offline' ? 'warning' : 'secondary'}>{mode}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {active ? (
          <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
            <div>
              <div className="truncate font-medium">{active.profile_id}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{active.progress?.message || active.type}</div>
            </div>
            <Progress value={total ? (step / total) * 100 : 8} />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>{active.state}</span>
              <span>{total ? `${step}/${total}` : active.id}</span>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
            No benchmark is running.
          </div>
        )}
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Waiting in queue</span>
          <span className="font-semibold tabular-nums">{queued}</span>
        </div>
        <Button asChild variant="outline" className="w-full">
          <Link to="/benchmaster">
            Open Benchmaster
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  )
}

function IdleOperations({
  activity,
  status,
}: {
  activity: ActivityPayload | null
  status: BenchmasterStatus | null
}) {
  const benchMode = status?.control?.mode || 'offline'
  return (
    <Card>
      <CardContent className="grid gap-3 py-4 sm:grid-cols-2">
        <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/20 px-3 py-2.5 text-sm">
          <div>
            <div className="font-medium">Gateway</div>
            <div className="text-xs text-muted-foreground">No client sessions in the last hour</div>
          </div>
          <Badge variant="secondary">{activity ? 'idle' : 'checking'}</Badge>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/20 px-3 py-2.5 text-sm">
          <div>
            <div className="font-medium">Benchmaster</div>
            <div className="text-xs text-muted-foreground">No benchmark work is queued</div>
          </div>
          <Badge variant={status ? 'secondary' : 'warning'}>{benchMode}</Badge>
        </div>
      </CardContent>
    </Card>
  )
}

function relativeTime(value?: string) {
  if (!value) return '—'
  const elapsed = Date.now() - new Date(value).getTime()
  if (!Number.isFinite(elapsed)) return '—'
  const minutes = Math.max(0, Math.round(elapsed / 60_000))
  if (minutes < 1) return 'now'
  if (minutes < 60) return `${minutes}m ago`
  return `${Math.round(minutes / 60)}h ago`
}

function LiveBadge({
  live,
  error,
}: {
  live: boolean
  error: string | null
}) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs',
        live ? 'border-success/40 bg-success/10 text-success' : 'border-warning/40 bg-warning/10 text-warning',
      )}
      title={error || undefined}
    >
      <Radio className="h-3.5 w-3.5" />
      {live ? 'Live' : 'Reconnecting'}
    </div>
  )
}

function MiniVital({ label, value, suffix }: { label: string; value?: number; suffix: string }) {
  return (
    <div className="rounded-md border bg-muted/30 px-2 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums">
        {typeof value === 'number' ? `${value.toFixed(0)}${suffix}` : '—'}
      </div>
    </div>
  )
}
