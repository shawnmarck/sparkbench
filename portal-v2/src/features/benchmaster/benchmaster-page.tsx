import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock3,
  FlaskConical,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Square,
  Trash2,
  Wifi,
  WifiOff,
} from 'lucide-react'
import {
  addBenchmasterJob,
  controlBenchmaster,
  getBenchmasterQueue,
  getBenchmasterRuns,
  getBenchmasterStatus,
  getRecipes,
  removeBenchmasterJob,
} from '@/lib/api/client'
import type {
  BenchmasterJob,
  BenchmasterPhase,
  BenchmasterRun,
  BenchmasterStatus,
  Recipe,
} from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === '1'

const JOB_LABELS: Record<BenchmasterJob['type'], string> = {
  perf_sweep: 'Full performance sweep',
  golden_workflow: 'Golden workflow',
  kv_sweep: 'KV cache sweep',
  ctx_ladder: 'Context ladder',
  intel_eval: 'Agent intelligence eval',
}

export function BenchmasterPage() {
  const [status, setStatus] = useState<BenchmasterStatus | null>(null)
  const [jobs, setJobs] = useState<BenchmasterJob[]>([])
  const [runs, setRuns] = useState<BenchmasterRun[]>([])
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [loading, setLoading] = useState(true)
  const [online, setOnline] = useState(false)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const refreshTimer = useRef<number | null>(null)

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    const [nextStatus, nextQueue, nextRuns] = await Promise.allSettled([
      getBenchmasterStatus(),
      getBenchmasterQueue(),
      getBenchmasterRuns(),
    ])
    if (nextStatus.status === 'fulfilled') {
      setStatus(nextStatus.value)
      setOnline(true)
      setMessage((current) => (current.startsWith('Offline:') ? '' : current))
    } else {
      setOnline(false)
      setMessage(`Offline: ${nextStatus.reason instanceof Error ? nextStatus.reason.message : 'Benchmaster API unavailable'}`)
    }
    if (nextQueue.status === 'fulfilled') setJobs(nextQueue.value.items || [])
    if (nextRuns.status === 'fulfilled') setRuns(nextRuns.value)
    setLoading(false)
  }, [])

  useEffect(() => {
    void refresh()
    void getRecipes().then(setRecipes).catch(() => setRecipes([]))
    const interval = window.setInterval(() => void refresh(true), 10_000)

    if (USE_FIXTURES || typeof EventSource === 'undefined') {
      return () => window.clearInterval(interval)
    }

    const stream = new EventSource('/api/benchmaster/stream')
    stream.addEventListener('status', (event) => {
      try {
        const next = JSON.parse((event as MessageEvent<string>).data) as BenchmasterStatus
        setStatus(next)
        setOnline(true)
      } catch {
        // Polling remains the source of truth if an event is malformed.
      }
    })
    stream.addEventListener('benchmaster', () => {
      if (refreshTimer.current) window.clearTimeout(refreshTimer.current)
      refreshTimer.current = window.setTimeout(() => void refresh(true), 500)
    })
    stream.onerror = () => setOnline(false)

    return () => {
      window.clearInterval(interval)
      if (refreshTimer.current) window.clearTimeout(refreshTimer.current)
      stream.close()
    }
  }, [refresh])

  const active = status?.current_job || status?.attention_job || jobs.find((job) => job.state === 'running')
  const visibleJobs = jobs.filter((job) => ['queued', 'running', 'failed'].includes(job.state))
  const queueCounts = useMemo(
    () => ({
      gpu: visibleJobs.filter((job) => job.type !== 'intel_eval' && job.state === 'queued').length,
      intel: visibleJobs.filter((job) => job.type === 'intel_eval' && job.state === 'queued').length,
      failed: visibleJobs.filter((job) => job.state === 'failed').length,
    }),
    [visibleJobs],
  )

  async function runControl(action: Parameters<typeof controlBenchmaster>[0]) {
    if (
      action === 'abort_current_requeue_front' &&
      !window.confirm('Abort the active benchmark process and requeue it at the front?')
    ) {
      return
    }
    setBusy(action)
    setMessage('')
    try {
      await controlBenchmaster(action)
      setMessage(action === 'resume' ? 'Queue resumed' : action === 'pause' ? 'Queue paused and GPU release requested' : 'Control request sent')
      await refresh(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  async function removeJob(job: BenchmasterJob) {
    if (!window.confirm(`Remove ${job.profile_id} from the benchmark queue?`)) return
    setBusy(job.id)
    try {
      await removeBenchmasterJob(job.id)
      setMessage(`Removed ${job.profile_id}`)
      await refresh(true)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
            <FlaskConical className="h-3.5 w-3.5" />
            Automated lab
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">Benchmaster</h1>
          <p className="max-w-2xl text-muted-foreground">
            Queue performance sweeps on Sparky and intelligence evals on the remote Harbor worker.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={online ? 'success' : 'warning'} className="gap-1.5">
            {online ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
            {online ? 'live' : 'offline'}
          </Badge>
          <Button variant="outline" size="sm" onClick={() => void refresh()} disabled={loading}>
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </header>

      {message && (
        <div
          role="status"
          className={cn(
            'rounded-lg border px-4 py-3 text-sm',
            message.startsWith('Offline:') ? 'border-warning/40 bg-warning/10 text-warning' : 'bg-card',
          )}
        >
          {message}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <SummaryCard label="Control" value={status?.control?.mode || 'unknown'} tone={status?.control?.mode === 'running' ? 'good' : 'neutral'} />
        <SummaryCard
          label="Waiting"
          value={String(queueCounts.gpu + queueCounts.intel)}
          detail={queueCounts.intel ? `${queueCounts.intel} intel · ${queueCounts.gpu} GPU` : undefined}
        />
        <SummaryCard label="Failed" value={String(queueCounts.failed)} tone={queueCounts.failed ? 'warn' : 'neutral'} />
        <SummaryCard label="Worker" value={status?.worker_alive ? 'online' : 'offline'} tone={status?.worker_alive ? 'good' : 'warn'} />
      </div>

      <Card className={cn(active && 'border-primary/30 shadow-[0_0_36px_var(--glow-soft)]')}>
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardDescription className="mb-1">Current work</CardDescription>
              <CardTitle className="text-lg">{active?.profile_id || 'No active benchmark'}</CardTitle>
            </div>
            {active && <Badge variant={active.state === 'failed' ? 'warning' : 'secondary'}>{JOB_LABELS[active.type]}</Badge>}
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          {active ? (
            <>
              {active.awaiting === 'remote_worker' && (
                <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm">
                  Model is prepared on Sparky. Start the Harbor worker to claim this eval.
                </div>
              )}
              <PhaseList phases={active.live_phases || []} />
              <JobProgress job={active} />
              {active.error && <p className="text-sm text-destructive">{active.error}</p>}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {status?.control?.mode === 'running' && visibleJobs.length
                ? 'Worker is selecting the next queued job…'
                : 'Queue a recipe below, then resume when you want Benchmaster to own the GPU.'}
            </p>
          )}

          <div className="flex flex-wrap gap-2 border-t pt-4">
            {status?.control?.mode === 'running' ? (
              <Button variant="outline" onClick={() => void runControl('pause')} disabled={!!busy}>
                <Pause className="h-4 w-4" />
                Pause & release GPU
              </Button>
            ) : (
              <Button onClick={() => void runControl('resume')} disabled={!!busy || !online}>
                <Play className="h-4 w-4" />
                Resume queue
              </Button>
            )}
            {active && (
              <>
                <Button variant="outline" onClick={() => void runControl('stop_after_current')} disabled={!!busy}>
                  <Square className="h-4 w-4" />
                  Stop after current
                </Button>
                <Button variant="destructive" onClick={() => void runControl('abort_current_requeue_front')} disabled={!!busy}>
                  <RotateCcw className="h-4 w-4" />
                  Abort & requeue
                </Button>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(340px,0.75fr)]">
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Queue</h2>
            <span className="text-xs text-muted-foreground">
              {queueCounts.gpu + queueCounts.intel} waiting
              {queueCounts.failed ? ` · ${queueCounts.failed} failed` : ''}
            </span>
          </div>
          {visibleJobs.length ? (
            <div className="overflow-hidden rounded-xl border bg-card">
              {visibleJobs.map((job, index) => (
                <QueueRow
                  key={job.id}
                  job={job}
                  index={index}
                  busy={busy === job.id}
                  onRemove={() => void removeJob(job)}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
              Queue is empty. Add a tested recipe to start an automated run.
            </div>
          )}
        </section>

        <AddJobCard
          recipes={recipes}
          disabled={!online || !!busy}
          onAdd={async (input) => {
            setBusy('add')
            try {
              await addBenchmasterJob(input)
              setMessage(`Queued ${input.profile_id}`)
              await refresh(true)
            } catch (error) {
              setMessage(error instanceof Error ? error.message : String(error))
            } finally {
              setBusy(null)
            }
          }}
        />
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Recent runs</h2>
          <span className="text-xs text-muted-foreground">Latest 20 artifacts</span>
        </div>
        <div className="overflow-hidden rounded-xl border bg-card">
          {runs.length ? (
            runs.slice(0, 20).map((run) => <RunRow key={run.job_id || run.id} run={run} />)
          ) : (
            <div className="p-6 text-sm text-muted-foreground">No completed runs yet.</div>
          )}
        </div>
      </section>
    </div>
  )
}

function SummaryCard({
  label,
  value,
  detail,
  tone = 'neutral',
}: {
  label: string
  value: string
  detail?: string
  tone?: 'neutral' | 'good' | 'warn'
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className={cn('mt-1 text-xl font-semibold capitalize', tone === 'good' && 'text-success', tone === 'warn' && 'text-warning')}>
          {value}
        </div>
        {detail && <div className="mt-0.5 text-xs text-muted-foreground">{detail}</div>}
      </CardContent>
    </Card>
  )
}

function PhaseList({ phases }: { phases: BenchmasterPhase[] }) {
  if (!phases.length) return null
  return (
    <ol className="grid gap-2 md:grid-cols-3">
      {phases.map((phase, index) => {
        const state = phase.state || 'pending'
        const Icon = state === 'done' ? CheckCircle2 : state === 'running' ? Loader2 : state === 'failed' ? AlertTriangle : Circle
        return (
          <li key={phase.id || index} className={cn('rounded-lg border p-3', state === 'running' && 'border-primary/40 bg-primary/5')}>
            <div className="flex items-center gap-2 text-sm font-medium">
              <Icon className={cn('h-4 w-4', state === 'done' && 'text-success', state === 'failed' && 'text-destructive', state === 'running' && 'animate-spin text-primary')} />
              {phase.label || phase.id}
            </div>
            {(phase.detail || phase.hint) && <p className="mt-1 text-xs text-muted-foreground">{phase.detail || phase.hint}</p>}
          </li>
        )
      })}
    </ol>
  )
}

function JobProgress({ job }: { job: BenchmasterJob }) {
  const step = job.progress?.step || 0
  const total = job.progress?.total_steps || 0
  const percent = total > 0 ? (step / total) * 100 : job.state === 'running' ? 8 : 0
  return (
    <div className="space-y-2">
      <div className="flex justify-between gap-3 text-xs text-muted-foreground">
        <span>{job.progress?.message || job.progress?.phase || job.state}</span>
        <span className="tabular-nums">{total ? `${step}/${total}` : job.id}</span>
      </div>
      <Progress value={percent} />
    </div>
  )
}

function QueueRow({
  job,
  index,
  busy,
  onRemove,
}: {
  job: BenchmasterJob
  index: number
  busy: boolean
  onRemove: () => void
}) {
  return (
    <div className="grid gap-3 border-b p-4 last:border-0 sm:grid-cols-[2rem_minmax(0,1fr)_auto] sm:items-center">
      <span className="hidden text-xs tabular-nums text-muted-foreground sm:block">{String(index + 1).padStart(2, '0')}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-medium">{job.profile_id}</span>
          <Badge variant={job.state === 'failed' ? 'warning' : job.state === 'running' ? 'success' : 'secondary'}>{job.state}</Badge>
          <Badge variant="outline">{JOB_LABELS[job.type]}</Badge>
        </div>
        <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
          {job.inventory_path || job.id}
          {job.claimed_by ? ` · claimed by ${job.claimed_by}` : ''}
        </div>
        {job.error && <p className="mt-1 text-xs text-destructive">{job.error}</p>}
      </div>
      {job.state !== 'running' && (
        <Button variant="ghost" size="icon" aria-label={`Remove ${job.profile_id}`} disabled={busy} onClick={onRemove}>
          {busy ? <Loader2 className="animate-spin" /> : <Trash2 />}
        </Button>
      )}
    </div>
  )
}

function AddJobCard({
  recipes,
  disabled,
  onAdd,
}: {
  recipes: Recipe[]
  disabled: boolean
  onAdd: (input: Parameters<typeof addBenchmasterJob>[0]) => Promise<void>
}) {
  const [profile, setProfile] = useState('')
  const [type, setType] = useState<BenchmasterJob['type']>('perf_sweep')
  const [note, setNote] = useState('')
  const [front, setFront] = useState(false)
  const selected = recipes.find((recipe) => recipe.id === profile)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Plus className="h-4 w-4 text-primary" />
          Queue a run
        </CardTitle>
        <CardDescription>Benchmaster takes GPU ownership only after you resume the queue.</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (!profile) return
            void onAdd({
              type,
              profile_id: profile,
              inventory_path: selected?.inventory_path,
              note: note.trim() || undefined,
              front,
            }).then(() => {
              setNote('')
              setFront(false)
            })
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="bm-profile">Recipe</Label>
            <select
              id="bm-profile"
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={profile}
              onChange={(event) => setProfile(event.target.value)}
            >
              <option value="">Choose a recipe…</option>
              {recipes.map((recipe) => (
                <option key={recipe.id} value={recipe.id}>
                  {recipe.name} · {recipe.engine}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="bm-type">Run type</Label>
            <select
              id="bm-type"
              className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={type}
              onChange={(event) => setType(event.target.value as BenchmasterJob['type'])}
            >
              {Object.entries(JOB_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground">
              {type === 'intel_eval'
                ? 'Loads the model here, then waits for Harbor on the remote worker.'
                : type === 'perf_sweep'
                  ? 'Golden workflow + KV sweep + context ladder.'
                  : 'Runs only this benchmark phase.'}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="bm-note">Note</Label>
            <Input id="bm-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why this run matters…" />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="bm-front" checked={front} onCheckedChange={(value) => setFront(value === true)} />
            <Label htmlFor="bm-front" className="cursor-pointer">Put at front of queue</Label>
          </div>
          <Button type="submit" className="w-full" disabled={disabled || !profile}>
            <Plus className="h-4 w-4" />
            Add to queue
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function RunRow({ run }: { run: BenchmasterRun }) {
  const ok = !!run.ok
  const label = run.aborted ? 'aborted' : ok ? 'done' : 'failed'
  return (
    <div className="grid gap-2 border-b px-4 py-3 text-sm last:border-0 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
      <div className="min-w-0">
        <div className="truncate font-medium">{run.profile_id || run.job_id || run.id}</div>
        <div className="font-mono text-[11px] text-muted-foreground">{run.type || 'benchmark'}</div>
      </div>
      <Badge variant={ok ? 'success' : run.aborted ? 'warning' : 'outline'}>{label}</Badge>
      <span className="flex items-center gap-1 text-xs text-muted-foreground">
        <Clock3 className="h-3 w-3" />
        {run.finished_at ? new Date(run.finished_at).toLocaleString() : '—'}
      </span>
    </div>
  )
}
