import { useEffect, useRef, useState } from 'react'
import { getInferenceLogs } from '../lib/api.js'

const LOG_NOISE = /\/v1\/models|\/metrics|healthz|GET \/health/i
const STORE = 'spark-v2-engine-log'
const FOLLOW_STORE = 'spark-v2-log-follow'

function usefulLog(line) {
  const s = typeof line === 'string' ? line : JSON.stringify(line)
  return !LOG_NOISE.test(s)
}

function formatLines(data, { filter = true } = {}) {
  const fmt = (line) => (typeof line === 'string' ? line : JSON.stringify(line))
  const raw = (data?.sections || []).flatMap((s) => (s.lines || []).map(fmt))
  const all = raw.length ? raw : (data?.lines || []).map(fmt)
  return filter ? all.filter(usefulLog) : all
}

export function useEngineLog(lineCount = 80) {
  const [logs, setLogs] = useState(null)
  const [logErr, setLogErr] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function tick() {
      try {
        const data = await getInferenceLogs(lineCount)
        if (cancelled) return
        setLogs(data)
        setLogErr(null)
      } catch (err) {
        if (!cancelled) setLogErr(err.message || 'logs unavailable')
      }
    }
    tick()
    const t = setInterval(tick, 2500)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [lineCount])

  return {
    logs,
    logErr,
    switching: Boolean(logs?.switch?.running),
    lines: formatLines(logs),
    rawLines: formatLines(logs, { filter: false }),
  }
}

function pinBottom(el) {
  if (el) el.scrollTop = el.scrollHeight
}

function useStickBottom(dep) {
  const ref = useRef(null)
  useEffect(() => {
    const id = requestAnimationFrame(() => pinBottom(ref.current))
    return () => cancelAnimationFrame(id)
  }, [dep])
  return ref
}

function useFollowLatest(dep) {
  const ref = useRef(null)
  const [follow, setFollow] = useState(() => {
    try {
      return window.localStorage.getItem(FOLLOW_STORE) !== '0'
    } catch {
      return true
    }
  })
  const followRef = useRef(follow)
  followRef.current = follow

  useEffect(() => {
    if (!follow) return undefined
    const id = requestAnimationFrame(() => pinBottom(ref.current))
    return () => cancelAnimationFrame(id)
  }, [dep, follow])

  function onScroll() {
    const el = ref.current
    if (!el) return
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight
    const atBottom = gap < 48
    if (atBottom === followRef.current) return
    followRef.current = atBottom
    setFollow(atBottom)
    try {
      window.localStorage.setItem(FOLLOW_STORE, atBottom ? '1' : '0')
    } catch {
      /* ignore */
    }
  }

  function setLocked(next) {
    followRef.current = next
    setFollow(next)
    try {
      window.localStorage.setItem(FOLLOW_STORE, next ? '1' : '0')
    } catch {
      /* ignore */
    }
    if (next) pinBottom(ref.current)
  }

  return { ref, follow, onScroll, setLocked }
}

export function EngineLogDock() {
  const { lines, logErr, switching } = useEngineLog(80)
  const [open, setOpen] = useState(() => {
    try {
      return window.localStorage.getItem(STORE) !== '0'
    } catch (_e) {
      return true
    }
  })
  const shown = lines.slice(-12)
  const preRef = useStickBottom(shown.join('\n'))

  useEffect(() => {
    if (switching) setOpen(true)
  }, [switching])

  function toggle() {
    setOpen((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(STORE, next ? '1' : '0')
      } catch (_e) { /* ignore */ }
      return next
    })
  }

  return (
    <aside className={`log-dock${open ? '' : ' closed'}`} aria-label="Engine log">
      <div className="log-dock-head">
        <button type="button" onClick={toggle} aria-expanded={open}>
          <h2>Engine log</h2>
          <span>
            {switching ? 'switch in progress' : lines.length ? `${lines.length} lines` : 'idle'}
          </span>
          <em>{open ? 'Hide' : 'Show'}</em>
        </button>
        <a
          className="log-pop"
          href="/v2/inference/log"
          title="Open the full engine log"
        >
          Open full
        </a>
      </div>
      {open ? (
        <>
          {logErr ? <p className="err">{logErr}</p> : null}
          <pre ref={preRef} className="log dock">
            {shown.length ? shown.join('\n') : 'No non-health-check lines right now.'}
          </pre>
        </>
      ) : null}
    </aside>
  )
}

export function LogPage() {
  const { rawLines, lines, logErr, switching, logs } = useEngineLog(200)
  const [noise, setNoise] = useState(false)
  const shown = noise ? rawLines : lines
  const { ref: preRef, follow, onScroll, setLocked } = useFollowLatest(shown.join('\n'))
  const title = logs?.file || logs?.engine || 'engine'

  return (
    <div className="log-page">
      <header className="log-page-head">
        <h1>Engine log</h1>
        <span>
          {title}
          {switching ? ' · switch in progress' : ''}
          {shown.length ? ` · ${shown.length} lines` : ''}
        </span>
        <label>
          <input type="checkbox" checked={follow} onChange={(e) => setLocked(e.target.checked)} />
          Lock to latest
        </label>
        <label>
          <input type="checkbox" checked={noise} onChange={(e) => setNoise(e.target.checked)} />
          Show health checks
        </label>
      </header>
      {logErr ? <p className="err">{logErr}</p> : null}
      <pre ref={preRef} className="log page" onScroll={onScroll}>
        {shown.length ? shown.join('\n') : 'No log lines yet.'}
      </pre>
    </div>
  )
}
