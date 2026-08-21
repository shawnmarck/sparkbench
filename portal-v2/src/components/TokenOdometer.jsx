import { useEffect, useRef, useState } from 'react'
import { fmtFull } from '../lib/fmt.js'

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
const STEP = 5

function DigitReel({ digit }) {
  const [offset, setOffset] = useState(0)
  const [animate, setAnimate] = useState(false)
  const [ticking, setTicking] = useState(false)
  const last = useRef(0)
  const primed = useRef(false)
  const tickTimer = useRef(0)

  useEffect(() => {
    const prev = last.current
    const delta = (digit - prev + 10) % 10
    last.current = digit
    if (delta === 0) return
    setAnimate(true)
    if (primed.current) {
      setTicking(true)
      window.clearTimeout(tickTimer.current)
      tickTimer.current = window.setTimeout(() => setTicking(false), 1100)
    } else {
      primed.current = true
    }
    setOffset((current) => (current % 10) + delta)
  }, [digit])

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
  const [shown, setShown] = useState(0)

  useEffect(() => {
    const start = requestAnimationFrame(() => setShown(target))
    return () => cancelAnimationFrame(start)
  }, [target])

  const text = fmtFull(shown)

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
