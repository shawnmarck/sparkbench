import { useEffect, useState } from 'react'
import {
  getHfModel,
  getHfQueue,
  getHfStatus,
  queueHfExplore,
  removeHfQueueItem,
  searchHf,
  startHfDownload,
  trendingHf,
} from '../lib/api.js'

function itemId(item) {
  return item.id || item.item_id || item.repo
}

export function ExplorePage() {
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('trending')
  const [models, setModels] = useState([])
  const [queue, setQueue] = useState({ explore: [], download: [] })
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [detail, setDetail] = useState(null)

  async function loadBrowse(nextQ = q, nextMode = mode) {
    setBusy(true)
    setMsg(null)
    try {
      const data = nextQ.trim()
        ? await searchHf(nextQ.trim())
        : await trendingHf(nextMode)
      setModels(data.models || [])
    } catch (err) {
      setMsg({ ok: false, text: err.message || 'browse failed' })
    } finally {
      setBusy(false)
    }
  }

  async function loadQueue() {
    try {
      const [st, qdata] = await Promise.all([getHfStatus(), getHfQueue()])
      setStatus(st)
      setQueue({
        explore: qdata?.explore || qdata?.queue?.explore || [],
        download: qdata?.download || qdata?.queue?.download || [],
      })
    } catch (_err) {
      /* keep last good queue */
    }
  }

  useEffect(() => {
    loadBrowse('', 'trending')
    loadQueue()
    const t = setInterval(loadQueue, 8000)
    return () => clearInterval(t)
  }, [])

  async function openDetail(repo) {
    setMsg(null)
    try {
      const data = await getHfModel(repo)
      setDetail({
        repo,
        model: data.model || data,
        variants: data.variants || [],
      })
    } catch (err) {
      setMsg({ ok: false, text: err.message || 'model lookup failed' })
    }
  }

  async function shortlist(repo) {
    setMsg(null)
    try {
      await queueHfExplore(repo)
      setMsg({ ok: true, text: `Shortlisted ${repo}` })
      loadQueue()
    } catch (err) {
      setMsg({ ok: false, text: err.message || 'queue failed' })
    }
  }

  async function download(id) {
    try {
      await startHfDownload(id)
      setMsg({ ok: true, text: 'Download started' })
      loadQueue()
    } catch (err) {
      setMsg({ ok: false, text: err.message || 'download failed' })
    }
  }

  async function remove(id, which) {
    try {
      await removeHfQueueItem(id, which)
      loadQueue()
    } catch (err) {
      setMsg({ ok: false, text: err.message || 'remove failed' })
    }
  }

  return (
    <div>
      <div className="page-head">
        <h1>Explore</h1>
        <p>
          Hugging Face search and shortlist. Worker {status?.ok ? 'up' : 'unknown'}
          {status?.worker_alive === false ? ' · down' : ''}.
        </p>
      </div>

      <div className="toolbar">
        <input
          className="field grow"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search Hugging Face…"
          onKeyDown={(e) => {
            if (e.key === 'Enter') loadBrowse()
          }}
        />
        <button type="button" className="btn primary" disabled={busy} onClick={() => loadBrowse()}>
          Search
        </button>
        <button
          type="button"
          className={`btn ${mode === 'trending' && !q ? 'on' : ''}`}
          onClick={() => { setMode('trending'); setQ(''); loadBrowse('', 'trending') }}
        >
          Trending
        </button>
        <button
          type="button"
          className={`btn ${mode === 'new' && !q ? 'on' : ''}`}
          onClick={() => { setMode('new'); setQ(''); loadBrowse('', 'new') }}
        >
          Recent
        </button>
      </div>
      {msg ? <p className={msg.ok ? 'flash ok' : 'flash err'}>{msg.text}</p> : null}

      <div className="grid inf-grid">
        <section className="card">
          <h2>{busy ? 'Loading…' : `${models.length} models`}</h2>
          <div className="stack-list">
            {models.length ? models.map((m) => {
              const repo = m.id || m.repo || m.modelId
              return (
                <div key={repo} className="stack-row">
                  <div>
                    <div className="pid">{repo}</div>
                    <div className="pname">
                      {(m.downloads != null ? `${m.downloads} dl` : '')}
                      {m.likes != null ? ` · ${m.likes} likes` : ''}
                    </div>
                  </div>
                  <div className="row-actions">
                    <button type="button" className="btn" onClick={() => openDetail(repo)}>Detail</button>
                    <button type="button" className="btn" onClick={() => shortlist(repo)}>Shortlist</button>
                  </div>
                </div>
              )
            }) : (
              <p className="muted">{busy ? 'Searching…' : 'No results.'}</p>
            )}
          </div>
        </section>

        <div className="stack">
          {detail ? (
            <section className="card">
              <h2>Detail</h2>
              <p className="pid">{detail.repo}</p>
              <p className="muted">{detail.model?.pipeline_tag || detail.model?.library_name || 'model'}</p>
              {detail.variants.length ? (
                <div className="stack-list">
                  {detail.variants.slice(0, 8).map((v) => (
                    <div key={v.id || v.label || v.inventory_path} className="stack-row">
                      <div>
                        <div className="pid">{v.label || 'variant'}</div>
                        <div className="pname">
                          {v.size_human || ''}
                          {v.engine ? ` · ${v.engine}` : ''}
                          {v.spark_fit_label ? ` · ${v.spark_fit_label}` : ''}
                        </div>
                      </div>
                      <button type="button" className="btn" onClick={() => shortlist(detail.repo)}>Shortlist</button>
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
          ) : null}
          <section className="card">
            <h2>Shortlist · {queue.explore.length}</h2>
            <div className="stack-list">
              {queue.explore.length ? queue.explore.slice().reverse().map((item) => {
                const id = itemId(item)
                return (
                  <div key={id} className="stack-row">
                    <div>
                      <div className="pid">{item.repo || id}</div>
                      <div className="pname">{item.state || item.status || 'queued'}{item.variant_label ? ` · ${item.variant_label}` : ''}</div>
                    </div>
                    <div className="row-actions">
                      <button type="button" className="btn" onClick={() => download(id)}>Download</button>
                      <button type="button" className="btn" onClick={() => remove(id, 'explore')}>Remove</button>
                    </div>
                  </div>
                )
              }) : <p className="muted">Empty.</p>}
            </div>
          </section>
          <section className="card">
            <h2>Downloads · {queue.download.length}</h2>
            <div className="stack-list">
              {queue.download.length ? queue.download.slice().reverse().map((item) => {
                const id = itemId(item)
                return (
                  <div key={id} className="stack-row">
                    <div>
                      <div className="pid">{item.repo || id}</div>
                      <div className="pname">
                        {item.state || item.status || 'queued'}
                        {item.plan?.size_human || item.snapshot?.size_human ? ` · ${item.plan?.size_human || item.snapshot.size_human}` : ''}
                      </div>
                    </div>
                    <button type="button" className="btn" onClick={() => remove(id, 'download')}>Remove</button>
                  </div>
                )
              }) : <p className="muted">Empty.</p>}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
