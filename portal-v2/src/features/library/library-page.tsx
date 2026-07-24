import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { HardDrive, Search } from 'lucide-react'
import { getInventory, getShelfStatus, shelfPull, shelfPush, shelfRemoveLocal } from '@/lib/api/client'
import type { InventoryModel, ShelfStatus } from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { isSidecarModel } from '@/lib/sidecars'

export function LibraryPage() {
  const navigate = useNavigate()
  const [models, setModels] = useState<InventoryModel[]>([])
  const [shelf, setShelf] = useState<ShelfStatus | null>(null)
  const [query, setQuery] = useState('')
  const [showSidecars, setShowSidecars] = useState(false)
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actingPath, setActingPath] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError('')
    try {
      const [inv, shelfStatus] = await Promise.all([getInventory(), getShelfStatus()])
      setModels(inv.models)
      setShelf(shelfStatus)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  const sidecarCount = useMemo(() => models.filter(isSidecarModel).length, [models])
  const primaryCount = models.length - sidecarCount

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return models.filter((m) => {
      if (!showSidecars && isSidecarModel(m)) return false
      if (!q) return true
      return [m.id, m.lab, m.name, m.hf_repo, m.golden_profile, m.requires_target]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(q))
    })
  }, [models, query, showSidecars])

  async function act(path: string, label: string, fn: () => Promise<unknown>) {
    setActingPath(path)
    setMessage(`${label}…`)
    try {
      await fn()
      setMessage(`${label} queued`)
      await refresh()
    } catch (err) {
      setMessage(`${label} failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setActingPath(null)
    }
  }

  async function removeLocal(model: InventoryModel, path: string) {
    const warning = shelf?.mounted
      ? `Delete the local copy of ${model.lab}/${model.name}? The NAS shelf copy is not affected.`
      : `Delete ${model.lab}/${model.name} from this machine? No mounted shelf copy can be verified.`
    if (!window.confirm(warning)) return
    setActingPath(path)
    setMessage('Remove local…')
    try {
      await shelfRemoveLocal(path)
      setMessage('Local removal queued')
      await refresh()
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err)
      if (
        detail.includes('not on NAS shelf') &&
        window.confirm(
          `${model.lab}/${model.name} is not on the NAS shelf. Delete the only verified local copy anyway?`,
        )
      ) {
        try {
          await shelfRemoveLocal(path, true)
          setMessage('Forced local removal queued')
          await refresh()
        } catch (forceError) {
          setMessage(`Remove local failed: ${forceError instanceof Error ? forceError.message : String(forceError)}`)
        }
      } else {
        setMessage(`Remove local failed: ${detail}`)
      }
    } finally {
      setActingPath(null)
    }
  }

  function openCreateRecipe(model: InventoryModel) {
    const path = model.rel_path || model.id
    navigate(`/recipes?create=${encodeURIComponent(path)}`)
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">Library</h1>
          <p className="max-w-2xl text-muted-foreground">
            Weights on disk and optional NAS shelf. Draft/speculative sidecars stay hidden unless you ask for them —
            they belong to a base model’s recipe, not the main catalog.
          </p>
        </div>
        <Button asChild>
          <Link to="/library/find">Find on Hugging Face</Link>
        </Button>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Models</CardDescription>
            <CardTitle className="text-2xl">{primaryCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Shelf</CardDescription>
            <CardTitle className="text-2xl">{shelf?.mounted ? 'Mounted' : 'Local only'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Golden mapped</CardDescription>
            <CardTitle className="text-2xl">
              {models.filter((m) => m.is_golden && !isSidecarModel(m)).length}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative max-w-md flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" placeholder="Filter library…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="flex items-center gap-2 rounded-md border px-3 py-2">
          <Switch id="show-sidecars" checked={showSidecars} onCheckedChange={setShowSidecars} />
          <Label htmlFor="show-sidecars" className="cursor-pointer">
            Show sidecars{sidecarCount ? ` (${sidecarCount})` : ''}
          </Label>
        </div>
        {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
      </div>

      {error ? (
        <div className="rounded-xl border border-warning/40 bg-warning/10 p-5 text-sm">
          <div className="font-medium text-warning">Library unavailable</div>
          <p className="mt-1 text-muted-foreground">{error}</p>
          <Button className="mt-3" size="sm" variant="outline" onClick={() => void refresh()}>
            Try again
          </Button>
        </div>
      ) : loading ? (
        <p className="text-sm text-muted-foreground">Loading library…</p>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
          No models match this view.
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map((model) => {
            const present = model.local?.present || model.status === 'ready'
            const path = model.rel_path || model.id
            const sidecar = isSidecarModel(model)
            return (
              <Card key={model.id}>
                <CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <HardDrive className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium">{model.lab}/{model.name}</span>
                      {model.is_golden && <Badge variant="success">golden</Badge>}
                      {sidecar && <Badge variant="outline">sidecar</Badge>}
                      <Badge variant={present ? 'secondary' : 'warning'}>{present ? 'on disk' : model.status || 'missing'}</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground font-mono truncate">
                      {model.hf_repo || path}
                      {model.size_human ? ` · ${model.size_human}` : ''}
                      {model.golden_profile ? ` · ${model.golden_profile}` : ''}
                      {model.requires_target ? ` · requires ${model.requires_target}` : ''}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {shelf?.mounted && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingPath === path}
                          onClick={() => void act(path, 'Pull', () => shelfPull(path))}
                        >
                          Pull
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingPath === path || !present}
                          onClick={() => void act(path, 'Push', () => shelfPush(path))}
                        >
                          Push
                        </Button>
                      </>
                    )}
                    {!sidecar && (
                      <Button
                        size="sm"
                        disabled={!present}
                        title={present ? 'Open recipe studio to create a draft for these weights' : 'Download weights first'}
                        onClick={() => openCreateRecipe(model)}
                      >
                        Create recipe…
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                      disabled={!present || actingPath === path}
                      onClick={() => void removeLocal(model, path)}
                    >
                      Remove local
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
