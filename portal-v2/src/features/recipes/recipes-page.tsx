import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowDown, ArrowDownWideNarrow, ArrowLeft, ArrowUp, Info, Loader2, Pencil, Play, Plus, Search } from 'lucide-react'
import {
  discardRecipe,
  getInferenceStatus,
  getInventory,
  getRecipes,
  markRecipeTesting,
  promoteRecipe,
  runBench,
  scaffoldRecipe,
  switchProfile,
  updateRecipe,
} from '@/lib/api/client'
import type { InventoryModel, Recipe } from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { MemoryBudgetBar } from '@/features/recipes/memory-budget-bar'
import { ModelFactsPanel } from '@/features/recipes/model-facts-panel'
import { findSidecarsForModel, nativeContext } from '@/lib/sidecars'

type LifeFilter = 'all' | 'works' | 'testing' | 'draft' | 'failed'
type EngineFilter = 'all' | 'eugr' | 'llama' | 'ds4'
type SortKey = 'smart' | 'model' | 'speed' | 'ctx' | 'active' | 'params' | 'engine' | 'lifecycle'
type SortDirection = 'asc' | 'desc'

const RECIPE_SORT_KEY = 'spark-recipes-sort'
const RECIPE_SORT_DIRECTION_KEY = 'spark-recipes-sort-direction'

function isSortKey(value: string | null): value is SortKey {
  return value === 'smart'
    || value === 'model'
    || value === 'speed'
    || value === 'ctx'
    || value === 'active'
    || value === 'params'
    || value === 'engine'
    || value === 'lifecycle'
}

function normalizeEngine(engine?: string) {
  if (!engine) return ''
  if (engine === 'llamacpp') return 'llama'
  return engine
}

function lifeTone(lifecycle?: string): 'success' | 'warning' | 'secondary' | 'outline' {
  if (lifecycle === 'works' || lifecycle === 'production') return 'success'
  if (lifecycle === 'testing') return 'warning'
  if (lifecycle === 'failed') return 'outline'
  return 'secondary'
}

function findModel(models: InventoryModel[], path?: string) {
  if (!path) return undefined
  return models.find((m) => (m.rel_path || m.id) === path)
}

function recipeSortValue(recipe: Recipe, models: InventoryModel[], key: SortKey) {
  const model = findModel(models, recipe.inventory_path)
  if (key === 'smart') return recipe.name || recipe.id
  if (key === 'model') return recipe.inventory_path || ''
  if (key === 'engine') return normalizeEngine(recipe.engine)
  if (key === 'lifecycle') return recipe.lifecycle || 'works'
  if (key === 'speed') return recipe.tok_s ?? model?.best_bench_tok_s ?? null
  if (key === 'ctx') {
    return recipe.context?.presets?.golden?.ctx ?? recipe.context?.default ?? model?.max_context ?? null
  }
  if (key === 'active') return model?.param_active_b ?? model?.param_b ?? null
  if (key === 'params') return model?.param_b ?? null
  return null
}

function defaultSortDirection(key: SortKey): SortDirection {
  return key === 'speed' || key === 'ctx' ? 'desc' : 'asc'
}

function compareRecipes(
  a: Recipe,
  b: Recipe,
  models: InventoryModel[],
  sort: SortKey,
  direction: SortDirection,
) {
  const aValue = recipeSortValue(a, models, sort)
  const bValue = recipeSortValue(b, models, sort)
  if (aValue == null && bValue == null) return (a.name || a.id).localeCompare(b.name || b.id)
  if (aValue == null) return 1
  if (bValue == null) return -1
  const order = typeof aValue === 'number' && typeof bValue === 'number'
    ? aValue - bValue
    : String(aValue).localeCompare(String(bValue), undefined, { numeric: true, sensitivity: 'base' })
  if (order !== 0) return direction === 'asc' ? order : -order
  return (a.name || a.id).localeCompare(b.name || b.id, undefined, { numeric: true, sensitivity: 'base' })
}

function SortableHeader({
  label,
  sortKey,
  sort,
  direction,
  onSort,
  className,
}: {
  label: string
  sortKey: SortKey
  sort: SortKey
  direction: SortDirection
  onSort: (key: SortKey) => void
  className?: string
}) {
  const active = sort === sortKey
  return (
    <th
      className={cn('px-3 py-3 font-medium', className)}
      aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        className={cn(
          'inline-flex items-center gap-1 whitespace-nowrap transition-colors hover:text-foreground',
          active && 'text-foreground',
        )}
        onClick={() => onSort(sortKey)}
      >
        {label}
        {active
          ? direction === 'asc'
            ? <ArrowUp className="h-3 w-3" />
            : <ArrowDown className="h-3 w-3" />
          : <ArrowDownWideNarrow className="h-3 w-3 opacity-35" />}
      </button>
    </th>
  )
}

