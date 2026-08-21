import { useEffect, useRef, useState } from 'react'
import { fmtFull } from '../lib/fmt.js'

const DIGITS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
const STEP = 5

function DigitReel({ digit }) {
  const [offset, setOffset] = useState(0)
  const [animate, setAnimate] = useState(false)
  const last = useRef(0)

  useEffect(() => {
    const prev = last.current
    const delta = (digit - prev + 10) % 10
    last.current = digit
    if (delta === 0) return
    setAnimate(true)
    setOffset((current) => (current % 10) + delta)
  }, [digit])

  function onTransitionEnd(e) {
    if (e.propertyName !== 'transform') return
    setAnimate(false)
    setOffset((current) => current % 10)
  }

  return (
    <span className="odo-digit">
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
        if (ch === ',') return <span key={`c${fromRight}`} className="odo-sep">,</span>
        return <DigitReel key={`d${fromRight}`} digit={Number(ch)} />
      })}
    </div>
  )
}
