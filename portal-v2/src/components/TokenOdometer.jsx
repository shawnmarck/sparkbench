import { useEffect, useRef, useState } from 'react'
import { fmtFull } from '../lib/fmt.js'

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

export function TokenOdometer({ value }) {
  const target = Math.max(0, Math.round(Number(value) || 0))
  const [shown, setShown] = useState(0)
  const [ticking, setTicking] = useState(false)
  const prev = useRef(0)
  const tickTimer = useRef(0)

  useEffect(() => {
    const grew = target > prev.current && prev.current > 0
    prev.current = target
    const start = requestAnimationFrame(() => setShown(target))
    if (grew) {
      setTicking(true)
      window.clearTimeout(tickTimer.current)
      tickTimer.current = window.setTimeout(() => setTicking(false), 900)
    }
    return () => cancelAnimationFrame(start)
  }, [target])

  useEffect(() => () => window.clearTimeout(tickTimer.current), [])

  const text = fmtFull(shown)

  return (
    <div
      className={`odometer${ticking ? ' tick' : ''}`}
      aria-label={`${text} lifetime tokens`}
    >
      {text.split('').map((ch, i) => {
        const fromRight = text.length - 1 - i
        if (ch === ',') {
          return <span key={`c${fromRight}`} className="odo-sep">,</span>
        }
        const digit = Number(ch)
        return (
          <span key={`d${fromRight}`} className="odo-digit">
            <span className="odo-reel" style={{ transform: `translateY(-${digit * 10}%)` }}>
              {DIGITS.map((d) => <i key={d}>{d}</i>)}
            </span>
          </span>
        )
      })}
    </div>
  )
}