export function RecipesPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const createPath = params.get('create')
  const selectedId = params.get('recipe')
  const studioMode = createPath != null || !!selectedId

  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [models, setModels] = useState<InventoryModel[]>([])
  const [query, setQuery] = useState('')
  const [life, setLife] = useState<LifeFilter>('all')
  const [engine, setEngine] = useState<EngineFilter>('all')
  const [sort, setSort] = useState<SortKey>(() => {
    const saved = localStorage.getItem(RECIPE_SORT_KEY)
    return isSortKey(saved) ? saved : 'smart'
  })
  const [sortDirection, setSortDirection] = useState<SortDirection>(() => {
    const savedDirection = localStorage.getItem(RECIPE_SORT_DIRECTION_KEY)
    if (savedDirection === 'asc' || savedDirection === 'desc') return savedDirection
    const savedSort = localStorage.getItem(RECIPE_SORT_KEY)
    return defaultSortDirection(isSortKey(savedSort) ? savedSort : 'smart')
  })
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [activeProfile, setActiveProfile] = useState<string | null>(null)
  const [startingProfile, setStartingProfile] = useState<string | null>(null)
  const [servingId, setServingId] = useState<string | null>(null)
  const [error, setError] = useState('')

  async function refresh() {
    setLoading(true)
    setError('')
    try {
      const [list, inv, status] = await Promise.all([
        getRecipes(),
        getInventory(),
        getInferenceStatus(true).catch(() => null),
      ])
      setRecipes(list)
      setModels(inv.models)
      setActiveProfile(status?.active?.profile || status?.active?.id || null)
      setStartingProfile(status?.switch?.running ? status.switch.profile || null : null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  useEffect(() => {
    localStorage.setItem(RECIPE_SORT_KEY, sort)
    localStorage.setItem(RECIPE_SORT_DIRECTION_KEY, sortDirection)
  }, [sort, sortDirection])

  useEffect(() => {
    if (!startingProfile) return
    let cancelled = false
    const timer = window.setInterval(() => {
      void getInferenceStatus(true).then((status) => {
        if (cancelled) return
        const active = status.active?.profile || status.active?.id || null
        const starting = status.switch?.running ? status.switch.profile || startingProfile : null
        setActiveProfile(active)
        setStartingProfile(starting)
        if (!starting && active === startingProfile) {
          setMessage(`${startingProfile} is now serving.`)
        }
      }).catch(() => undefined)
    }, 2000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [startingProfile])

  function changeSort(key: SortKey) {
    if (key === sort) {
      setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')
      return
    }
    setSort(key)
    setSortDirection(defaultSortDirection(key))
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const matches = recipes.filter((r) => {
      const lc = r.lifecycle || 'works'
      if (life === 'works' && lc !== 'works' && lc !== 'production') return false
      if (life === 'testing' && lc !== 'testing') return false
      if (life === 'draft' && lc !== 'draft') return false
      if (life === 'failed' && lc !== 'failed') return false
      const eng = normalizeEngine(r.engine)
      if (engine !== 'all' && eng !== engine) return false
      if (!q) return true
      return [r.id, r.name, r.engine, r.lifecycle, r.inventory_path, r.notes, ...(r.tags || [])]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    })
    return matches.sort((a, b) => compareRecipes(a, b, models, sort, sortDirection))
  }, [recipes, models, query, life, engine, sort, sortDirection])

  const counts = useMemo(() => {
    const c = { all: recipes.length, works: 0, testing: 0, draft: 0, failed: 0 }
    for (const r of recipes) {
      const lc = r.lifecycle || 'works'
      if (lc === 'works' || lc === 'production') c.works++
      else if (lc === 'testing') c.testing++
      else if (lc === 'draft') c.draft++
      else if (lc === 'failed') c.failed++
    }
    return c
  }, [recipes])

  const selected = recipes.find((r) => r.id === selectedId) || null

  function openRecipe(id: string) {
    const next = new URLSearchParams()
    next.set('recipe', id)
    setParams(next)
  }

  function openCreate(path = '') {
    const next = new URLSearchParams()
    next.set('create', path)
    setParams(next)
  }

  function backToList() {
    setParams(new URLSearchParams())
    setMessage('')
  }

  async function serveRecipe(recipe: Recipe) {
    if (recipe.switchable === false || servingId || startingProfile) return
    const heavy = recipe.tier === 'heavy'
    if (
      heavy
      && !window.confirm(`Load the heavy recipe “${recipe.name || recipe.id}”? This can take several minutes and replaces the active engine.`)
    ) return
    setServingId(recipe.id)
    setMessage(`Starting ${recipe.name || recipe.id}…`)
    try {
      await switchProfile(recipe.id, heavy)
      setStartingProfile(recipe.id)
      setMessage(`${recipe.name || recipe.id} is starting. The active engine will switch when it is ready.`)
    } catch (err) {
      setMessage(`Serve failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setServingId(null)
    }
  }

  async function act(label: string, fn: () => Promise<unknown>, confirmMessage?: string) {
    if (confirmMessage && !window.confirm(confirmMessage)) return
    setBusy(true)
    setMessage(`${label}…`)
    try {
      await fn()
      setMessage(`${label} ok`)
      await refresh()
    } catch (err) {
      setMessage(`${label} failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy(false)
    }
  }

  if (studioMode && loading) {
    return <p className="text-sm text-muted-foreground">Loading recipe studio…</p>
  }

  if (studioMode && error) {
    return (
      <div className="rounded-xl border border-warning/40 bg-warning/10 p-5 text-sm">
        <div className="font-medium text-warning">Recipe studio unavailable</div>
        <p className="mt-1 text-muted-foreground">{error}</p>
        <Button className="mt-3" size="sm" variant="outline" onClick={() => void refresh()}>
          Try again
        </Button>
      </div>
    )
  }

  if (studioMode && createPath == null && !selected) {
    return (
      <div className="rounded-xl border border-dashed p-8 text-center">
        <h1 className="text-lg font-semibold">Recipe not found</h1>
        <p className="mt-1 text-sm text-muted-foreground">{selectedId}</p>
        <Button className="mt-4" variant="outline" onClick={backToList}>
          Back to recipes
        </Button>
      </div>
    )
  }

  if (studioMode) {
    return (
      <RecipeStudio
        mode={createPath != null ? 'create' : 'edit'}
        createPath={createPath || ''}
        recipe={selected}
        models={models}
        busy={busy}
        message={message}
        onBack={backToList}
        onBusy={setBusy}
        onMessage={setMessage}
        onCreated={async (id) => {
          await refresh()
          openRecipe(id)
        }}
        onSaved={async () => {
          await refresh()
        }}
        onAct={act}
      />
    )
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">Recipes</h1>
          <p className="max-w-2xl text-muted-foreground">
            Search every profile, open one to edit against its model facts, or start a new recipe from a
            model already in the library.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => navigate('/library')}>
            From Library
          </Button>
          <Button onClick={() => openCreate('')}>
            <Plus className="h-4 w-4" />
            New recipe
          </Button>
        </div>
      </header>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full max-w-xl">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            placeholder="Search recipes by name, id, model path, notes, tags…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {(
            [
              ['all', `All ${counts.all}`],
              ['works', `Works ${counts.works}`],
              ['testing', `Testing ${counts.testing}`],
              ['draft', `Drafts ${counts.draft}`],
              ['failed', `Failed ${counts.failed}`],
            ] as const
          ).map(([id, label]) => (
            <Button key={id} size="sm" variant={life === id ? 'default' : 'outline'} onClick={() => setLife(id)}>
              {label}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {(
            [
              ['all', 'Any engine'],
              ['eugr', 'eugr'],
              ['llama', 'llama'],
              ['ds4', 'ds4'],
            ] as const
          ).map(([id, label]) => (
            <Button key={id} size="sm" variant={engine === id ? 'secondary' : 'ghost'} onClick={() => setEngine(id)}>
              {label}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <ArrowDownWideNarrow className="h-4 w-4 text-muted-foreground" />
          <select
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={sort}
            onChange={(event) => {
              const key = event.target.value as SortKey
              setSort(key)
              setSortDirection(defaultSortDirection(key))
            }}
            aria-label="Sort recipes"
          >
            <option value="smart">Recipe</option>
            <option value="model">Model</option>
            <option value="engine">Engine</option>
            <option value="lifecycle">Lifecycle</option>
            <option value="ctx">Context</option>
            <option value="active">Active params</option>
            <option value="params">Total params</option>
            <option value="speed">Speed</option>
          </select>
          <Button
            type="button"
            size="icon"
            variant="outline"
            aria-label={`Sort ${sortDirection === 'asc' ? 'descending' : 'ascending'}`}
            onClick={() => setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')}
          >
            {sortDirection === 'asc' ? <ArrowUp /> : <ArrowDown />}
          </Button>
        </div>
      </div>

      {message && <p className="text-sm text-muted-foreground">{message}</p>}

      {error ? (
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-5 text-sm">
          <div className="font-medium text-warning">Recipes unavailable</div>
          <p className="mt-1 text-muted-foreground">{error}</p>
          <Button className="mt-3" size="sm" variant="outline" onClick={() => void refresh()}>
            Try again
          </Button>
        </div>
      ) : loading ? (
        <p className="text-sm text-muted-foreground">Loading recipes…</p>
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="w-full">
            <table className="w-full table-fixed text-left text-sm">
              <colgroup>
                <col />
                <col className="hidden w-[24%] 2xl:table-column" />
                <col className="hidden w-20 sm:table-column" />
                <col className="w-24" />
                <col className="hidden w-20 md:table-column" />
                <col className="hidden w-20 xl:table-column" />
                <col className="hidden w-20 xl:table-column" />
                <col className="w-20" />
                <col className="hidden w-40 md:table-column" />
              </colgroup>
              <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
                <tr>
                  <SortableHeader label="Recipe" sortKey="smart" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <SortableHeader className="hidden 2xl:table-cell" label="Model" sortKey="model" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <SortableHeader className="hidden sm:table-cell" label="Engine" sortKey="engine" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <SortableHeader label="Lifecycle" sortKey="lifecycle" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <SortableHeader className="hidden md:table-cell" label="Ctx" sortKey="ctx" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <SortableHeader className="hidden xl:table-cell" label="Active" sortKey="active" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <SortableHeader className="hidden xl:table-cell" label="Total" sortKey="params" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <SortableHeader label="tok/s" sortKey="speed" sort={sort} direction={sortDirection} onSort={changeSort} />
                  <th className="hidden px-3 py-3 font-medium md:table-cell">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-10 text-center text-muted-foreground">
                      No recipes match. Try clearing filters or create one from Library.
                    </td>
                  </tr>
                )}
                {filtered.map((r) => {
                  const model = findModel(models, r.inventory_path)
                  const isActive = activeProfile === r.id
                  const isStarting = startingProfile === r.id || servingId === r.id
                  const serveDisabled = (
                    r.switchable === false
                    || isActive
                    || servingId != null
                    || startingProfile != null
                  )
                  return (
                    <tr
                      key={r.id}
                      className={cn('border-b last:border-0', isActive && 'bg-primary/[0.04]')}
                    >
                      <td className="min-w-0 px-3 py-3 align-top">
                        <div className="flex min-w-0 items-center gap-2">
                          <div className="truncate font-medium" title={r.name}>{r.name}</div>
                          {isActive && <Badge variant="success" className="shrink-0 text-[10px]">serving</Badge>}
                        </div>
                        <div className="truncate font-mono text-[11px] text-muted-foreground" title={r.id}>{r.id}</div>
                        <div className="truncate font-mono text-[11px] text-muted-foreground 2xl:hidden" title={r.inventory_path}>
                          {r.inventory_path || '—'}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {(r.tags || []).slice(0, 3).map((t) => (
                            <Badge key={t} variant={t === 'golden' ? 'success' : 'secondary'} className="text-[10px]">
                              {t}
                            </Badge>
                          ))}
                        </div>
                        <div className="mt-2 flex gap-2 md:hidden">
                          <Button
                            size="sm"
                            disabled={serveDisabled}
                            title={r.switchable === false ? 'This recipe is not switchable yet' : undefined}
                            onClick={() => void serveRecipe(r)}
                          >
                            {isStarting ? <Loader2 className="animate-spin" /> : <Play />}
                            {isActive ? 'Serving' : isStarting ? 'Starting' : 'Serve'}
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => openRecipe(r.id)}>
                            <Pencil />
                            Edit
                          </Button>
                        </div>
                      </td>
                      <td className="hidden min-w-0 px-3 py-3 align-top 2xl:table-cell">
                        <div className="truncate font-mono text-xs" title={r.inventory_path}>{r.inventory_path || '—'}</div>
                        {model?.lab && (
                          <div className="text-xs text-muted-foreground">{model.lab}</div>
                        )}
                      </td>
                      <td className="hidden px-3 py-3 align-top sm:table-cell">
                        <Badge variant="outline">{normalizeEngine(r.engine) || r.engine}</Badge>
                      </td>
                      <td className="px-3 py-3 align-top">
                        <Badge variant={lifeTone(r.lifecycle)}>{r.lifecycle || 'works'}</Badge>
                      </td>
                      <td className="hidden whitespace-nowrap px-3 py-3 align-top text-muted-foreground tabular-nums md:table-cell">
                        {r.context?.presets?.golden?.ctx?.toLocaleString() ||
                          r.context?.default?.toLocaleString() ||
                          '—'}
                      </td>
                      <td className="hidden px-3 py-3 align-top text-muted-foreground tabular-nums xl:table-cell">
                        {model?.param_active_b != null
                          ? `${model.param_active_b}B`
                          : model?.param_b != null
                            ? `${model.param_b}B`
                            : '—'}
                      </td>
                      <td className="hidden px-3 py-3 align-top text-muted-foreground tabular-nums xl:table-cell">
                        {model?.param_b != null ? `${model.param_b}B` : '—'}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 align-top text-muted-foreground tabular-nums">
                        {r.tok_s ?? model?.best_bench_tok_s ?? '—'}
                      </td>
                      <td className="hidden px-3 py-3 align-top text-right md:table-cell">
                        <div className="flex justify-end gap-1">
                          <Button
                            size="sm"
                            disabled={serveDisabled}
                            title={r.switchable === false ? 'This recipe is not switchable yet' : undefined}
                            onClick={() => void serveRecipe(r)}
                          >
                            {isStarting ? <Loader2 className="animate-spin" /> : <Play />}
                            {isActive ? 'Serving' : isStarting ? 'Starting' : 'Serve'}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => openRecipe(r.id)}>
                            <Pencil />
                            Edit
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

type StudioProps = {
  mode: 'create' | 'edit'
  createPath: string
  recipe: Recipe | null
  models: InventoryModel[]
  busy: boolean
  message: string
  onBack: () => void
  onBusy: (v: boolean) => void
  onMessage: (v: string) => void
  onCreated: (id: string) => Promise<void>
  onSaved: () => Promise<void>
  onAct: (label: string, fn: () => Promise<unknown>, confirmMessage?: string) => Promise<void>
}

function RecipeStudio({
  mode,
  createPath,
  recipe,
  models,
  busy,
  message,
  onBack,
  onBusy,
  onMessage,
  onCreated,
  onSaved,
  onAct,
}: StudioProps) {
  const inventoryPath = mode === 'create' ? createPath : recipe?.inventory_path || ''
  const model = findModel(models, inventoryPath)

  const [path, setPath] = useState(inventoryPath)
  const [name, setName] = useState('')
  const [notes, setNotes] = useState('')
  const [tier, setTier] = useState<'fast' | 'heavy' | 'experimental'>('heavy')
  const [engine, setEngine] = useState<'auto' | 'eugr' | 'llamacpp' | 'ds4'>('auto')
  const [ctx, setCtx] = useState<number>(32768)
  const [kv, setKv] = useState('auto')
  const [useGolden, setUseGolden] = useState(true)
  const [specOn, setSpecOn] = useState(false)
  const [sidecar, setSidecar] = useState('')
  const [specTokens, setSpecTokens] = useState(10)
  const [specDismissed, setSpecDismissed] = useState(false)

  useEffect(() => {
    if (mode === 'create') {
      const m = findModel(models, createPath)
      setPath(createPath)
      setName(m?.name || createPath.split('/').pop() || '')
      setNotes('')
      setTier((m?.param_b || 0) >= 20 ? 'heavy' : 'fast')
      const sug = (m?.engines || [])[0]
      setEngine(sug === 'llama' ? 'llamacpp' : sug === 'eugr' || sug === 'ds4' ? sug : 'auto')
      const native = nativeContext(m)
      // Prefer a safer default when native is huge; user can raise to native.
      setCtx(native != null ? Math.min(native, native > 65536 ? 32768 : native) : 32768)
      setKv(sug === 'llama' || sug === 'llamacpp' ? 'q8_0' : 'fp8')
      setUseGolden(true)
      setSpecOn(false)
      setSidecar('')
      setSpecTokens(10)
      setSpecDismissed(false)
      return
    }
    if (!recipe) return
    setPath(recipe.inventory_path || '')
    setName(recipe.name || '')
    setNotes(recipe.notes || '')
    setTier((recipe.tier as typeof tier) || 'heavy')
    setEngine(
      recipe.engine === 'llama' || recipe.engine === 'llamacpp'
        ? 'llamacpp'
        : recipe.engine === 'ds4'
          ? 'ds4'
          : recipe.engine === 'eugr'
            ? 'eugr'
            : 'auto',
    )
    setCtx(recipe.context?.default || recipe.context?.presets?.golden?.ctx || 32768)
    setKv(recipe.context?.kv_default || recipe.context?.presets?.golden?.kv || 'auto')
    setUseGolden(!!recipe.context?.presets?.golden)
    setSpecOn(!!recipe.speculative)
    setSidecar(recipe.speculative?.sidecar_inventory || '')
    setSpecTokens(recipe.speculative?.num_speculative_tokens || 10)
    setSpecDismissed(false)
  }, [mode, createPath, recipe, models])

  const modelOptions = models
    .filter((m) => m.local?.present || m.status === 'ready')
    .map((m) => m.rel_path || m.id)

  const activePath = path || inventoryPath
  const activeModel = findModel(models, activePath) || model
  const suggestedSidecars = useMemo(
    () => findSidecarsForModel(models, activePath),
    [models, activePath],
  )
  const primarySidecar = suggestedSidecars[0]
  const primarySidecarPath = primarySidecar ? primarySidecar.rel_path || primarySidecar.id : ''
  const showSpecSuggest =
    !!primarySidecarPath && !specDismissed && (!specOn || sidecar !== primarySidecarPath)

  const nativeCtx = nativeContext(activeModel, recipe?.context?.native)
  // Max supported on this model card = advertised native (fit may be lower after bench).
  const maxSupportedCtx = nativeCtx
  const ctxHint =
    nativeCtx != null
      ? `Native ${nativeCtx.toLocaleString()} · max supported ${maxSupportedCtx!.toLocaleString()}`
      : 'Native / max supported unknown for this model'

  const draftModel = useMemo(() => {
    if (!specOn || !sidecar) return null
    return findModel(models, sidecar) || null
  }, [specOn, sidecar, models])

  const memoryInput = useMemo(
    () => ({
      model: activeModel || null,
      draft: draftModel,
      ctx,
      kv,
      speculative: specOn,
      engine: mode === 'edit' ? recipe?.engine : engine === 'auto' ? activeModel?.engines?.[0] || 'eugr' : engine,
    }),
    [activeModel, draftModel, ctx, kv, specOn, mode, recipe?.engine, engine],
  )

  function applySuggestedSidecar() {
    if (!primarySidecarPath) return
    setSpecOn(true)
    setSidecar(primarySidecarPath)
    setSpecDismissed(false)
  }

  function formIsValid() {
    if (!Number.isFinite(ctx) || ctx < 1024) {
      onMessage('Context window must be at least 1,024 tokens')
      return false
    }
    if (specOn && !sidecar.trim()) {
      onMessage('Choose a sidecar inventory path or turn speculative decoding off')
      return false
    }
    return true
  }

  async function create() {
    if (!activePath.trim()) {
      onMessage('Pick a model inventory path first')
      return
    }
    if (!formIsValid()) return
    onBusy(true)
    onMessage('Creating draft…')
    try {
      const res = await scaffoldRecipe({
        inventory_path: activePath.trim(),
        engine,
        name: name.trim() || undefined,
        tier,
      })
      const id = res.recipe?.id
      if (id) {
        await updateRecipe({
          profile: id,
          name: name.trim() || undefined,
          notes,
          tier,
          ctx,
          kv,
          golden_ctx: useGolden ? ctx : undefined,
          golden_kv: useGolden ? kv : undefined,
          speculative: specOn
            ? { method: 'dflash', sidecar_inventory: sidecar, num_speculative_tokens: specTokens }
            : false,
        })
        onMessage(`Draft created: ${id}`)
        await onCreated(id)
      } else {
        onMessage('Draft created')
        await onSaved()
        onBack()
      }
    } catch (err) {
      onMessage(`Create failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      onBusy(false)
    }
  }

  async function save() {
    if (!recipe) return
    if (!formIsValid()) return
    onBusy(true)
    onMessage('Saving…')
    try {
      await updateRecipe({
        profile: recipe.id,
        name: name.trim(),
        notes,
        tier,
        ctx,
        kv,
        golden_ctx: useGolden ? ctx : undefined,
        golden_kv: useGolden ? kv : undefined,
        speculative: specOn
          ? { method: 'dflash', sidecar_inventory: sidecar, num_speculative_tokens: specTokens }
          : false,
      })
      onMessage('Saved')
      await onSaved()
    } catch (err) {
      onMessage(`Save failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      onBusy(false)
    }
  }

  const lc = recipe?.lifecycle || (mode === 'create' ? 'draft' : 'works')

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          All recipes
        </Button>
        <Separator orientation="vertical" className="hidden h-6 sm:block" />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {mode === 'create' ? 'New recipe' : 'Edit recipe'}
          </h1>
          <p className="text-sm text-muted-foreground">
            Model facts first, then knobs you can change for this profile.
          </p>
        </div>
      </header>

      {mode === 'create' && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Which model?</CardTitle>
            <CardDescription>Recipe is always for one inventory path under /models.</CardDescription>
          </CardHeader>
          <CardContent>
            <Input
              list="recipe-model-options"
              placeholder="lab/slug"
              value={path}
              onChange={(e) => {
                setPath(e.target.value)
                setSpecDismissed(false)
              }}
            />
            <datalist id="recipe-model-options">
              {modelOptions.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
          </CardContent>
        </Card>
      )}

      {activePath ? (
        <ModelFactsPanel model={activeModel} inventoryPath={activePath} />
      ) : (
        <Card>
          <CardContent className="py-8 text-sm text-muted-foreground">
            Select a model path to see its facts (context, format, maker, links).
          </CardContent>
        </Card>
      )}

      {activePath && <MemoryBudgetBar input={memoryInput} />}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recipe knobs</CardTitle>
          <CardDescription>
            Prefills from the model above. Change only what you want to experiment with.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="rname">Display name</Label>
              <Input id="rname" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="rengine">Engine</Label>
              <select
                id="rengine"
                disabled={mode === 'edit'}
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm disabled:opacity-60"
                value={engine}
                onChange={(e) => setEngine(e.target.value as typeof engine)}
              >
                <option value="auto">Auto-detect</option>
                <option value="eugr">eugr (vLLM)</option>
                <option value="llamacpp">llama.cpp</option>
                <option value="ds4">ds4</option>
              </select>
              {mode === 'edit' && (
                <p className="text-xs text-muted-foreground">Engine is fixed after create — make a new recipe to switch engines.</p>
              )}
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="rtier">Tier</Label>
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        className="inline-flex text-muted-foreground hover:text-foreground"
                        aria-label="What tier means"
                      >
                        <Info className="h-3.5 w-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <p className="font-medium mb-1">Recipe tier</p>
                      <p>
                        <strong>fast</strong> — smaller / quicker swap; agent grunt work.
                      </p>
                      <p>
                        <strong>heavy</strong> — full GPU slot; large MoE or long context.
                      </p>
                      <p>
                        <strong>experimental</strong> — lab recipes; may need special engines or fail.
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        One heavy engine runs at a time on the box.
                      </p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <select
                id="rtier"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={tier}
                onChange={(e) => setTier(e.target.value as typeof tier)}
              >
                <option value="fast">fast</option>
                <option value="heavy">heavy</option>
                <option value="experimental">experimental</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="rctx">Context window</Label>
              <Input
                id="rctx"
                type="number"
                min={1024}
                max={nativeCtx ?? undefined}
                value={ctx}
                onChange={(e) => setCtx(Number(e.target.value) || 0)}
              />
              <p className="text-xs text-muted-foreground">
                {ctxHint}
                {nativeCtx != null && ctx > nativeCtx && (
                  <span className="text-warning"> · above native — engine may clamp or OOM</span>
                )}
                {nativeCtx != null && (
                  <button
                    type="button"
                    className="ml-2 text-primary hover:underline"
                    onClick={() => setCtx(nativeCtx)}
                  >
                    Use native
                  </button>
                )}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="rkv">KV cache</Label>
              <select
                id="rkv"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={kv}
                onChange={(e) => setKv(e.target.value)}
              >
                <option value="auto">auto</option>
                <option value="fp8">fp8</option>
                <option value="q8_0">q8_0</option>
                <option value="q4_0">q4_0</option>
                <option value="f16">f16</option>
              </select>
            </div>
            <div className="sm:col-span-2 flex items-center gap-2">
              <Checkbox
                id="golden"
                checked={useGolden}
                onCheckedChange={(v) => setUseGolden(v === true)}
              />
              <Label htmlFor="golden">Also set golden preset to this ctx / kv</Label>
            </div>
            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="rnotes">Notes</Label>
              <textarea
                id="rnotes"
                className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Why this recipe exists, quirks, bench notes…"
              />
            </div>
          </div>

          <Separator />

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Checkbox id="spec" checked={specOn} onCheckedChange={(v) => setSpecOn(v === true)} />
              <Label htmlFor="spec">Speculative decoding (DFlash / draft model)</Label>
            </div>

            {showSpecSuggest && (
              <div className="flex flex-col gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm">
                  <div className="font-medium">Speculative sidecar found on disk</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {primarySidecarPath}
                    {primarySidecar?.size_human ? ` · ${primarySidecar.size_human}` : ''}
                    {suggestedSidecars.length > 1 ? ` · +${suggestedSidecars.length - 1} more` : ''}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button type="button" size="sm" onClick={applySuggestedSidecar}>
                    Use this
                  </Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setSpecDismissed(true)}>
                    Dismiss
                  </Button>
                </div>
              </div>
            )}

            {!primarySidecarPath && activePath && (
              <p className="text-xs text-muted-foreground">
                No on-disk DFlash/MTP sidecar detected for this model (looked for{' '}
                <code className="text-[11px]">requires_target</code> match or{' '}
                <code className="text-[11px]">z-lab/{'{slug}'}</code>).
              </p>
            )}

            {specOn && (
              <div className="grid gap-4 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2">
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="sidecar">Sidecar inventory path</Label>
                  <Input
                    id="sidecar"
                    list="sidecar-options"
                    placeholder="z-lab/qwen3.6-27b"
                    value={sidecar}
                    onChange={(e) => setSidecar(e.target.value)}
                  />
                  <datalist id="sidecar-options">
                    {(suggestedSidecars.length
                      ? suggestedSidecars.map((s) => s.rel_path || s.id)
                      : modelOptions
                    ).map((p) => (
                      <option key={p} value={p} />
                    ))}
                  </datalist>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="ntok">Speculative tokens (n)</Label>
                  <Input
                    id="ntok"
                    type="number"
                    min={1}
                    max={64}
                    value={specTokens}
                    onChange={(e) => setSpecTokens(Number(e.target.value) || 1)}
                  />
                </div>
              </div>
            )}
          </div>

          {message && <p className="text-sm text-muted-foreground">{message}</p>}

          <div className="flex flex-wrap gap-2">
            {mode === 'create' ? (
              <Button disabled={busy || !activePath.trim()} onClick={() => void create()}>
                {busy ? 'Creating…' : 'Create draft'}
              </Button>
            ) : (
              <>
                <Button disabled={busy} onClick={() => void save()}>
                  {busy ? 'Saving…' : 'Save changes'}
                </Button>
                {lc === 'draft' && (
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => onAct('Mark testing', () => markRecipeTesting(recipe!.id))}
                  >
                    Mark testing
                  </Button>
                )}
                {(lc === 'testing' || lc === 'works' || lc === 'production') && (
                  <>
                    <Button
                      variant="outline"
                      disabled={busy || recipe?.switchable === false}
                      onClick={() =>
                        onAct(
                          'Serve',
                          () => switchProfile(recipe!.id, recipe?.tier === 'heavy'),
                          recipe?.tier === 'heavy'
                            ? `Load the heavy recipe “${recipe.name}”? This can take several minutes and replaces the active engine.`
                            : undefined,
                        )
                      }
                    >
                      Serve
                    </Button>
                    <Button variant="outline" disabled={busy} onClick={() => onAct('Bench', () => runBench())}>
                      Bench
                    </Button>
                  </>
                )}
                {lc === 'testing' && (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      onAct(
                        'Publish',
                        () => promoteRecipe(recipe!.id),
                        `Publish “${recipe!.name}” as a working recipe?`,
                      )
                    }
                  >
                    Publish as works
                  </Button>
                )}
                {(lc === 'draft' || lc === 'testing' || lc === 'failed') && (
                  <Button
                    variant="destructive"
                    disabled={busy}
                    onClick={() =>
                      onAct(
                        'Discard',
                        () => discardRecipe(recipe!.id),
                        `Discard “${recipe!.name}”? This removes the draft recipe.`,
                      )
                    }
                  >
                    Discard
                  </Button>
                )}
              </>
            )}
          </div>

          {mode === 'edit' && (
            <p className={cn('text-xs text-muted-foreground')}>
              Lifecycle: <Badge variant={lifeTone(lc)}>{lc}</Badge>
              {' — '}
              Publish as works moves a tested draft into <code>recipes/</code> and enables Serve switching.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
