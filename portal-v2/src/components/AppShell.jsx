import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { fmtPct, shortName } from '../lib/fmt.js'
import { PopOut } from './PopOut.jsx'
import { ThemePicker } from './ThemePicker.jsx'

const operate = [
  { to: '/', label: 'Home', end: true },
  { to: '/inference', label: 'Inference' },
  { to: '/inference/log', label: 'Engine log' },
  { to: '/benchmaster', label: 'Benchmaster' },
  { to: '/activity', label: 'Activity' },
  { to: '/hardware', label: 'Hardware' },
]
const browse = [
  { to: '/explore', label: 'Explore' },
  { to: '/models', label: 'Models' },
]
const external = [
  { href: '/hermes/', label: 'Hermes' },
  { href: 'http://sparky:3000/', label: 'Chat' },
  { href: 'http://sparky:19999/v3/', label: 'Netdata' },
]

function servingTone(active, ready) {
  if (!active) return 'down'
  if (ready) return 'ok'
  return 'warn'
}

export function AppShell({ live, children }) {
  const [navOpen, setNavOpen] = useState(false)
  const active = live.inference?.active
  const ready = Boolean(active?.ready ?? live.inference?.ready)
  const gpu = live.gpu
  const tone = servingTone(active, ready)

  return (
    <div className="app">
      <header className="topbar">
        <button type="button" className="btn nav-toggle" onClick={() => setNavOpen((v) => !v)}>Menu</button>
        <a className="brand" href="/v2/">SparkBench</a>
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
          <span className="pill" title="GPU and CPU package temps">
            <b>{gpu?.gpu_temp_c ?? '—'}</b>° · <b>{gpu?.cpu_temp_c ?? '—'}</b>°
          </span>
          {live.error ? <span className="pill down">API {live.error}</span> : null}
        </div>
        <ThemePicker />
        <button type="button" className="kbd-hint" title="Command palette" onClick={() => window.dispatchEvent(new Event('spark-palette'))}>
          Ctrl K
        </button>
        <a className="legacy-link" href="/">Legacy UI</a>
      </header>
      <nav className={`sidenav${navOpen ? ' open' : ''}`} aria-label="Primary" onClick={() => setNavOpen(false)}>
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
          {external.map((item) => (
            <a
              key={item.href}
              className="nav-item ext"
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {item.label}
              <PopOut />
            </a>
          ))}
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  )
}
