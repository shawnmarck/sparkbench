import { Leaf, Moon, Sun } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { THEMES, type AppTheme } from '@/components/theme-config'
import { cn } from '@/lib/utils'

const META: Record<
  AppTheme,
  { label: string; icon: typeof Sun; hint: string }
> = {
  light: { label: 'Light', icon: Sun, hint: 'Light surfaces' },
  green: { label: 'Green', icon: Leaf, hint: 'Spark green dark' },
  dark: { label: 'Midnight', icon: Moon, hint: 'True dark / black' },
}

export function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const current = (THEMES.includes(theme as AppTheme) ? theme : 'green') as AppTheme

  if (!mounted) {
    return <div className="h-8 w-[7.5rem]" aria-hidden />
  }

  return (
    <TooltipProvider delayDuration={300}>
      <div
        className="inline-flex items-center rounded-md border border-sidebar-border bg-background/40 p-0.5"
        role="group"
        aria-label="Color theme"
      >
        {THEMES.map((id) => {
          const { label, icon: Icon, hint } = META[id]
          const active = current === id
          return (
            <Tooltip key={id}>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className={cn(
                    'h-7 w-7',
                    active && 'bg-sidebar-accent text-sidebar-accent-foreground',
                  )}
                  aria-label={label}
                  aria-pressed={active}
                  onClick={() => setTheme(id)}
                >
                  <Icon className="h-3.5 w-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top">
                {label} — {hint}
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
    </TooltipProvider>
  )
}
