import { useEffect, useState } from 'react'
import {
  addBenchmasterJob,
  controlBenchmaster,
  getBenchmasterQueue,
  getBenchmasterRuns,
  getBenchmasterStatus,
  removeBenchmasterJob,
} from '../lib/api.js'

const actions = [
  { id: 'resume', label: 'Resume', kind: 'primary' },
  { id: 'pause', label: 'Pause' },
  { id: 'stop_after_current', label: 'Stop after current' },
  { id: 'abort_current_requeue_front', label: 'Abort & requeue', danger: true },
]

function fmtTs(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleString()
  } catch (_e) {
    return String(ts)
  }
}

export function BenchmasterPage({ live }) {
  const [status, setStatus] = useState(null)
  const [queue, setQueue] = useState([])
  const [runs, setRuns] = useState([])
  const [err, setErr] = useState(null)
  const [msg, setMsg] = useState(null)
  const [profileId, setProfileId] = useState('')
  const [jobType, setJobType] = useState('perf_sweep')
  const [busy, setBusy] = useState(false)

  async function refresh() {
    try {
      const [st, q, r] = await Promise.all([
        getBenchmasterStatus(),
        getBenchmasterQueue(),
        getBenchmasterRuns(),
      ])
      setStatus(st)
      setQueue(q.items || [])
      setRuns(r.runs || [])
      setErr(null)
    } catch (e) {
      setErr(e.message || 'benchmaster unreachable')
    }
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 8000)
    return () => clearInterval(t)
  }, [])

  async function control(action) {
    setBusy(true)
    setMsg(null)
    try {
      await controlBenchmaster(action)
      setMsg({ ok: true, text: `Control: ${action}` })
      await refresh()
    } catch (e) {
      setMsg({ ok: false, text: e.message || 'control failed' })
    } finally {
      setBusy(false)
    }
  }

  async function addJob() {
    const id = profileId.trim()
    if (!id) {
      setMsg({ ok: false, text: 'Profile id required' })
      return
    }
    setBusy(true)
    try {
      await addBenchmasterJob({ type: jobType, profileId: id })
      setMsg({ ok: true, text: `Queued ${id}` })
      setProfileId('')
      await refresh()
    } catch (e) {
      setMsg({ ok: false, text: e.message || 'queue failed' })
    } finally {
      setBusy(false)
    }
  }

  async function remove(jobId) {
    try {
      await removeBenchmasterJob(jobId)
      await refresh()
    } catch (e) {
      setMsg({ ok: false, text: e.message || 'remove failed' })
    }
  }

  const current = status?.current_job || status?.attention_job
  const ctrl = status?.control || {}
  const counts = status?.counts || {}
  const recipes = live.recipes || []
  const progress = current?.progress || {}

  return (
    <div>
      <div className="page-head">
        <h1>Benchmaster</h1>
        <p>
          {ctrl.mode || 'paused'}
          {ctrl.stop_after_current ? ' · stop after current' : ''}
          {ctrl.abort_requested ? ' · aborting' : ''}
          {counts.gpu_queued ? ` · gpu queued ${counts.gpu_queued}` : ''}
          {counts.intel_queued ? ` · intel awaiting Mac ${counts.intel_queued}` : ''}
          {status?.intel_claimable ? ' · intel claimable' : ''}
          {status?.worker_alive === false ? ' · worker down' : ''}
          {status?.schedule_open === false ? ' · outside schedule' : ''}
        </p>
      </div>

      <div className="toolbar">
        {actions.map((a) => (
          <button
            key={a.id}
            type="button"
            className={`btn ${a.kind || ''} ${a.danger ? 'danger' : ''}`}
            disabled={busy}
            onClick={() => control(a.id)}
          >
            {a.label}
          </button>
        ))}
        <button type="button" className="btn" onClick={refresh}>Refresh</button>
      </div>
      {err ? <p className="flash err">{err}</p> : null}
      {msg ? <p className={msg.ok ? 'flash ok' : 'flash err'}>{msg.text}</p> : null}

      <div className="grid inf-grid">
        <div className="stack">
          <section className="card">
            <h2>Current</h2>
            {current ? (
              <>
                <p className="hero-meta tall">
                  {current.profile_id} · {current.type}
                  {current.state ? ` · ${current.state}` : ''}
                  {current.awaiting === 'remote_worker' ? ' · awaiting Mac worker' : ''}
                </p>
                <p className="muted">
                  step {progress.step ?? 0}/{progress.total_steps ?? '—'} · {current.id}
                </p>
                {Array.isArray(current.live_phases) && current.live_phases.length ? (
                  <ul className="phase-list">
                    {current.live_phases.map((ph) => (
                      <li key={ph.id || ph.label} className={`phase ${ph.state || ''}`}>
                        {ph.label || ph.id}
                        {ph.detail ? <span className="muted"> · {ph.detail}</span> : null}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : (
              <p className="muted">Idle.</p>
            )}
          </section>
          <section className="card">
            <h2>Enqueue</h2>
            <div className="toolbar tight">
              <input
                className="field grow"
                list="bm-profiles"
                value={profileId}
                onChange={(e) => setProfileId(e.target.value)}
                placeholder="profile id"
              />
              <datalist id="bm-profiles">
                {recipes.map((r) => (
                  <option key={r.id} value={r.id}>{r.name || r.id}</option>
                ))}
              </datalist>
              <select className="field" value={jobType} onChange={(e) => setJobType(e.target.value)}>
                <option value="perf_sweep">perf_sweep</option>
                <option value="ctx_ladder">ctx_ladder</option>
                <option value="kv_sweep">kv_sweep</option>
                <option value="intel_eval">intel_eval</option>
              </select>
              <button type="button" className="btn primary" disabled={busy} onClick={addJob}>Queue</button>
            </div>
          </section>
          <section className="card">
            <h2>Queue · {queue.length}</h2>
            <div className="stack-list">
              {queue.length ? queue.map((job) => {
                const id = job.id
                return (
                  <div key={id} className="stack-row">
                    <div>
                      <div className="pid">{job.profile_id || id}</div>
                      <div className="pname">{job.type} · {job.state || 'queued'}</div>
                    </div>
                    {job.state !== 'running' ? (
                      <button type="button" className="btn" onClick={() => remove(id)}>Remove</button>
                    ) : null}
                  </div>
                )
              }) : <p className="muted">Empty.</p>}
            </div>
          </section>
        </div>
        <section className="card">
          <h2>Recent runs</h2>
          <div className="table-wrap" style={{ maxHeight: '64vh' }}>
            <table>
              <thead>
                <tr>
                  <th>Profile</th>
                  <th>Type</th>
                  <th>Result</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {(runs.slice ? runs.slice(0, 40) : []).map((r, i) => (
                  <tr key={r.run_id || r.id || i}>
                    <td>{r.profile_id}</td>
                    <td>{r.type}</td>
                    <td>{r.aborted ? 'aborted' : r.ok ? 'done' : 'failed'}</td>
                    <td>{fmtTs(r.finished_at || r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}
