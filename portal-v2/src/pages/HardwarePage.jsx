import { fmtPct } from '../lib/fmt.js'

function uptime(gpu) {
  return gpu?.uptime_human || '—'
}

export function HardwarePage({ live }) {
  const gpu = live.gpu || {}
  const load = gpu.engine_load || {}
  const net = gpu.network || {}
  const storage = gpu.storage || []
  const hermes = gpu.hermes || {}

  return (
    <div>
      <div className="page-head">
        <h1>Hardware</h1>
        <p>{gpu.gpu_name || 'GPU'} · up {uptime(gpu)} · load {gpu.load_1 ?? '—'} / {gpu.load_5 ?? '—'} / {gpu.load_15 ?? '—'}</p>
      </div>

      <div className="grid grid-3">
        <section className="card">
          <h2>GPU</h2>
          <div className="meters">
            <div>
              <div className="meter-row"><span>Util</span><b>{fmtPct(gpu.gpu_util_pct)}%</b></div>
              <div className="bar gpu" style={{ '--pct': Math.min(1, (Number(gpu.gpu_util_pct) || 0) / 100) }}><i /></div>
            </div>
            <div>
              <div className="meter-row"><span>Memory</span><b>{fmtPct(gpu.memory_used_pct)}% · {Math.round((gpu.memory_used_mb || 0) / 1024)} / {Math.round((gpu.memory_total_mb || 0) / 1024)} GB</b></div>
              <div className="bar mem" style={{ '--pct': Math.min(1, (Number(gpu.memory_used_pct) || 0) / 100) }}><i /></div>
            </div>
            <div className="meter-row"><span>Temp / power</span><b>{gpu.gpu_temp_c ?? '—'}° · {gpu.gpu_power_w ?? '—'} W</b></div>
            {load.max != null ? (
              <div className="meter-row"><span>Engine seqs</span><b>{load.running ?? 0}/{load.max}{load.kv_cache_pct != null ? ` · KV ${fmtPct(load.kv_cache_pct)}%` : ''}</b></div>
            ) : null}
          </div>
        </section>
        <section className="card">
          <h2>CPU</h2>
          <div className="meters">
            <div>
              <div className="meter-row"><span>Util</span><b>{fmtPct(gpu.cpu_util_pct)}%</b></div>
              <div className="bar mem" style={{ '--pct': Math.min(1, (Number(gpu.cpu_util_pct) || 0) / 100) }}><i /></div>
            </div>
            <div className="meter-row"><span>Peak core</span><b>{fmtPct(gpu.cpu_peak_core_pct)}% · {gpu.cpu_cores ?? '—'} cores</b></div>
            <div className="meter-row"><span>Temp</span><b>{gpu.cpu_temp_c ?? '—'}°</b></div>
          </div>
        </section>
        <section className="card">
          <h2>Network</h2>
          <p className="hero-meta tall">
            {net.label || net.iface || 'iface'} · rx {net.rx_mbps ?? gpu.net_rx_mbps ?? '—'} · tx {net.tx_mbps ?? gpu.net_tx_mbps ?? '—'} Mbps
          </p>
          <p className="muted">Hermes {hermes.online ? 'online' : 'offline'}{hermes.container ? ' · container' : ''}{hermes.service ? ' · service' : ''}</p>
        </section>
      </div>

      <section className="card" style={{ marginTop: '1rem' }}>
        <h2>Storage</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Volume</th>
                <th>Role</th>
                <th>Used</th>
                <th>Models</th>
                <th>Path</th>
              </tr>
            </thead>
            <tbody>
              {storage.map((s) => (
                <tr key={s.disk_path || s.label}>
                  <td>
                    <div className="pid">{s.label}</div>
                    <div className="pname">{s.online ? 'online' : 'offline'}</div>
                  </td>
                  <td>{s.role || '—'}</td>
                  <td>{fmtPct(s.used_pct)}% · {s.used_gb ?? '—'} / {s.total_gb ?? '—'} GB</td>
                  <td>{s.models_gb != null ? `${s.models_gb} GB` : '—'}</td>
                  <td>{s.models_path || s.disk_path}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
