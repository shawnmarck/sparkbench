import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Bot,
  CalendarClock,
  Check,
  CirclePause,
  ExternalLink,
  Goal,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { OperatorChat } from '@/features/operator/operator-chat'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  createOperatorProposal,
  deleteOperatorGoal,
  getOperatorChecks,
  getOperatorGoals,
  getOperatorModelCatalog,
  getOperatorSettings,
  resolveOperatorProposal,
  saveOperatorGoal,
  updateOperatorSettings,
} from '@/lib/api/client'
import type {
  OperatorCheck,
  OperatorGoal,
  OperatorModelCatalog,
  OperatorProposal,
  OperatorSettings,
  OperatorStatus,
} from '@/lib/api/types'
import { cn } from '@/lib/utils'

type Tab = 'chat' | 'goals' | 'checks' | 'settings'

const tabs: Array<{ id: Tab; label: string; icon: typeof Bot }> = [
  { id: 'chat', label: 'Chat', icon: Bot },
  { id: 'goals', label: 'Goals', icon: Goal },
  { id: 'checks', label: 'Daily checks', icon: CalendarClock },
  { id: 'settings', label: 'Settings', icon: Settings2 },
]

export function OperatorPage() {
  const [tab, setTab] = useState<Tab>('chat')
  const [status, setStatus] = useState<OperatorStatus | null>(null)
  const [goals, setGoals] = useState<OperatorGoal[]>([])
  const [checks, setChecks] = useState<OperatorCheck[]>([])
  const [settings, setSettings] = useState<OperatorSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    const [goalResult, checkResult, settingsResult] = await Promise.allSettled([
      getOperatorGoals(),
      getOperatorChecks(),
      getOperatorSettings(),
    ])
    if (goalResult.status === 'fulfilled') setGoals(goalResult.value)
    if (checkResult.status === 'fulfilled') setChecks(checkResult.value)
    if (settingsResult.status === 'fulfilled') setSettings(settingsResult.value)
    const failure = [goalResult, checkResult, settingsResult].find((result) => result.status === 'rejected')
    if (failure?.status === 'rejected') {
      setError(failure.reason instanceof Error ? failure.reason.message : String(failure.reason))
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
            <Sparkles className="h-3.5 w-3.5" />
            Hermes-powered operator
          </div>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Spark</h1>
          <p className="max-w-2xl text-muted-foreground">
            Talk to your model lab, keep operational goals, and automate routine checks without giving an agent an unrestricted shell.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={status?.available ? 'success' : 'secondary'}>
            {status?.available ? 'online' : 'offline'}
          </Badge>
          <Badge variant="outline">{status?.provider || 'provider not set'}</Badge>
          {status?.pending_actions ? <Badge variant="warning">{status.pending_actions} awaiting confirmation</Badge> : null}
        </div>
      </header>

      <div className="flex gap-1 overflow-x-auto rounded-xl border bg-muted/25 p-1" role="tablist">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={cn(
              'inline-flex min-w-max flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors',
              tab === id ? 'bg-background font-medium shadow-sm' : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={() => setTab(id)}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
          {error}
        </div>
      )}

      {tab === 'chat' && <OperatorChat onStatus={setStatus} />}
      {tab === 'goals' && <GoalsPanel goals={goals} loading={loading} onRefresh={refresh} />}
      {tab === 'checks' && <ChecksPanel checks={checks} loading={loading} goals={goals} onRefresh={refresh} />}
      {tab === 'settings' && <SettingsPanel settings={settings} onSaved={setSettings} />}
    </div>
  )
}

