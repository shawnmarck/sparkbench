import { useEffect, useRef, useState } from 'react'
import { THEMES, applyTheme, currentThemeId } from '../lib/theme.js'

const spark = THEMES.filter((t) => t.source === 'spark')
const omarchyDark = THEMES.filter((t) => t.source === 'omarchy' && t.mode === 'dark')
const omarchyLight = THEMES.filter((t) => t.source === 'omarchy' && t.mode === 'light')

function Swatch({ theme, current, onPick }) {
  return (
    <button
      type="button"
      className={`theme-opt${theme.id === current ? ' on' : ''}`}
      onClick={() => onPick(theme.id)}
    >
      <i
        className="theme-swatch"
        style={{ '--swatch-bg': theme.swatchBg, '--swatch-accent': theme.swatchAccent }}
      />
      <span>{theme.name}</span>
    </button>
  )
}

export function ThemePicker() {
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState(currentThemeId)
  const box = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    function onDoc(ev) {
      if (!box.current?.contains(ev.target)) setOpen(false)
    }
    function onKey(ev) {
      if (ev.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  function pick(id) {
    applyTheme(id)
    setCurrent(id)
  }

  const active = THEMES.find((t) => t.id === current) || THEMES[0]

  return (
    <div className="theme-picker" ref={box}>
      <button
        type="button"
        className="theme-btn"
        title="Theme"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <i
          className="theme-swatch"
          style={{ '--swatch-bg': active.swatchBg, '--swatch-accent': active.swatchAccent }}
        />
        <span className="theme-btn-label">Theme</span>
      </button>
      {open ? (
        <div className="theme-pop" role="dialog" aria-label="Theme picker">
          <p className="theme-group">Spark</p>
          <div className="theme-grid">
            {spark.map((theme) => (
              <Swatch key={theme.id} theme={theme} current={current} onPick={pick} />
            ))}
          </div>
          <p className="theme-group">Omarchy</p>
          <div className="theme-grid">
            {omarchyDark.map((theme) => (
              <Swatch key={theme.id} theme={theme} current={current} onPick={pick} />
            ))}
          </div>
          <p className="theme-group">Omarchy light</p>
          <div className="theme-grid">
            {omarchyLight.map((theme) => (
              <Swatch key={theme.id} theme={theme} current={current} onPick={pick} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
