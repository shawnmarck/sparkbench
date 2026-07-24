import * as React from 'react'
import { cn } from '@/lib/utils'

export function Badge({
  className,
  variant = 'default',
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  variant?: 'default' | 'secondary' | 'outline' | 'success' | 'warning' | 'destructive'
}) {
  return (
    <div
      className={cn(
        'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium transition-colors',
        variant === 'default' && 'border-transparent bg-primary text-primary-foreground',
        variant === 'secondary' && 'border-transparent bg-secondary text-secondary-foreground',
        variant === 'outline' && 'text-foreground',
        variant === 'success' && 'border-transparent bg-success/15 text-success',
        variant === 'warning' && 'border-transparent bg-warning/15 text-warning',
        variant === 'destructive' && 'border-transparent bg-destructive/15 text-destructive',
        className,
      )}
      {...props}
    />
  )
}
