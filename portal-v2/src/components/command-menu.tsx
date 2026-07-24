import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity,
  BookOpen,
  Bot,
  Boxes,
  Clipboard,
  FlaskConical,
  HeartPulse,
  LayoutDashboard,
  LibraryBig,
  Power,
  Puzzle,
  Search,
  Wrench,
} from 'lucide-react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { stopInference } from '@/lib/api/client'
import { cn } from '@/lib/utils'

type Command = {
  id: string
  label: string
  hint: string
  keywords: string
  icon: typeof Search
  run: () => void | Promise<void>
  danger?: boolean
}

export function CommandMenu({
  open,
  onOpenChange,
  hasActiveInference,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  hasActiveInference: boolean
}) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [message, setMessage] = useState('')

  function go(path: string) {
    navigate(path)
    onOpenChange(false)
  }

  const commands: Command[] = [
      { id: 'home', label: 'Open command center', hint: 'Live stack overview', keywords: 'home dashboard overview', icon: LayoutDashboard, run: () => go('/') },
      { id: 'operator', label: 'Ask Spark', hint: 'Hermes-powered lab operator', keywords: 'agent assistant chat goals daily checks hermes', icon: Bot, run: () => go('/operator') },
      { id: 'catalog', label: 'Serve a golden model', hint: 'Open Catalog', keywords: 'catalog model switch start inference', icon: LibraryBig, run: () => go('/catalog') },
      { id: 'find', label: 'Find & download a model', hint: 'Browse Hugging Face', keywords: 'download hugging face hf explore', icon: Search, run: () => go('/library/find') },
      { id: 'library', label: 'Manage weights', hint: 'Open Library', keywords: 'disk nas shelf models', icon: Boxes, run: () => go('/library') },
      { id: 'recipes', label: 'Build or tune a recipe', hint: 'Open Recipes', keywords: 'recipe profile context kv draft', icon: BookOpen, run: () => go('/recipes') },
      { id: 'benchmaster', label: 'Run automated benchmarks', hint: 'Open Benchmaster', keywords: 'bench benchmark queue perf intel eval', icon: FlaskConical, run: () => go('/benchmaster') },
      { id: 'health', label: 'Inspect system health', hint: 'Host and service status', keywords: 'gpu cpu service engine status logs', icon: HeartPulse, run: () => go('/health') },
      { id: 'addons', label: 'Manage add-ons', hint: 'Chat, Hermes, Netdata', keywords: 'open webui chat addons', icon: Puzzle, run: () => go('/addons') },
      { id: 'setup', label: 'Install or update components', hint: 'Open Setup', keywords: 'setup install update token service', icon: Wrench, run: () => go('/setup') },
      {
        id: 'copy-gateway',
        label: 'Copy gateway endpoint',
        hint: `${window.location.hostname}:9000/v1`,
        keywords: 'copy api url endpoint gateway openai',
        icon: Clipboard,
        run: async () => {
          await navigator.clipboard.writeText(`http://${window.location.hostname}:9000/v1`)
          setMessage('Gateway endpoint copied')
        },
      },
      ...(hasActiveInference
        ? [
            {
              id: 'stop-inference',
              label: 'Stop active inference',
              hint: 'Release unified memory and the GPU',
              keywords: 'stop down release gpu engine inference',
              icon: Power,
              danger: true,
              run: async () => {
                if (!window.confirm('Stop the active inference engine and release the GPU?')) return
                await stopInference()
                setMessage('Inference stop requested')
              },
            } satisfies Command,
          ]
        : []),
  ]

  const filtered = commands.filter((command) => {
    const needle = query.trim().toLowerCase()
    if (!needle) return true
    return `${command.label} ${command.hint} ${command.keywords}`.toLowerCase().includes(needle)
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) {
          setQuery('')
          setMessage('')
        }
      }}
    >
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-xl">
        <DialogHeader className="sr-only">
          <DialogTitle>Command menu</DialogTitle>
          <DialogDescription>Navigate SparkBench and run common operator actions.</DialogDescription>
        </DialogHeader>
        <div className="relative border-b">
          <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="What do you want to do?"
            className="h-14 rounded-none border-0 bg-transparent pl-11 pr-4 text-base shadow-none focus-visible:ring-0"
          />
        </div>
        <div className="max-h-[min(65vh,520px)] overflow-y-auto p-2">
          {message && (
            <div role="status" className="mb-2 rounded-md bg-success/10 px-3 py-2 text-sm text-success">
              {message}
            </div>
          )}
          {filtered.length ? (
            filtered.map((command) => {
              const Icon = command.icon
              return (
                <button
                  key={command.id}
                  type="button"
                  className={cn(
                    'flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
                    command.danger && 'text-destructive',
                  )}
                  onClick={() => void Promise.resolve(command.run()).catch((error) => setMessage(error instanceof Error ? error.message : String(error)))}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border bg-background">
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{command.label}</span>
                    <span className="block truncate text-xs text-muted-foreground">{command.hint}</span>
                  </span>
                </button>
              )
            })
          ) : (
            <div className="px-3 py-8 text-center text-sm text-muted-foreground">No matching command.</div>
          )}
        </div>
        <div className="flex items-center justify-between border-t bg-muted/30 px-4 py-2 text-[11px] text-muted-foreground">
          <span>Search workflows, pages, and controls</span>
          <span className="flex items-center gap-1">
            <Activity className="h-3 w-3" />
            local operator
          </span>
        </div>
      </DialogContent>
    </Dialog>
  )
}
