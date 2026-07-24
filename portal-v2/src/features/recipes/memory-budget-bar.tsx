import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  budgetCaption,
  estimateMemoryBudget,
  formatGb,
  FRAMEWORK_RESERVE_GB,
  OS_RESERVE_GB,
  type MemoryBudgetInput,
  type MemorySegmentId,
  verdictLabel,
} from '@/lib/memory-budget'
import { cn } from '@/lib/utils'

const SEGMENT_CLASS: Record<MemorySegmentId, string> = {
  os: 'bg-muted-foreground/35',
  weights: 'bg-primary',
  draft: 'bg-secondary-foreground/70',
  kv: 'bg-[var(--warning)]',
  framework: 'bg-muted-foreground/55',
  free: 'bg-muted',
}

export function MemoryBudgetBar({
  input,
  className,
  compact = false,
}: {
  input: MemoryBudgetInput
  className?: string
  compact?: boolean
}) {
  const budget = estimateMemoryBudget(input)
  const pool = budget.poolBytes || 1

  const displaySegments =
    budget.verdict === 'over'
      ? [
          ...budget.segments,
          {
            id: 'free' as const,
            label: 'Over',
            bytes: budget.overBytes,
            note: `Plan exceeds the ${formatGb(budget.poolBytes, 0)} GB unified pool.`,
          },
        ]
      : budget.segments

  // Normalize bar widths to pool; when OVER, scale so segments still sum visually to 100%.
  const barTotal = budget.verdict === 'over' ? budget.usedBytes || pool : pool

  return (
    <Card className={cn(className)}>
      <CardHeader className={cn('pb-2', compact && 'px-4 py-3')}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">Unified memory (128 GB)</CardTitle>
            {!compact && (
              <CardDescription className="mt-1">
                Planned footprint when served (eugr/vLLM pre-allocates KV to fill ~85% util — not just one
                sequence).
                {budget.approximate ? ' Some weight sizes are estimated.' : ''}
              </CardDescription>
            )}
          </div>
          <Badge
            variant={
              budget.verdict === 'fit' ? 'success' : budget.verdict === 'tight' ? 'warning' : 'destructive'
            }
          >
            {verdictLabel(budget.verdict)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className={cn('space-y-3', compact && 'px-4 pb-4 pt-0')}>
        <TooltipProvider delayDuration={150}>
          <div
            className="flex h-4 w-full overflow-hidden rounded-md border bg-muted/40"
            role="img"
            aria-label={budgetCaption(budget)}
          >
            {displaySegments
              .filter((s) => s.bytes > 0)
              .map((seg) => {
                const pct = Math.max(0.4, (seg.bytes / barTotal) * 100)
                return (
                  <Tooltip key={seg.id}>
                    <TooltipTrigger asChild>
                      <div
                        className={cn(
                          'h-full min-w-[2px] transition-[flex-grow] duration-300 ease-out',
                          SEGMENT_CLASS[seg.id],
                          budget.verdict === 'over' && seg.id === 'free' && 'bg-destructive',
                        )}
                        style={{ flexGrow: pct, flexBasis: 0 }}
                      />
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <p className="font-medium">
                        {seg.label}: {formatGb(seg.bytes)} GB
                      </p>
                      <p className="text-muted-foreground">{seg.note}</p>
                    </TooltipContent>
                  </Tooltip>
                )
              })}
          </div>
        </TooltipProvider>

        <p className="text-sm text-muted-foreground">{budgetCaption(budget)}</p>

        {!compact && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            {displaySegments
              .filter((s) => s.bytes > 0 && s.id !== 'free')
              .map((seg) => (
                <span key={seg.id} className="inline-flex items-center gap-1.5">
                  <span className={cn('inline-block h-2 w-2 rounded-sm', SEGMENT_CLASS[seg.id])} />
                  {seg.label} {formatGb(seg.bytes)}
                </span>
              ))}
            {budget.verdict !== 'over' && budget.freeBytes > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <span className={cn('inline-block h-2 w-2 rounded-sm', SEGMENT_CLASS.free)} />
                Headroom {formatGb(budget.freeBytes)}
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** Compact badge for catalog cards using the same estimator. */
export function FitsSparkBadge({ input }: { input: MemoryBudgetInput }) {
  const budget = estimateMemoryBudget(input)
  const empty =
    !input.model &&
    budget.usedBytes <= (OS_RESERVE_GB + FRAMEWORK_RESERVE_GB) * 1e9
  if (empty) return null
  const label =
    budget.verdict === 'fit' ? 'Fits Spark' : budget.verdict === 'tight' ? 'Tight fit' : 'May OOM'
  return (
    <Badge
      variant={
        budget.verdict === 'fit' ? 'success' : budget.verdict === 'tight' ? 'warning' : 'destructive'
      }
      title={budgetCaption(budget)}
    >
      {label}
    </Badge>
  )
}
