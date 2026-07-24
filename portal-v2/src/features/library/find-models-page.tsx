import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Download, ExternalLink, Loader2, Search, Trash2 } from 'lucide-react'
import {
  getHfQueue,
  newHf,
  queueHfDownload,
  queueHfExplore,
  removeHfQueueItem,
  searchHf,
  startHfExploreDownload,
  trendingHf,
} from '@/lib/api/client'
import type { HfModelCard, HfQueueItem, HfQueuePayload } from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'

type BrowseMode = 'trending' | 'new'

const FILTER_CHIPS = [
  { id: 'gguf', label: 'GGUF' },
  { id: 'nvfp4', label: 'NVFP4' },
  { id: 'moe', label: 'MoE' },
  { id: 'fits_spark', label: 'Fits Spark' },
] as const

function formatDownloads(n?: number | null) {
  if (n == null) return null
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function traitBadges(m: HfModelCard) {
  const out: string[] = []
  if (m.has_gguf) out.push('gguf')
  if (m.has_nvfp4) out.push('nvfp4')
  if (m.has_moe) out.push('moe')
  if (m.has_dense) out.push('dense')
  if (m.has_mtp) out.push('mtp')
  if (m.has_vision) out.push('vision')
  if (m.has_diffusion) out.push('diffusion')
  return out
}

export function FindModelsPage() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<HfModelCard[]>([])
  const [mode, setMode] = useState<BrowseMode>('trending')
  const [filters, setFilters] = useState<Set<string>>(() => new Set(['fits_spark']))
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [queue, setQueue] = useState<HfQueuePayload | null>(null)
  const [actingId, setActingId] = useState<string | null>(null)
  const [usingSearch, setUsingSearch] = useState(false)
  const [queueError, setQueueError] = useState('')

  async function refreshQueue() {
    try {
      const q = await getHfQueue()
      setQueue(q)
      setQueueError('')
    } catch (err) {
      setQueueError(err instanceof Error ? err.message : String(err))
    }
  }

  useEffect(() => {
    void refreshQueue()
    const id = setInterval(() => void refreshQueue(), 5000)
    return () => clearInterval(id)
  }, [])

  async function browse(next?: { mode?: BrowseMode; filters?: Set<string>; query?: string }) {
    const activeMode = next?.mode ?? mode
    const activeFilters = [...(next?.filters ?? filters)]
    const q = (next?.query ?? query).trim()

    setBusy(true)
    setMessage('')
    if (next?.mode) setMode(next.mode)
    if (next?.filters) setFilters(next.filters)

    try {
      let models: HfModelCard[]
      if (q) {
        setUsingSearch(true)
        models = await searchHf(q, { filters: activeFilters })
      } else {
        setUsingSearch(false)
        models =
          activeMode === 'new'
            ? await newHf({ filters: activeFilters })
            : await trendingHf({ filters: activeFilters })
      }
      setResults(models)
      if (!models.length) setMessage('No models matched these filters.')
    } catch (err) {
      setResults([])
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const browseRef = useRef(browse)
  browseRef.current = browse

  // Match old Explore: load Trending + Fits Spark as soon as the page opens.
  useEffect(() => {
    void browseRef.current({ mode: 'trending', filters: new Set(['fits_spark']), query: '' })
  }, [])

  function toggleFilter(id: string) {
    const next = new Set(filters)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    void browse({ filters: next })
  }

  function setBrowseMode(next: BrowseMode) {
    setQuery('')
    void browse({ mode: next, query: '' })
  }

  async function queueDownload(repo: string) {
    setActingId(repo)
    setMessage(`Queuing download for ${repo}…`)
    try {
      await queueHfDownload(repo)
      setMessage(`Download queued: ${repo}`)
      await refreshQueue()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setActingId(null)
    }
  }

  async function saveShortlist(repo: string) {
    setActingId(`save-${repo}`)
    setMessage(`Saving ${repo} to shortlist…`)
    try {
      await queueHfExplore(repo)
      setMessage(`Shortlisted: ${repo}`)
      await refreshQueue()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setActingId(null)
    }
  }

  async function startExplore(item: HfQueueItem) {
    setActingId(item.id)
    try {
      await startHfExploreDownload(item.id)
      setMessage(`Download started: ${item.repo}`)
      await refreshQueue()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setActingId(null)
    }
  }

  async function removeItem(item: HfQueueItem, which: 'download' | 'explore') {
    setActingId(item.id)
    try {
      await removeHfQueueItem(item.id, which)
      setMessage(`Removed ${item.repo}`)
      await refreshQueue()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setActingId(null)
    }
  }

  const active = queue?.active
  const canStart =
    typeof queue?.can_start === 'object' ? queue.can_start?.ok !== false : queue?.can_start !== false
  const canStartReason =
    typeof queue?.can_start === 'object' ? queue.can_start?.reason : undefined

  const resultsLabel = usingSearch
    ? `Search: ${query.trim()}`
    : mode === 'new'
      ? 'Recently updated'
      : 'Trending on HF'

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2 gap-1 text-muted-foreground">
          <Link to="/library">
            <ArrowLeft className="h-4 w-4" />
            Library
          </Link>
        </Button>
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">Find on Hugging Face</h1>
          <p className="max-w-2xl text-muted-foreground">
            Same browse flow as the old Explore tab: trending / new, Spark-oriented filters, then queue a download
            or shortlist for later.
          </p>
        </div>
      </header>

      <div className="space-y-3">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void browse()
          }}
          className="flex flex-wrap gap-2"
        >
          <div className="relative min-w-[220px] flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Search Hugging Face models…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy || !query.trim()}>
            {busy && usingSearch ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Search'}
          </Button>
        </form>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-md border p-0.5">
            <button
              type="button"
              className={cn(
                'rounded px-3 py-1.5 text-sm transition-colors',
                !usingSearch && mode === 'trending'
                  ? 'bg-secondary text-secondary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
              title="HF Hub trending (recent momentum, not all-time downloads)"
              disabled={busy}
              onClick={() => setBrowseMode('trending')}
            >
              Trending
            </button>
            <button
              type="button"
              className={cn(
                'rounded px-3 py-1.5 text-sm transition-colors',
                !usingSearch && mode === 'new'
                  ? 'bg-secondary text-secondary-foreground'
                  : 'text-muted-foreground hover:text-foreground',
              )}
              disabled={busy}
              onClick={() => setBrowseMode('new')}
            >
              New
            </button>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {FILTER_CHIPS.map((chip) => (
              <button
                key={chip.id}
                type="button"
                disabled={busy}
                onClick={() => toggleFilter(chip.id)}
                className={cn(
                  'rounded-md border px-2.5 py-1 text-xs transition-colors',
                  filters.has(chip.id)
                    ? 'border-primary bg-primary/10 text-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {message && <p className="text-sm text-muted-foreground">{message}</p>}
      {queueError && (
        <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
          Download queue unavailable: {queueError}
        </p>
      )}

      {active?.repo && (
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Active download</CardDescription>
            <CardTitle className="text-base font-mono">{active.repo}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{active.state || 'running'}</span>
              {active.progress_pct != null && <span>{Math.round(active.progress_pct)}%</span>}
            </div>
            {active.progress_pct != null && <Progress value={active.progress_pct} />}
          </CardContent>
        </Card>
      )}

      {!canStart && canStartReason && (
        <p className="text-sm text-amber-600 dark:text-amber-400">Queue paused: {canStartReason}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <section className="space-y-3">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">{resultsLabel}</h2>
            <span className="text-xs text-muted-foreground">
              {busy ? 'Loading…' : results.length ? results.length : '—'}
            </span>
          </div>

          {busy && !results.length ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : (
            <div className="space-y-2">
              {results.map((m) => {
                const traits = traitBadges(m)
                const downloads = formatDownloads(m.downloads)
                return (
                  <Card key={m.repo}>
                    <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0 space-y-1.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium font-mono text-sm break-all">{m.repo}</span>
                          {m.pipeline_tag && <Badge variant="outline">{m.pipeline_tag}</Badge>}
                          {traits.map((t) => (
                            <Badge key={t} variant="secondary">
                              {t}
                            </Badge>
                          ))}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {downloads ? `${downloads} downloads` : null}
                          {m.likes != null ? `${downloads ? ' · ' : ''}${m.likes} likes` : null}
                          {!downloads && m.likes == null ? 'Hub model' : null}
                        </div>
                        {m.spark_warning && (
                          <p className="text-xs text-amber-600 dark:text-amber-400">{m.spark_warning}</p>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2 shrink-0">
                        {m.hf_url && (
                          <Button asChild size="sm" variant="ghost">
                            <a href={m.hf_url} target="_blank" rel="noreferrer">
                              <ExternalLink className="h-3.5 w-3.5" />
                              Hub
                            </a>
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingId === `save-${m.repo}`}
                          onClick={() => void saveShortlist(m.repo)}
                        >
                          Shortlist
                        </Button>
                        <Button
                          size="sm"
                          disabled={actingId === m.repo}
                          onClick={() => void queueDownload(m.repo)}
                        >
                          <Download className="h-3.5 w-3.5" />
                          Queue download
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}
        </section>

        <aside className="space-y-4">
          <QueuePanel
            title="Download queue"
            empty="No downloads queued."
            items={queue?.download || []}
            actingId={actingId}
            onRemove={(item) => void removeItem(item, 'download')}
            stateKey="state"
          />
          <QueuePanel
            title="Shortlist"
            empty="Nothing shortlisted yet."
            items={queue?.explore || []}
            actingId={actingId}
            onRemove={(item) => void removeItem(item, 'explore')}
            onDownload={(item) => void startExplore(item)}
            stateKey="status"
          />
        </aside>
      </div>
    </div>
  )
}

function QueuePanel({
  title,
  empty,
  items,
  actingId,
  onRemove,
  onDownload,
  stateKey,
}: {
  title: string
  empty: string
  items: HfQueueItem[]
  actingId: string | null
  onRemove: (item: HfQueueItem) => void
  onDownload?: (item: HfQueueItem) => void
  stateKey: 'state' | 'status'
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-lg">{items.length}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {!items.length ? (
          <p className="text-sm text-muted-foreground">{empty}</p>
        ) : (
          items.map((item) => {
            const label = stateKey === 'state' ? item.state : item.status
            return (
              <div key={item.id} className="rounded-md border p-3 space-y-2">
                <div className="font-mono text-xs break-all">{item.repo}</div>
                <div className="flex flex-wrap items-center gap-2">
                  {label && <Badge variant="outline">{label}</Badge>}
                  {item.variant_label && <Badge variant="secondary">{item.variant_label}</Badge>}
                  {item.plan?.size_human && (
                    <span className="text-xs text-muted-foreground">{item.plan.size_human}</span>
                  )}
                </div>
                {item.note && <p className="text-xs text-muted-foreground">{item.note}</p>}
                <div className="flex flex-wrap gap-2">
                  {onDownload && label !== 'download_queued' && label !== 'on_disk' && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={actingId === item.id}
                      onClick={() => onDownload(item)}
                    >
                      <Download className="h-3.5 w-3.5" />
                      Download
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={actingId === item.id}
                    onClick={() => onRemove(item)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    Remove
                  </Button>
                </div>
              </div>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}
