import type { ReactNode } from 'react'
import { ExternalLink } from 'lucide-react'
import type { InventoryModel } from '@/lib/api/types'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export function ModelFactsPanel({
  model,
  inventoryPath,
}: {
  model?: InventoryModel
  inventoryPath: string
}) {
  const formats = (model?.variants || [])
    .map((v) => v.format)
    .filter(Boolean)
    .join(', ')
  const engines = (model?.engines || []).join(', ')
  const params =
    model?.param_b != null
      ? model.param_active_b != null
        ? `${model.param_b}B (${model.param_active_b}B active)`
        : `${model.param_b}B`
      : null

  const facts: Array<{ label: string; value: ReactNode }> = [
    { label: 'Lab / maker', value: model?.lab || inventoryPath.split('/')[0] || '—' },
    { label: 'Inventory path', value: <span className="font-mono text-xs">{inventoryPath}</span> },
    {
      label: 'On-disk path',
      value: (
        <span className="font-mono text-xs break-all">
          {model?.path || model?.local?.path || `/models/${inventoryPath}`}
        </span>
      ),
    },
    { label: 'Format / weights', value: formats || engines || '—' },
    { label: 'Suggested engine(s)', value: engines || '—' },
    {
      label: 'Native max context',
      value: model?.max_context != null ? model.max_context.toLocaleString() : '—',
    },
    { label: 'Size', value: model?.size_human || '—' },
    { label: 'Architecture', value: model?.architecture || '—' },
    { label: 'Parameters', value: params || '—' },
    {
      label: 'Status',
      value: model?.local?.present || model?.status === 'ready' ? 'on disk' : model?.status || 'unknown',
    },
  ]

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">
              {model ? `${model.lab}/${model.name}` : inventoryPath}
            </CardTitle>
            <CardDescription>
              Facts about this model — not recipe knobs. Used to prefill a new recipe.
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-1">
            {model?.is_golden && <Badge variant="success">golden mapped</Badge>}
            {(model?.capabilities || []).slice(0, 4).map((c) => (
              <Badge key={c} variant="secondary">
                {c}
              </Badge>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {model?.summary && <p className="text-sm text-muted-foreground">{model.summary}</p>}
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 text-sm">
          {facts.map((f) => (
            <div key={f.label}>
              <dt className="text-xs text-muted-foreground">{f.label}</dt>
              <dd className="mt-0.5">{f.value}</dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-wrap gap-3 text-sm">
          {(model?.hf_url || model?.hf_repo) && (
            <a
              className="inline-flex items-center gap-1 text-primary hover:underline"
              href={model.hf_url || `https://huggingface.co/${model.hf_repo}`}
              target="_blank"
              rel="noreferrer"
            >
              Hugging Face
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          {model?.golden_profile && (
            <span className="text-muted-foreground">
              Golden recipe: <code className="text-xs">{model.golden_profile}</code>
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
