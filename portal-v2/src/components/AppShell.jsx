import { NavLink } from 'react-router-dom'
import { fmtPct, shortName } from '../lib/fmt.js'

const operate = [
  { to: '/', label: 'Home', end: true },
  { to: '/inference', label: 'Inference' },
  { to: '/benchmaster', label: 'Benchmaster' },
]
const browse = [
  { to: '/explore', label: 'Explore' },
]

function servingTone(active, ready) {
  if (!active) return 'down'
  if (ready) return 'ok'
  return 'warn'
}

export function AppShell({ live, children }) {
  const active = live.inference?.active
  const ready = Boolean(active?.ready ?? live.inference?.ready)
  const gpu = live.gpu
  const tone = servingTone(active, ready)

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/v2/">
          Sparky
          <small>home lab</small>
          <span className="v2">new</span>
        </a>
        <div className="pills">
          <span className={`pill ${tone}`} title={active?.id || 'No profile'}>
            <i className="dot" />
            <b>{active ? shortName(active.name, active.id) : 'offline'}</b>
          </span>
          <span className="pill">
            GPU <b>{fmtPct(gpu?.gpu_util_pct)}</b>%
          </span>
          <span className="pill">
            MEM <b>{fmtPct(gpu?.memory_used_pct)}</b>%
          </span>
          {live.error ? <span className="pill down">API {live.error}</span> : null}
        </div>
        <a className="legacy-link" href="/">Legacy UI</a>
      </header>
      <nav className="sidenav" aria-label="Primary">
        <div className="nav-group">
          <div className="nav-label">Operate</div>
          {operate.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
              {item.label}
            </NavLink>
          ))}
        </div>
        <div className="nav-group">
          <div className="nav-label">Browse</div>
          {browse.map((item) => (
            <NavLink key={item.to} to={item.to} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
              {item.label}
            </NavLink>
          ))}
        </div>
        <div className="nav-group">
          <div className="nav-label">External</div>
          <a className="nav-item" href="/hermes/">Hermes</a>
          <a className="nav-item" href="http://sparky:3000/">Chat</a>
          <a className="nav-item" href="http://sparky:19999/v3/">Netdata</a>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  )
}
