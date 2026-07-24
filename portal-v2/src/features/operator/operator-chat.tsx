import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Bot,
  Check,
  Loader2,
  Send,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  createOperatorTurn,
  getOperatorStatus,
  getOperatorTurn,
  resolveOperatorProposal,
  streamOperatorTurn,
} from '@/lib/api/client'
import type { OperatorProposal, OperatorStatus, OperatorTurn } from '@/lib/api/types'
import { cn } from '@/lib/utils'

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  proposals?: OperatorProposal[]
  error?: boolean
}

const SESSION_KEY = 'spark-operator-session'
const HISTORY_KEY = 'spark-operator-history'

const suggestions = [
  'What needs my attention?',
  'Summarize inference and GPU health',
  'What is Benchmaster doing?',
  'Which recipes are fastest?',
]

function loadHistory(): ChatMessage[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is ChatMessage => (
        !!item
        && typeof item === 'object'
        && 'id' in item
        && typeof item.id === 'string'
        && 'role' in item
        && (item.role === 'user' || item.role === 'assistant')
        && 'content' in item
        && typeof item.content === 'string'
      ))
      .slice(-24)
  } catch {
    return []
  }
}

export function OperatorChat({
  compact = false,
  onStatus,
}: {
  compact?: boolean
  onStatus?: (status: OperatorStatus) => void
}) {
  const [status, setStatus] = useState<OperatorStatus | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(loadHistory)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [connectionError, setConnectionError] = useState('')
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(SESSION_KEY))
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    getOperatorStatus()
      .then((next) => {
        if (cancelled) return
        setStatus(next)
        onStatus?.(next)
      })
      .catch((error) => {
        if (!cancelled) setConnectionError(error instanceof Error ? error.message : String(error))
      })
    return () => {
      cancelled = true
    }
  }, [onStatus])

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(messages.slice(-24)))
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  function finishTurn(turn: OperatorTurn, assistantId: string) {
    if (turn.session_id) {
      setSessionId(turn.session_id)
      localStorage.setItem(SESSION_KEY, turn.session_id)
    }
    setMessages((current) => current.map((message) =>
      message.id === assistantId
        ? {
            ...message,
            content: turn.state === 'failed'
              ? turn.error || 'Spark could not finish that request.'
              : turn.response || 'Done.',
            proposals: turn.proposals || [],
            error: turn.state === 'failed',
          }
        : message,
    ))
    setSending(false)
  }

  async function pollTurn(turnId: string, assistantId: string) {
    for (let attempt = 0; attempt < 180; attempt += 1) {
      const turn = await getOperatorTurn(turnId)
      if (['succeeded', 'failed', 'cancelled'].includes(turn.state)) {
        finishTurn(turn, assistantId)
        return
      }
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
    }
    throw new Error('Spark is still working; reopen this conversation in a moment.')
  }

  async function sendMessage(value = input) {
    const text = value.trim()
    if (!text || sending) return
    setConnectionError('')
    setInput('')
    setSending(true)
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: 'user', content: text }
    const assistantId = crypto.randomUUID()
    setMessages((current) => [
      ...current,
      userMessage,
      { id: assistantId, role: 'assistant', content: 'Checking the lab…' },
    ])
    try {
      const turn = await createOperatorTurn(text, sessionId)
      if (['succeeded', 'failed', 'cancelled'].includes(turn.state)) {
        finishTurn(turn, assistantId)
        return
      }
      let settled = false
      const close = streamOperatorTurn(
        turn.id,
        (next) => {
          if (!['succeeded', 'failed', 'cancelled'].includes(next.state)) return
          settled = true
          finishTurn(next, assistantId)
        },
        () => {
          if (settled) return
          void pollTurn(turn.id, assistantId).catch((error) => {
            setConnectionError(error instanceof Error ? error.message : String(error))
            setSending(false)
          })
        },
      )
      window.setTimeout(() => {
        if (!settled) close()
      }, 16 * 60_000)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setMessages((current) => current.map((item) =>
        item.id === assistantId ? { ...item, content: message, error: true } : item,
      ))
      setSending(false)
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    void sendMessage()
  }

  function resetConversation() {
    setMessages([])
    setSessionId(null)
    localStorage.removeItem(HISTORY_KEY)
    localStorage.removeItem(SESSION_KEY)
  }

  async function resolveProposal(messageId: string, proposal: OperatorProposal, resolution: 'confirm' | 'cancel') {
    setMessages((current) => current.map((message) =>
      message.id === messageId
        ? {
            ...message,
            proposals: message.proposals?.map((item) =>
              item.id === proposal.id ? { ...item, state: 'running' } : item,
            ),
          }
        : message,
    ))
    try {
      const resolved = await resolveOperatorProposal(proposal.id, resolution)
      setMessages((current) => current.map((message) =>
        message.id === messageId
          ? {
              ...message,
              proposals: message.proposals?.map((item) => item.id === proposal.id ? resolved : item),
            }
          : message,
      ))
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : String(error))
    }
  }

  const chat = (
    <>
      <div
        ref={scrollRef}
        className={cn(
          'space-y-4 overflow-y-auto px-4 py-4 sm:px-5',
          compact ? 'max-h-[380px] min-h-[240px]' : 'min-h-[420px] max-h-[62vh]',
        )}
        aria-live="polite"
      >
        {!messages.length && (
          <div className="mx-auto flex max-w-lg flex-col items-center py-8 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-[0_0_28px_var(--glow)]">
              <Sparkles className="h-5 w-5" />
            </span>
            <h3 className="mt-4 font-semibold">Ask Spark about your model lab</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              It can inspect live state and prepare changes for your confirmation.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              {suggestions.slice(0, compact ? 3 : 4).map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                  onClick={() => void sendMessage(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message) => (
          <div
            key={message.id}
            className={cn('flex gap-3', message.role === 'user' && 'justify-end')}
          >
            {message.role === 'assistant' && (
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Bot className="h-4 w-4" />
              </span>
            )}
            <div className={cn('max-w-[88%] space-y-3', message.role === 'user' && 'max-w-[80%]')}>
              <div
                className={cn(
                  'whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed',
                  message.role === 'user'
                    ? 'rounded-br-md bg-primary text-primary-foreground'
                    : message.error
                      ? 'rounded-bl-md border border-destructive/30 bg-destructive/5 text-destructive'
                      : 'rounded-bl-md border bg-muted/35',
                )}
              >
                {message.content}
                {sending && message.role === 'assistant' && message === messages[messages.length - 1] && (
                  <Loader2 className="ml-2 inline h-3.5 w-3.5 animate-spin" />
                )}
              </div>
              {message.proposals?.map((proposal) => (
                <ProposalCard
                  key={proposal.id}
                  proposal={proposal}
                  onResolve={(resolution) => void resolveProposal(message.id, proposal, resolution)}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
      <form onSubmit={submit} className="border-t bg-muted/15 p-3 sm:p-4">
        {connectionError && (
          <div role="alert" className="mb-3 rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
            {connectionError}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-xl border bg-background p-2 shadow-sm focus-within:ring-2 focus-within:ring-ring/40">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void sendMessage()
              }
            }}
            rows={compact ? 1 : 2}
            placeholder={status?.available ? 'Ask Spark…' : 'Install the Spark operator to begin'}
            disabled={!status?.available || sending}
            className="max-h-36 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-muted-foreground"
          />
          <Button type="submit" size="icon" disabled={!input.trim() || !status?.available || sending} aria-label="Send">
            {sending ? <Loader2 className="animate-spin" /> : <Send />}
          </Button>
        </div>
        <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <ShieldCheck className="h-3 w-3" />
            Changes require confirmation
          </span>
          {!compact && <span>{status?.model || 'OOB provider not configured'}</span>}
        </div>
      </form>
    </>
  )

  if (compact) {
    return (
      <Card className="overflow-hidden">
        <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 border-b">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4 text-primary" />
              Ask Spark
            </CardTitle>
            <CardDescription>Hermes-powered lab operator</CardDescription>
          </div>
          <Button asChild variant="ghost" size="sm">
            <Link to="/operator">
              Open
              <ArrowRight />
            </Link>
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          {status && !status.available ? <Unavailable /> : chat}
        </CardContent>
      </Card>
    )
  }

  return status && !status.available ? <Unavailable /> : (
    <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3 sm:px-5">
        <div>
          <div className="text-sm font-medium">Conversation</div>
          <div className="text-xs text-muted-foreground">{sessionId ? 'Persistent Hermes session' : 'New session'}</div>
        </div>
        <Button type="button" size="sm" variant="ghost" disabled={!messages.length && !sessionId} onClick={resetConversation}>
          New conversation
        </Button>
      </div>
      {chat}
    </div>
  )
}

function Unavailable() {
  return (
    <div className="flex min-h-56 flex-col items-center justify-center px-6 py-8 text-center">
      <Bot className="h-8 w-8 text-muted-foreground" />
      <div className="mt-3 font-medium">Spark is not installed</div>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">
        Install the optional Hermes runtime, then configure an out-of-band provider.
      </p>
      <Button asChild className="mt-4">
        <Link to="/addons">Install Spark operator</Link>
      </Button>
    </div>
  )
}

function ProposalCard({
  proposal,
  onResolve,
}: {
  proposal: OperatorProposal
  onResolve: (resolution: 'confirm' | 'cancel') => void
}) {
  const pending = proposal.state === 'pending'
  const running = proposal.state === 'running'
  return (
    <div className="rounded-xl border border-warning/35 bg-warning/5 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-medium">
            <ShieldCheck className="h-4 w-4 text-warning" />
            {proposal.title}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{proposal.summary}</p>
        </div>
        <Badge
          variant={proposal.state === 'succeeded' ? 'success' : proposal.state === 'failed' ? 'destructive' : 'warning'}
        >
          {proposal.state}
        </Badge>
      </div>
      {proposal.error && <p className="mt-2 text-xs text-destructive">{proposal.error}</p>}
      {(pending || running) && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" disabled={running} onClick={() => onResolve('confirm')}>
            {running ? <Loader2 className="animate-spin" /> : <Check />}
            Confirm
          </Button>
          <Button size="sm" variant="outline" disabled={running} onClick={() => onResolve('cancel')}>
            <X />
            Cancel
          </Button>
        </div>
      )}
    </div>
  )
}
