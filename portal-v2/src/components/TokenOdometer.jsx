import { useEffect, useRef, useState } from 'react'
import { fmtFull } from '../lib/fmt.js'

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
const STEP = 5

function DigitReel({ digit }) {
  const next = ((Number(digit) % 10) + 10) % 10
  const [offset, setOffset] = useState(next)
  const [animate, setAnimate] = useState(false)
  const [ticking, setTicking] = useState(false)
  const last = useRef(next)
  const primed = useRef(false)
  const tickTimer = useRef(0)

  useEffect(() => {
    if (!primed.current) {
      primed.current = true
      last.current = next
      setAnimate(false)
      setOffset(next)
      return
    }
    const prev = last.current
    const delta = (next - prev + 10) % 10
    last.current = next
    if (delta === 0) return
    setAnimate(true)
    setTicking(true)
    window.clearTimeout(tickTimer.current)
    tickTimer.current = window.setTimeout(() => setTicking(false), 1100)
    setOffset((current) => (current % 10) + delta)
  }, [next])

  useEffect(() => () => window.clearTimeout(tickTimer.current), [])

  function onTransitionEnd(e) {
    if (e.propertyName !== 'transform') return
    setAnimate(false)
    setOffset((current) => current % 10)
  }

  return (
    <span className={`odo-digit${ticking ? ' tick' : ''}`}>
      <span
        className={`odo-reel${animate ? '' : ' snap'}`}
        style={{ transform: `translateY(-${offset * STEP}%)` }}
        onTransitionEnd={onTransitionEnd}
      >
        {[...DIGITS, ...DIGITS].map((d, i) => <i key={i}>{d}</i>)}
      </span>
    </span>
  )
}

export function TokenOdometer({ value }) {
  const target = Math.max(0, Math.round(Number(value) || 0))
  const text = fmtFull(target)

  return (
    <div className="odometer" aria-label={`${text} lifetime tokens`}>
      {text.split('').map((ch, i) => {
        const fromRight = text.length - 1 - i
        if (ch === ',') return <span key={`c${fromRight}`} className="odo-sep">,</span>
        return <DigitReel key={`d${fromRight}`} digit={Number(ch)} />
      })}
    </div>
  )
}