function GoalsPanel({
  goals,
  loading,
  onRefresh,
}: {
  goals: OperatorGoal[]
  loading: boolean
  onRefresh: () => Promise<void>
}) {
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState('')
  const [message, setMessage] = useState('')

  async function addGoal(event: FormEvent) {
    event.preventDefault()
    if (!title.trim()) return
    setBusy('new')
    try {
      await saveOperatorGoal({ title: title.trim(), notes: notes.trim(), status: 'active' })
      setTitle('')
      setNotes('')
      setMessage('Goal added')
      await onRefresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy('')
    }
  }

  async function setGoalStatus(goal: OperatorGoal, status: OperatorGoal['status']) {
    setBusy(goal.id)
    try {
      await saveOperatorGoal({ title: goal.title, notes: goal.notes, status }, goal.id)
      await onRefresh()
    } finally {
      setBusy('')
    }
  }

  async function remove(goal: OperatorGoal) {
    if (!window.confirm(`Delete goal “${goal.title}”?`)) return
    setBusy(goal.id)
    try {
      await deleteOperatorGoal(goal.id)
      await onRefresh()
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[0.72fr_1.28fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">New operational goal</CardTitle>
          <CardDescription>Persistent context Spark can use across sessions and checks.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={addGoal}>
            <div className="space-y-2">
              <Label htmlFor="goal-title">Goal</Label>
              <Input id="goal-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Keep golden recipes current" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="goal-notes">Success notes</Label>
              <textarea
                id="goal-notes"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                rows={4}
                className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="What should Spark watch, report, or help complete?"
              />
            </div>
            <Button type="submit" disabled={!title.trim() || busy === 'new'}>
              {busy === 'new' ? <Loader2 className="animate-spin" /> : <Plus />}
              Add goal
            </Button>
            {message && <p role="status" className="text-xs text-muted-foreground">{message}</p>}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Goals</CardTitle>
          <CardDescription>{goals.filter((goal) => goal.status === 'active').length} active</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading goals…</p>
          ) : goals.length ? goals.map((goal) => (
            <div key={goal.id} className="rounded-xl border p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-medium">{goal.title}</div>
                  {goal.notes && <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{goal.notes}</p>}
                </div>
                <Badge variant={goal.status === 'active' ? 'success' : 'secondary'}>{goal.status}</Badge>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {goal.status !== 'done' && (
                  <Button size="sm" variant="outline" disabled={busy === goal.id} onClick={() => void setGoalStatus(goal, goal.status === 'paused' ? 'active' : 'paused')}>
                    {goal.status === 'paused' ? <Play /> : <CirclePause />}
                    {goal.status === 'paused' ? 'Resume' : 'Pause'}
                  </Button>
                )}
                {goal.status !== 'done' && (
                  <Button size="sm" variant="outline" disabled={busy === goal.id} onClick={() => void setGoalStatus(goal, 'done')}>
                    <Check />
                    Complete
                  </Button>
                )}
                <Button size="sm" variant="ghost" className="text-destructive" disabled={busy === goal.id} onClick={() => void remove(goal)}>
                  <Trash2 />
                  Delete
                </Button>
              </div>
            </div>
          )) : (
            <div className="rounded-xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
              No goals yet. Add one for Spark to carry between conversations.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function ChecksPanel({
  checks,
  loading,
  goals,
  onRefresh,
}: {
  checks: OperatorCheck[]
  loading: boolean
  goals: OperatorGoal[]
  onRefresh: () => Promise<void>
}) {
  const [name, setName] = useState('Daily SparkBench health')
  const [schedule, setSchedule] = useState('0 8 * * *')
  const [prompt, setPrompt] = useState('Check service, GPU, inference, shelf, and Benchmaster health. Report only actionable exceptions and recommend the next safe step.')
  const [goalId, setGoalId] = useState('')
  const [proposal, setProposal] = useState<OperatorProposal | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  async function propose(action: string, args: Record<string, unknown>) {
    setBusy(true)
    setMessage('')
    try {
      setProposal(await createOperatorProposal(action, args))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  async function create(event: FormEvent) {
    event.preventDefault()
    await propose('check_create', { name, schedule, prompt, goal_id: goalId || undefined })
  }

  async function resolve(resolution: 'confirm' | 'cancel') {
    if (!proposal) return
    setBusy(true)
    try {
      const next = await resolveOperatorProposal(proposal.id, resolution)
      setProposal(next)
      if (next.state === 'succeeded') await onRefresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {proposal && (
        <ConfirmationCard proposal={proposal} busy={busy} onResolve={resolve} />
      )}
      <div className="grid gap-4 xl:grid-cols-[0.72fr_1.28fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Schedule a check</CardTitle>
            <CardDescription>Hermes cron runs with the OOB model; creation requires confirmation.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={create}>
              <div className="space-y-2">
                <Label htmlFor="check-name">Name</Label>
                <Input id="check-name" value={name} onChange={(event) => setName(event.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="check-schedule">Cron schedule</Label>
                <Input id="check-schedule" value={schedule} onChange={(event) => setSchedule(event.target.value)} className="font-mono" />
                <p className="text-xs text-muted-foreground">Uses the host timezone. Default: every day at 08:00.</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="check-goal">Related goal</Label>
                <select id="check-goal" value={goalId} onChange={(event) => setGoalId(event.target.value)} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
                  <option value="">None</option>
                  {goals.filter((goal) => goal.status === 'active').map((goal) => <option key={goal.id} value={goal.id}>{goal.title}</option>)}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="check-prompt">Instructions</Label>
                <textarea id="check-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={5} className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
              </div>
              <Button type="submit" disabled={busy || !name.trim() || !schedule.trim() || !prompt.trim()}>
                <CalendarClock />
                Review schedule
              </Button>
              {message && <p role="status" className="text-xs text-destructive">{message}</p>}
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Scheduled checks</CardTitle>
            <CardDescription>Persistent Hermes jobs, separate from the GPU benchmark queue.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {loading ? <p className="text-sm text-muted-foreground">Loading checks…</p> : checks.length ? checks.map((check) => (
              <div key={check.id} className="rounded-xl border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-medium">{check.name}</div>
                    <div className="mt-1 font-mono text-xs text-muted-foreground">{check.schedule || 'unscheduled'}</div>
                    <p className="mt-2 line-clamp-2 text-sm text-muted-foreground">{check.prompt}</p>
                  </div>
                  <Badge variant={check.enabled ? 'success' : 'secondary'}>{check.enabled ? 'enabled' : 'paused'}</Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => void propose('check_run', { job_id: check.id })}>
                    <RotateCcw />
                    Run now
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => void propose(check.enabled ? 'check_pause' : 'check_resume', { job_id: check.id })}>
                    {check.enabled ? <CirclePause /> : <Play />}
                    {check.enabled ? 'Pause' : 'Resume'}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-destructive" onClick={() => void propose('check_delete', { job_id: check.id })}>
                    <Trash2 />
                    Delete
                  </Button>
                </div>
              </div>
            )) : (
              <div className="rounded-xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                No checks scheduled. The daily health template is ready when you are.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function SettingsPanel({
  settings,
  onSaved,
}: {
  settings: OperatorSettings | null
  onSaved: (settings: OperatorSettings) => void
}) {
  const [provider, setProvider] = useState(settings?.provider || 'openrouter')
  const [model, setModel] = useState(settings?.model || '')
  const [catalog, setCatalog] = useState<OperatorModelCatalog | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogError, setCatalogError] = useState('')
  const catalogRequest = useRef(0)
  const [reviewing, setReviewing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!settings) return
    setProvider(settings.provider || 'openrouter')
    setModel(settings.model || '')
  }, [settings])

  const loadModels = useCallback(async (refresh = false) => {
    if (!provider) return
    const requestId = ++catalogRequest.current
    setCatalogLoading(true)
    setCatalogError('')
    try {
      const nextCatalog = await getOperatorModelCatalog(provider, refresh)
      if (catalogRequest.current === requestId) setCatalog(nextCatalog)
    } catch (error) {
      if (catalogRequest.current === requestId) {
        setCatalogError(error instanceof Error ? error.message : String(error))
      }
    } finally {
      if (catalogRequest.current === requestId) setCatalogLoading(false)
    }
  }, [provider])

  useEffect(() => {
    void loadModels()
  }, [loadModels])

  async function save() {
    setBusy(true)
    setMessage('')
    try {
      const next = await updateOperatorSettings({
        provider,
        model,
      })
      onSaved(next)
      setReviewing(false)
      setMessage('Provider saved and Hermes restarted')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const hasCatalogModels = Boolean(catalog?.models.length)
  const modelIsCatalogChoice = Boolean(catalog?.models.some((item) => item.id === model))
  const configuredProviders = catalog?.providers.filter((item) => item.authenticated || item.id === provider) || []

  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_0.72fr]">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Out-of-band inference</CardTitle>
          <CardDescription>Spark stays available even while local inference is switching or stopped.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {reviewing && (
            <div className="rounded-xl border border-warning/35 bg-warning/5 p-4">
              <div className="flex items-center gap-2 font-medium"><ShieldCheck className="h-4 w-4 text-warning" />Restart Hermes with this provider?</div>
              <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                <div><dt className="text-xs text-muted-foreground">Provider</dt><dd>{provider}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Model</dt><dd className="font-mono text-xs">{model}</dd></div>
              </dl>
              <div className="mt-4 flex gap-2">
                <Button size="sm" disabled={busy} onClick={() => void save()}>{busy ? <Loader2 className="animate-spin" /> : <Check />}Confirm & restart</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => setReviewing(false)}><X />Cancel</Button>
              </div>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="operator-provider">Provider</Label>
            <select
              id="operator-provider"
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value)
                setModel('')
              }}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              {!catalog?.providers.some((item) => item.id === provider) && (
                <option value={provider}>{provider}</option>
              )}
              {(configuredProviders.length ? configuredProviders : [{ id: provider, name: provider }]).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            {catalog?.selected && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant={catalog.selected.authenticated ? 'success' : 'secondary'}>
                  {catalog.selected.authenticated ? 'authenticated' : 'not configured'}
                </Badge>
                <span>{catalog.selected.total_models} available models</span>
                {catalog.selected.warning && <span className="text-warning">{catalog.selected.warning}</span>}
              </div>
            )}
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="operator-model">Model</Label>
              <Button type="button" size="sm" variant="ghost" disabled={catalogLoading} onClick={() => void loadModels(true)}>
                <RefreshCw className={cn(catalogLoading && 'animate-spin')} />
                Refresh models
              </Button>
            </div>
            {hasCatalogModels ? (
              <>
                <select
                  id="operator-model"
                  value={modelIsCatalogChoice ? model : model ? '__custom__' : ''}
                  onChange={(event) => setModel(event.target.value === '__custom__' ? '' : event.target.value)}
                  className="h-10 w-full rounded-md border bg-background px-3 font-mono text-sm"
                >
                  <option value="" disabled>Choose a model…</option>
                  {(catalog?.models || []).map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                  <option value="__custom__">Custom model ID…</option>
                </select>
                {!modelIsCatalogChoice && (
                  <Input
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    placeholder="Enter a custom model id"
                    className="font-mono"
                    aria-label="Custom model ID"
                  />
                )}
              </>
            ) : (
              <Input
                id="operator-model"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder={catalogLoading ? 'Loading provider models…' : 'Enter a model id'}
                className="font-mono"
              />
            )}
            {catalogError && <p className="text-xs text-warning">{catalogError}</p>}
            {!catalogLoading && catalog && !catalog.models.length && (
              <p className="text-xs text-muted-foreground">
                No catalog returned. Configure this provider in Hermes or enter a model id manually.
              </p>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Provider endpoint and credentials are managed by Hermes and applied automatically.
          </p>
          <Button disabled={!model.trim() || reviewing || catalog?.selected?.authenticated === false} onClick={() => setReviewing(true)}>
            <ShieldCheck />
            Review change
          </Button>
          {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Provider management</CardTitle>
          <CardDescription>Add providers, update credentials, and manage OAuth in Hermes.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {settings?.dashboard_url && (
            <Button asChild variant="outline" className="w-full">
              <a href={settings.dashboard_url} target="_blank" rel="noreferrer">
                Open Hermes dashboard
                <ExternalLink />
              </a>
            </Button>
          )}
          <p className="text-xs leading-relaxed text-muted-foreground">
            Providers configured there automatically appear in this picker with their available models.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}

function ConfirmationCard({
  proposal,
  busy,
  onResolve,
}: {
  proposal: OperatorProposal
  busy: boolean
  onResolve: (resolution: 'confirm' | 'cancel') => Promise<void>
}) {
  const pending = proposal.state === 'pending'
  return (
    <Card className="border-warning/35 bg-warning/5">
      <CardContent className="flex flex-wrap items-start justify-between gap-4 py-4">
        <div>
          <div className="flex items-center gap-2 font-medium"><ShieldCheck className="h-4 w-4 text-warning" />{proposal.title}</div>
          <p className="mt-1 text-sm text-muted-foreground">{proposal.summary}</p>
          {proposal.error && <p className="mt-1 text-sm text-destructive">{proposal.error}</p>}
        </div>
        {pending ? (
          <div className="flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => void onResolve('confirm')}>{busy ? <Loader2 className="animate-spin" /> : <Check />}Confirm</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void onResolve('cancel')}><X />Cancel</Button>
          </div>
        ) : <Badge variant={proposal.state === 'succeeded' ? 'success' : proposal.state === 'failed' ? 'destructive' : 'secondary'}>{proposal.state}</Badge>}
      </CardContent>
    </Card>
  )
}
