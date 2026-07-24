import { useEffect, useMemo, useState } from 'react'
import { ArrowDownWideNarrow, Download, LayoutGrid, List, Play, Search } from 'lucide-react'
import { getInventory, getRecipes } from '@/lib/api/client'
import type { InventoryModel, Recipe } from '@/lib/api/types'
import { getAndServe } from '@/lib/get-and-serve'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { FitsSparkBadge } from '@/features/recipes/memory-budget-bar'
import { cn } from '@/lib/utils'

type CatalogItem = {
  recipe: Recipe
  model?: InventoryModel
}

type ViewMode = 'cards' | 'rows'
type SortKey = 'smart' | 'speed' | 'active' | 'params' | 'ctx' | 'engine'

const VIEW_KEY = 'spark-catalog-view'
const SORT_KEY = 'spark-catalog-sort'

function isPresent(model?: InventoryModel) {
  return !!(model?.local?.present || model?.status === 'ready')
}

function tokSpeed(item: CatalogItem) {
  return item.recipe.tok_s ?? item.model?.best_bench_tok_s ?? null
}

function activeParams(item: CatalogItem) {
  return item.model?.param_active_b ?? item.model?.param_b ?? null
}

function totalParams(item: CatalogItem) {
  return item.model?.param_b ?? null
}

function ctxSize(item: CatalogItem) {
  return (
    item.recipe.context?.presets?.golden?.ctx ??
    item.recipe.context?.default ??
    item.model?.max_context ??
    null
  )
}

/** Natural / smart name: ignore punctuation, numeric-aware, case-insensitive. */
function smartNameKey(item: CatalogItem) {
  const raw = item.recipe.name || item.recipe.id || ''
  return raw
    .toLowerCase()
    .replace(/[_\-./]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function smartCompare(a: string, b: string) {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })
}

function compareItems(a: CatalogItem, b: CatalogItem, sort: SortKey) {
  if (sort === 'speed') {
    const av = tokSpeed(a)
    const bv = tokSpeed(b)
    if (av == null && bv == null) return smartCompare(smartNameKey(a), smartNameKey(b))
    if (av == null) return 1
    if (bv == null) return -1
    return bv - av
  }
  if (sort === 'active') {
    const av = activeParams(a)
    const bv = activeParams(b)
    if (av == null && bv == null) return smartCompare(smartNameKey(a), smartNameKey(b))
    if (av == null) return 1
    if (bv == null) return -1
    return av - bv
  }
  if (sort === 'params') {
    const av = totalParams(a)
    const bv = totalParams(b)
    if (av == null && bv == null) return smartCompare(smartNameKey(a), smartNameKey(b))
    if (av == null) return 1
    if (bv == null) return -1
    return av - bv
  }
  if (sort === 'ctx') {
    const av = ctxSize(a)
    const bv = ctxSize(b)
    if (av == null && bv == null) return smartCompare(smartNameKey(a), smartNameKey(b))
    if (av == null) return 1
    if (bv == null) return -1
    return bv - av
  }
  if (sort === 'engine') {
    const eng = (item: CatalogItem) => (item.recipe.engine || '').toLowerCase()
    const c = eng(a).localeCompare(eng(b))
    return c || smartCompare(smartNameKey(a), smartNameKey(b))
  }
  return smartCompare(smartNameKey(a), smartNameKey(b))
}

