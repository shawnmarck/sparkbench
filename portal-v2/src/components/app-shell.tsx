import { Suspense, useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Beaker,
  BookOpenText,
  Boxes,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Command,
  ExternalLink,
  HeartPulse,
  LayoutDashboard,
  LibraryBig,
  MessageSquare,
  Puzzle,
  Activity,
  Bot,
  Circle,
  FlaskConical,
  Sparkles,
  Wrench,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { ThemeToggle } from '@/components/theme-toggle'
import { Separator } from '@/components/ui/separator'
import { getGpu, getInferenceStatus, getInstallStatus } from '@/lib/api/client'
import type { AddonState, GpuMetrics, InferenceStatus, InstallStatus } from '@/lib/api/types'
import { getAddonNavPreference, resolveAddonStates } from '@/lib/addons'
import { CommandMenu } from '@/components/command-menu'
import { SidebarEndpoints } from '@/components/endpoint-status'

const navGroups = [
  {
    label: 'Operate',
    items: [
      { to: '/', label: 'Command center', shortLabel: 'Home', icon: LayoutDashboard, end: true },
      { to: '/operator', label: 'Spark operator', shortLabel: 'Spark', icon: Bot },
      { to: '/catalog', label: 'Catalog', icon: LibraryBig },
      { to: '/library', label: 'Library', icon: Boxes },
      { to: '/recipes', label: 'Recipes', icon: BookOpenText },
      { to: '/benchmaster', label: 'Benchmaster', shortLabel: 'Bench', icon: FlaskConical },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/health', label: 'Health', icon: HeartPulse },
      { to: '/addons', label: 'Add-ons', icon: Puzzle },
      { to: '/setup', label: 'Setup', icon: Wrench },
    ],
  },
]

const addonIcons = {
  chat: MessageSquare,
  hermes: Bot,
  netdata: Activity,
} as const

export function AppShell() {
  const [addonLinks, setAddonLinks] = useState<AddonState[]>([])
  const [inference, setInference] = useState<InferenceStatus | null>(null)
  const [install, setInstall] = useState<InstallStatus | null>(null)
  const [gpu, setGpu] = useState<GpuMetrics | null>(null)
  const [online, setOnline] = useState(false)
  const [endpointsOpen, setEndpointsOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('spark-sidebar-collapsed') === '1',
  )
  const location = useLocation()

  useEffect(() => {
    let cancelled = false
    async function refresh() {
      const [gpuResult, installResult, inferenceResult] = await Promise.allSettled([
        getGpu(),
        getInstallStatus(),
        getInferenceStatus(true),
      ])
      if (cancelled) return
      const gpu = gpuResult.status === 'fulfilled' ? gpuResult.value : null
      const nextInstall = installResult.status === 'fulfilled' ? installResult.value : null
      const nextInference = inferenceResult.status === 'fulfilled' ? inferenceResult.value : null
      setInstall(nextInstall)
      setInference(nextInference)
      setGpu(gpu)
      setOnline(gpuResult.status === 'fulfilled' || inferenceResult.status === 'fulfilled')
      if (!gpu) {
        setAddonLinks([])
        return
      }
      const resolved = resolveAddonStates(
        gpu,
        nextInstall || { ok: false, services: [], install_token_configured: false },
      ).filter(
        (addon) => addon.id !== 'hermes' && (getAddonNavPreference(addon.id) ?? addon.status === 'on'),
      )
      setAddonLinks(resolved)
    }
    void refresh()
    const onStorage = () => void refresh()
    window.addEventListener('spark-addons-changed', onStorage)
    const id = setInterval(() => void refresh(), 15000)
    return () => {
      cancelled = true
      window.removeEventListener('spark-addons-changed', onStorage)
      clearInterval(id)
    }
  }, [])

  useEffect(() => {
    localStorage.setItem('spark-sidebar-collapsed', sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const currentPage = useMemo(() => {
    const item = navGroups.flatMap((group) => group.items).find((entry) =>
      entry.to === '/' ? location.pathname === '/' : location.pathname.startsWith(entry.to),
    )
    return item?.label || 'SparkBench'
  }, [location.pathname])

  const activeProfile = inference?.active?.id || inference?.active?.profile
  const unhealthy =
    install?.services?.filter((service) => !service.healthy && service.name !== 'gateway').length || 0

  return (
    <div
      className={cn(
        'min-h-dvh lg:grid',
        sidebarCollapsed
          ? 'lg:grid-cols-[76px_minmax(0,1fr)]'
          : 'lg:grid-cols-[264px_minmax(0,1fr)]',
      )}
    >
      <aside className="relative hidden h-dvh flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:sticky lg:top-0 lg:flex">
        <button
          type="button"
          className="absolute -right-3 top-6 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-sidebar-border bg-sidebar text-muted-foreground shadow-sm transition-colors hover:text-foreground"
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
        >
          {sidebarCollapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronLeft className="h-3.5 w-3.5" />}
        </button>
        <div className={cn('flex h-16 items-center gap-3 px-5', sidebarCollapsed && 'justify-center px-2')}>
          <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-[0_0_24px_var(--glow)]">
            <Beaker className="h-4.5 w-4.5" />
            <Sparkles className="absolute -right-1 -top-1 h-3 w-3 text-primary" />
          </div>
          <div className={cn(sidebarCollapsed && 'hidden')}>
            <div className="text-sm font-semibold tracking-tight">SparkBench</div>
            <div className="text-[11px] text-muted-foreground">Model operations lab</div>
          </div>
        </div>
        <Separator />

        <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="Primary navigation">
          {navGroups.map((group, groupIndex) => (
            <div key={group.label} className={cn(groupIndex > 0 && 'mt-6')}>
              {sidebarCollapsed ? (
                <Separator className="mx-auto mb-2 w-6 opacity-60" />
              ) : (
                <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">
                  {group.label}
                </div>
              )}
              <div className="space-y-1">
                {group.items.map(({ to, label, icon: Icon, end }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={end}
                    className={({ isActive }) =>
                      cn(
                        'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all',
                        sidebarCollapsed && 'justify-center px-2',
                        isActive
                          ? 'bg-sidebar-accent text-sidebar-accent-foreground shadow-sm'
                          : 'text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground',
                      )
                    }
                    title={sidebarCollapsed ? label : undefined}
                  >
                    <Icon className="h-4 w-4 transition-transform group-hover:scale-105" />
                    <span className={cn(sidebarCollapsed && 'sr-only')}>{label}</span>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}

          {addonLinks.length > 0 && (
            <div className="mt-6">
              {sidebarCollapsed ? (
                <Separator className="mx-auto mb-2 w-6 opacity-60" />
              ) : (
                <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/70">
                  Launch
                </div>
              )}
              <div className="space-y-1">
                {addonLinks.map((addon) => {
                  const Icon = addonIcons[addon.id] || ExternalLink
                  return (
                    <a
                      key={addon.id}
                      href={addon.url}
                      target="_blank"
                      rel="noreferrer"
                      className={cn(
                        'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-foreground',
                        sidebarCollapsed && 'justify-center px-2',
                      )}
                      title={sidebarCollapsed ? addon.name : undefined}
                    >
                      <Icon className="h-4 w-4" />
                      <span className={cn(sidebarCollapsed && 'sr-only')}>{addon.name}</span>
                      {!sidebarCollapsed && <ExternalLink className="ml-auto h-3 w-3 opacity-60" />}
                    </a>
                  )
                })}
              </div>
            </div>
          )}
        </nav>

        <div className="border-t p-3">
          <div
            className={cn('rounded-lg bg-background/30', sidebarCollapsed && 'flex justify-center')}
            title={sidebarCollapsed ? `${online ? 'Sparky online' : 'Sparky unreachable'} · show endpoints` : undefined}
          >
            <button
              type="button"
              className={cn('w-full p-3 text-left', sidebarCollapsed && 'flex justify-center p-2')}
              aria-expanded={endpointsOpen}
              aria-label={`${online ? 'Sparky online' : 'Sparky unreachable'}; toggle API endpoints`}
              onClick={() => {
                if (sidebarCollapsed) setSidebarCollapsed(false)
                setEndpointsOpen((open) => !open)
              }}
            >
              <div className="flex items-center gap-2 text-xs font-medium">
                <Circle className={cn('h-2.5 w-2.5 fill-current', online ? 'text-success' : 'text-warning')} />
                {!sidebarCollapsed && (
                  <>
                    {online ? 'Sparky online' : 'Sparky unreachable'}
                    {unhealthy > 0 && <span className="text-warning">{unhealthy} down</span>}
                    <ChevronUp className={cn('ml-auto h-3.5 w-3.5 text-muted-foreground transition-transform', !endpointsOpen && 'rotate-180')} />
                  </>
                )}
              </div>
              {!sidebarCollapsed && (
                <div className="mt-1.5 truncate font-mono text-[10px] text-muted-foreground">
                  {activeProfile ? `serving ${activeProfile}` : 'GPU idle'}
                </div>
              )}
            </button>
            {endpointsOpen && !sidebarCollapsed && (
              <div className="border-t border-sidebar-border/70 px-2 pb-2 pt-2">
                <div className="mb-1.5 px-1 text-[9px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  API endpoints
                </div>
                <SidebarEndpoints gpu={gpu} inference={inference} />
              </div>
            )}
          </div>
          <div className={cn('mt-3 flex justify-end', sidebarCollapsed && 'hidden')}>
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b bg-background/85 px-4 backdrop-blur-xl lg:h-16 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground lg:hidden">
              <Beaker className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{currentPage}</div>
              <div className="hidden items-center gap-1.5 text-[11px] text-muted-foreground sm:flex">
                <Circle className={cn('h-2 w-2 fill-current', online ? 'text-success' : 'text-warning')} />
                {online ? (activeProfile ? `Serving ${activeProfile}` : 'Online · GPU idle') : 'Live APIs unavailable'}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="flex h-9 items-center gap-2 rounded-lg border bg-card px-3 text-xs text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground"
              onClick={() => setCommandOpen(true)}
            >
              <Command className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Quick actions</span>
              <kbd className="hidden rounded border bg-muted/50 px-1.5 py-0.5 font-mono text-[10px] md:inline">⌘K</kbd>
            </button>
            <div className="lg:hidden">
              <ThemeToggle />
            </div>
          </div>
        </header>

        <nav className="sticky top-14 z-20 overflow-x-auto border-b bg-background/90 px-2 py-2 backdrop-blur lg:hidden" aria-label="Mobile navigation">
          <div className="flex min-w-max gap-1">
            {navGroups.flatMap((group) => group.items).map(({ to, label, shortLabel, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    'inline-flex items-center gap-1.5 rounded-md px-2.5 py-2 text-xs transition-colors',
                    isActive ? 'bg-accent font-medium text-accent-foreground' : 'text-muted-foreground',
                  )
                }
              >
                <Icon className="h-3.5 w-3.5" />
                {shortLabel || label}
              </NavLink>
            ))}
          </div>
        </nav>

        <main className="min-w-0">
          <div className="mx-auto w-full max-w-[1500px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <Suspense fallback={<div className="py-12 text-sm text-muted-foreground">Loading view…</div>}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>

      <CommandMenu
        open={commandOpen}
        onOpenChange={setCommandOpen}
        hasActiveInference={!!activeProfile}
      />
    </div>
  )
}
