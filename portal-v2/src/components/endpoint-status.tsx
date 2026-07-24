import { useState } from 'react'
import { Check, Copy, Server } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { engineIsUp } from '@/features/home/use-live-home-stream'
import type { GpuMetrics, InferenceStatus } from '@/lib/api/types'

type EndpointRow = {
  id: string
  label: string
  url?: string | null
  up?: boolean
  model?: string | null
}

function endpointRows(gpu: GpuMetrics | null, inference: InferenceStatus | null): EndpointRow[] {
  const host = window.location.hostname
  const gateway = gpu?.inference?.gateway
  const engines = gpu?.inference?.engines || []
  const activeUrl = inference?.active?.api_url || inference?.urls?.api
  const rows: EndpointRow[] = [
    {
      id: 'gateway',
      label: 'Gateway :9000',
      url: gateway?.url || `http://${host}:9000/v1`,
      up: gateway?.up,
      model: gateway?.model,
    },
  ]

  for (const engine of engines) {
    rows.push({
      id: engine.id,
      label: `${engine.label || engine.id}${engine.port ? ` :${engine.port}` : ''}`,
      url: engine.port ? `http://${host}:${engine.port}/v1` : null,
      up: engine.up,
      model: engine.model,
    })
  }

  if (!engines.length && inference?.engines) {
    for (const name of ['eugr', 'llamacpp', 'ds4'] as const) {
      const up = engineIsUp(inference.engines, name === 'llamacpp' ? 'llama' : name)
      const port = name === 'llamacpp' ? 8081 : 8000
      rows.push({
        id: name,
        label: `${name} :${port}`,
        url: `http://${host}:${port}/v1`,
        up,
        model: up ? inference.active?.served_name : null,
      })
    }
  }

  const activePort = endpointPort(activeUrl)
  const activeAlreadyListed = rows.some(
    (row) => row.url === activeUrl || (activePort && endpointPort(row.url) === activePort),
  )
  if (activeUrl && !activeAlreadyListed) {
    rows.push({
      id: 'active-api',
      label: 'Active engine API',
      url: activeUrl,
      up: !!inference?.active?.ready,
      model: inference?.active?.served_name,
    })
  }

  return rows
}

function endpointPort(url?: string | null) {
  if (!url) return ''
  try {
    return new URL(url).port
  } catch {
    return ''
  }
}

export function EndpointGrid({
  gpu,
  inference,
}: {
  gpu: GpuMetrics | null
  inference: InferenceStatus | null
}) {
  const [copied, setCopied] = useState('')

  async function copyEndpoint(row: EndpointRow) {
    if (!row.url) return
    await navigator.clipboard.writeText(row.url)
    setCopied(row.id)
    window.setTimeout(() => setCopied(''), 1200)
  }

  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
      {endpointRows(gpu, inference).map((row) => (
        <div key={row.id} className="space-y-2 rounded-lg border p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Server className="h-3.5 w-3.5 text-muted-foreground" />
              {row.label}
            </div>
            <Badge variant={row.up ? 'success' : 'secondary'}>{row.up ? 'up' : 'down'}</Badge>
          </div>
          <div className="flex items-center gap-1">
            <div className="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground">{row.url || '—'}</div>
            {row.url && (
              <Button
                type="button"
                size="icon"
                variant="ghost"
                className="h-7 w-7 shrink-0"
                aria-label={`Copy ${row.label} endpoint`}
                onClick={() => void copyEndpoint(row)}
              >
                {copied === row.id ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            )}
          </div>
          {row.model && <div className="truncate font-mono text-[11px]">{row.model}</div>}
        </div>
      ))}
    </div>
  )
}

export function SidebarEndpoints({
  gpu,
  inference,
}: {
  gpu: GpuMetrics | null
  inference: InferenceStatus | null
}) {
  return (
    <div className="space-y-1.5">
      {endpointRows(gpu, inference).map((row) => (
        <div key={row.id} className="rounded-md border border-sidebar-border/70 bg-background/30 px-2 py-1.5">
          <div className="flex items-center gap-2 text-[11px]">
            <CircleStatus up={row.up} />
            <span className="min-w-0 flex-1 truncate font-medium">{row.label}</span>
          </div>
          <div className="mt-0.5 truncate pl-3.5 font-mono text-[9px] text-muted-foreground">{row.url || '—'}</div>
        </div>
      ))}
    </div>
  )
}

function CircleStatus({ up }: { up?: boolean }) {
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${up ? 'bg-success' : 'bg-muted-foreground/40'}`} />
}