export function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([])
  const [models, setModels] = useState<InventoryModel[]>([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<CatalogItem | null>(null)
  const [alsoBench, setAlsoBench] = useState(false)
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const [error, setError] = useState('')
  const [operationDone, setOperationDone] = useState<'download_started' | 'ready' | null>(null)
  const [view, setView] = useState<ViewMode>(() => {
    const v = localStorage.getItem(VIEW_KEY)
    return v === 'rows' || v === 'cards' ? v : 'cards'
  })
  const [sort, setSort] = useState<SortKey>(() => {
    const v = localStorage.getItem(SORT_KEY)
    return v === 'speed' || v === 'active' || v === 'params' || v === 'ctx' || v === 'engine' || v === 'smart'
      ? v
      : 'smart'
  })
  const [downloadedOnly, setDownloadedOnly] = useState(false)
  const [engineFilter, setEngineFilter] = useState<'all' | 'eugr' | 'llama' | 'ds4'>('all')

  useEffect(() => {
    localStorage.setItem(VIEW_KEY, view)
  }, [view])

  useEffect(() => {
    localStorage.setItem(SORT_KEY, sort)
  }, [sort])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError('')
      try {
        const [recipes, inventory] = await Promise.all([getRecipes(), getInventory()])
        const byPath = new Map(inventory.models.map((m) => [m.rel_path || m.id, m]))
        const golden = recipes
          .filter((r) => (r.tags || []).includes('golden') || r.lifecycle === 'works')
          .map((recipe) => ({
            recipe,
            model: recipe.inventory_path ? byPath.get(recipe.inventory_path) : undefined,
          }))
        if (!cancelled) {
          setModels(inventory.models)
          setItems(golden)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = items.filter(({ recipe, model }) => {
      if (downloadedOnly && !isPresent(model)) return false
      const eng = recipe.engine === 'llamacpp' ? 'llama' : recipe.engine
      if (engineFilter !== 'all' && eng !== engineFilter) return false
      if (!q) return true
      return [recipe.name, recipe.id, recipe.engine, model?.hf_repo, recipe.inventory_path, model?.lab]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    })
    return [...list].sort((a, b) => compareItems(a, b, sort))
  }, [items, query, downloadedOnly, engineFilter, sort])

  function openServe(item: CatalogItem) {
    setSelected(item)
    setAlsoBench(false)
    setLog([])
    setOperationDone(null)
  }

  async function runGetAndServe() {
    if (!selected) return
    setBusy(true)
    setLog([])
    try {
      const result = await getAndServe({
        recipe: selected.recipe,
        model: selected.model,
        alsoBench,
        onStep: (message) => setLog((prev) => [...prev, message]),
      })
      setOperationDone(result.status)
    } catch (err) {
      setLog((prev) => [...prev, `Error: ${err instanceof Error ? err.message : String(err)}`])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Catalog</h1>
        <p className="max-w-2xl text-muted-foreground">
          Benchmark-proven recipes. Start missing downloads, then serve on the gateway when the weights are ready.
        </p>
      </header>

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative min-w-[220px] flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-9"
              placeholder="Search golden recipes…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="inline-flex rounded-md border p-0.5">
            <Button
              size="sm"
              variant={view === 'cards' ? 'secondary' : 'ghost'}
              className="gap-1.5"
              onClick={() => setView('cards')}
            >
              <LayoutGrid className="h-4 w-4" />
              Cards
            </Button>
            <Button
              size="sm"
              variant={view === 'rows' ? 'secondary' : 'ghost'}
              className="gap-1.5"
              onClick={() => setView('rows')}
            >
              <List className="h-4 w-4" />
              Rows
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <ArrowDownWideNarrow className="h-4 w-4 text-muted-foreground" />
            <select
              className="h-9 rounded-md border border-input bg-background px-3 text-sm"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortKey)}
              aria-label="Sort catalog"
            >
              <option value="smart">Name (smart)</option>
              <option value="speed">Speed (tok/s)</option>
              <option value="active">Active params</option>
              <option value="params">Total params</option>
              <option value="ctx">Context window</option>
              <option value="engine">Engine</option>
            </select>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 rounded-md border px-3 py-2">
            <Checkbox
              id="downloaded-only"
              checked={downloadedOnly}
              onCheckedChange={(v) => setDownloadedOnly(v === true)}
            />
            <Label htmlFor="downloaded-only" className="cursor-pointer">
              On disk only
            </Label>
          </div>
          <div className="flex flex-wrap gap-1">
            {(
              [
                ['all', 'Any engine'],
                ['eugr', 'eugr'],
                ['llama', 'llama'],
                ['ds4', 'ds4'],
              ] as const
            ).map(([id, label]) => (
              <Button
                key={id}
                size="sm"
                variant={engineFilter === id ? 'secondary' : 'ghost'}
                onClick={() => setEngineFilter(id)}
              >
                {label}
              </Button>
            ))}
          </div>
          <span className="text-xs text-muted-foreground">
            {filtered.length} of {items.length}
          </span>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-5 text-sm">
          <div className="font-medium text-warning">Catalog unavailable</div>
          <p className="mt-1 text-muted-foreground">{error}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            Live data is no longer replaced with demo models. Check the inference API and inventory build.
          </p>
        </div>
      ) : loading ? (
        <p className="text-sm text-muted-foreground">Loading catalog…</p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-muted-foreground">No recipes match these filters.</p>
      ) : view === 'cards' ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {filtered.map((item) => (
            <CatalogCard key={item.recipe.id} item={item} models={models} onServe={() => openServe(item)} />
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-left text-sm">
              <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <SortHeader label="Name" active={sort === 'smart'} onClick={() => setSort('smart')} />
                  <th className="px-4 py-3 font-medium">Model</th>
                  <SortHeader label="Engine" active={sort === 'engine'} onClick={() => setSort('engine')} />
                  <SortHeader label="tok/s" active={sort === 'speed'} onClick={() => setSort('speed')} align="right" />
                  <SortHeader label="Active" active={sort === 'active'} onClick={() => setSort('active')} align="right" />
                  <SortHeader label="Params" active={sort === 'params'} onClick={() => setSort('params')} align="right" />
                  <SortHeader label="Ctx" active={sort === 'ctx'} onClick={() => setSort('ctx')} align="right" />
                  <th className="px-4 py-3 font-medium">Disk</th>
                  <th className="px-4 py-3 font-medium" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => {
                  const { recipe, model } = item
                  const present = isPresent(model)
                  const tok = tokSpeed(item)
                  const active = activeParams(item)
                  const params = totalParams(item)
                  const ctx = ctxSize(item)
                  return (
                    <tr key={recipe.id} className="border-b last:border-0 hover:bg-muted/40">
                      <td className="px-4 py-3 align-top">
                        <div className="font-medium">{recipe.name}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">{recipe.id}</div>
                      </td>
                      <td className="px-4 py-3 align-top font-mono text-xs">
                        {recipe.inventory_path || '—'}
                      </td>
                      <td className="px-4 py-3 align-top">
                        <Badge variant="outline">{recipe.engine === 'llamacpp' ? 'llama' : recipe.engine}</Badge>
                      </td>
                      <td className="px-4 py-3 align-top text-right tabular-nums">
                        {tok != null ? tok : '—'}
                      </td>
                      <td className="px-4 py-3 align-top text-right tabular-nums">
                        {active != null ? `${active}B` : '—'}
                      </td>
                      <td className="px-4 py-3 align-top text-right tabular-nums">
                        {params != null ? `${params}B` : '—'}
                      </td>
                      <td className="px-4 py-3 align-top text-right tabular-nums">
                        {ctx != null ? ctx.toLocaleString() : '—'}
                      </td>
                      <td className="px-4 py-3 align-top">
                        <Badge variant={present ? 'success' : 'warning'}>
                          {present ? 'on disk' : 'download'}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 align-top text-right">
                        <Button size="sm" onClick={() => openServe(item)}>
                          <Play className="h-3.5 w-3.5" />
                          Serve
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Dialog open={!!selected} onOpenChange={(open) => !open && !busy && setSelected(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{selected && isPresent(selected.model) ? 'Serve model' : 'Get model weights'}</DialogTitle>
            <DialogDescription>
              {selected && isPresent(selected.model)
                ? 'Switch inference to this benchmarked recipe and wait until it is ready on the gateway.'
                : 'Start the weight download now. You can serve this recipe after the download queue finishes.'}
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-4">
              <div className="rounded-lg border bg-muted/40 p-3 text-sm">
                <div className="font-medium">{selected.recipe.name}</div>
                <div className="font-mono text-xs text-muted-foreground">{selected.recipe.id}</div>
              </div>
              {isPresent(selected.model) && (
                <div className="flex items-center gap-2">
                  <Checkbox
                    id="also-bench"
                    checked={alsoBench}
                    onCheckedChange={(v) => setAlsoBench(v === true)}
                    disabled={busy}
                  />
                  <Label htmlFor="also-bench">Also run golden bench after the engine is ready</Label>
                </div>
              )}
              {log.length > 0 && (
                <ScrollArea className="h-36 rounded-md border bg-muted/30 p-3 font-mono text-xs">
                  {log.map((line, i) => (
                    <div key={`${i}-${line}`}>{line}</div>
                  ))}
                </ScrollArea>
              )}
            </div>
          )}
          <DialogFooter>
            {operationDone ? (
              <Button onClick={() => setSelected(null)}>Done</Button>
            ) : (
              <>
                <Button variant="outline" disabled={busy} onClick={() => setSelected(null)}>
                  Cancel
                </Button>
                <Button disabled={busy} onClick={runGetAndServe}>
                  {selected && isPresent(selected.model) ? <Play className="h-4 w-4" /> : <Download className="h-4 w-4" />}
                  {busy ? 'Working…' : selected && isPresent(selected.model) ? 'Serve now' : 'Start download'}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function SortHeader({
  label,
  active,
  onClick,
  align = 'left',
}: {
  label: string
  active: boolean
  onClick: () => void
  align?: 'left' | 'right'
}) {
  return (
    <th className={cn('px-4 py-3 font-medium', align === 'right' && 'text-right')}>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'inline-flex items-center gap-1 hover:text-foreground',
          active ? 'text-foreground' : 'text-muted-foreground',
          align === 'right' && 'flex-row-reverse',
        )}
      >
        {label}
        {active && <span className="text-[10px]">▼</span>}
      </button>
    </th>
  )
}

function CatalogCard({
  item,
  models,
  onServe,
}: {
  item: CatalogItem
  models: InventoryModel[]
  onServe: () => void
}) {
  const { recipe, model } = item
  const present = isPresent(model)
  const tok = tokSpeed(item)
  const active = activeParams(item)
  const golden = recipe.context?.presets?.golden
  const fitCtx = golden?.ctx ?? recipe.context?.default ?? model?.max_context ?? 32768
  const fitKv = golden?.kv ?? recipe.context?.kv_default ?? 'fp8'
  const draftPath = recipe.speculative?.sidecar_inventory
  const draft = draftPath
    ? models.find((m) => (m.rel_path || m.id) === draftPath)
    : undefined
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle>{recipe.name}</CardTitle>
          <Badge variant="success">golden</Badge>
        </div>
        <CardDescription className="font-mono text-xs">{recipe.id}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary">{recipe.engine === 'llamacpp' ? 'llama' : recipe.engine}</Badge>
          {tok != null && <Badge variant="outline">{tok} tok/s</Badge>}
          {active != null && <Badge variant="outline">{active}B active</Badge>}
          <Badge variant={present ? 'success' : 'warning'}>
            {present ? 'on disk' : 'needs download'}
          </Badge>
          <FitsSparkBadge
            input={{
              model,
              draft,
              ctx: fitCtx,
              kv: fitKv,
              speculative: !!recipe.speculative,
              engine: recipe.engine,
            }}
          />
        </div>
        {golden && (
          <p className="text-muted-foreground">
            {golden.label || 'Golden'}: ctx {golden.ctx?.toLocaleString()} · kv {golden.kv}
          </p>
        )}
      </CardContent>
      <CardFooter className="mt-auto">
        <Button className="w-full" onClick={onServe}>
          {present ? <Play className="h-4 w-4" /> : <Download className="h-4 w-4" />}
          {present ? 'Serve' : 'Get weights'}
        </Button>
      </CardFooter>
    </Card>
  )
}
