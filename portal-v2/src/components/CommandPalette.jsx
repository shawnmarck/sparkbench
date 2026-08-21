import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

const jumps = [
  { id: 'home', label: 'Go to Home', hint: 'operate', run: (nav) => nav('/') },
  { id: 'inf', label: 'Go to Inference', hint: 'operate', run: (nav) => nav('/inference') },
  { id: 'log', label: 'Go to Engine log', hint: 'operate', run: (nav) => nav('/inference/log') },
  { id: 'bm', label: 'Go to Benchmaster', hint: 'operate', run: (nav) => nav('/benchmaster') },
  { id: 'ex', label: 'Go to Explore', hint: 'browse', run: (nav) => nav('/explore') },
  { id: 'lib', label: 'Go to Models', hint: 'browse', run: (nav) => nav('/models') },
  { id: 'act', label: 'Go to Activity', hint: 'operate', run: (nav) => nav('/activity') },
  { id: 'hw', label: 'Go to Hardware', hint: 'operate', run: (nav) => nav('/hardware') },
  { id: 'hermes', label: 'Open Hermes', hint: 'external', href: '/hermes/' },
  { id: 'chat', label: 'Open Chat', hint: 'external', href: 'http://sparky:3000/' },
  { id: 'netdata', label: 'Open Netdata', hint: 'external', href: 'http://sparky:19999/v3/' },
  { id: 'legacy', label: 'Open Legacy UI', hint: 'external', href: '/' },
]

function match(q, item) {
  if (!q) return true
  const hay = `${item.label} ${item.hint || ''} ${item.id || ''}`.toLowerCase()
  return hay.includes(q)
}

export function CommandPalette({ live, onSwitch, onStop }) {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const inputRef = useRef(null)

  const items = useMemo(() => {
    const query = q.trim().toLowerCase()
    const recipeHits = (live.recipes || [])
      .filter((r) => {
        if (!query) return false
        const hay = `${r.name || ''} ${r.id || ''} ${r.engine || ''}`.toLowerCase()
        return hay.includes(query)
      })
      .slice(0, 8)
      .map((r) => ({
        id: `serve-${r.id}`,
        label: `Serve ${r.name || r.id}`,
        hint: r.id,
        kind: 'switch',
        profile: r,
      }))
    const stop = query && 'stop inference'.includes(query)
      ? [{ id: 'stop', label: 'Stop inference', hint: 'down', kind: 'stop' }]
      : []
    return [
      ...jumps.filter((j) => match(query, j)),
      ...recipeHits,
      ...stop,
    ]
  }, [q, live.recipes])

  useEffect(() => {
    function onKey(e) {
      const meta = e.metaKey || e.ctrlKey
      if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
        setQ('')
        setIdx(0)
      }
      if (e.key === 'Escape' && open) {
        e.preventDefault()
        setOpen(false)
      }
    }
    function onOpen() {
      setOpen(true)
      setQ('')
      setIdx(0)
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('spark-palette', onOpen)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('spark-palette', onOpen)
    }
  }, [open])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    setIdx(0)
  }, [q])

  function run(item) {
    if (!item) return
    setOpen(false)
    if (item.href) {
      window.open(item.href, item.hint === 'external' ? '_blank' : '_self')
      return
    }
    if (item.kind === 'switch') {
      onSwitch?.(item.profile)
      return
    }
    if (item.kind === 'stop') {
      onStop?.()
      return
    }
    item.run?.(nav)
  }

  if (!open) return null
  const current = items[idx]

  return (
    <div className="palette-scrim" onClick={() => setOpen(false)} role="presentation">
      <div className="palette" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Jump, serve a recipe, stop…"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setIdx((i) => Math.min(items.length - 1, i + 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setIdx((i) => Math.max(0, i - 1))
            } else if (e.key === 'Enter') {
              e.preventDefault()
              run(current)
            }
          }}
        />
        <ul>
          {items.length ? items.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                className={i === idx ? 'on' : ''}
                onMouseEnter={() => setIdx(i)}
                onClick={() => run(item)}
              >
                <span>{item.label}</span>
                {item.hint ? <em>{item.hint}</em> : null}
              </button>
            </li>
          )) : (
            <li className="empty">No matches</li>
          )}
        </ul>
        <p className="palette-hint">Ctrl/Cmd+K · Enter to run · Esc to close</p>
      </div>
    </div>
  )
}
