import { useMemo, useState } from 'react'
import { fmtTokens } from '../lib/fmt.js'
import {
  HEAT_RANGES,
  calendarWeeks,
  countsOf,
  lastNDates,
  monthLabel,
  ytdDates,
} from '../lib/usage.js'

const DOW = ['', 'M', '', 'W', '', 'F', '']

function levelFor(total, max) {
  if (!total) return 0
  return Math.min(4, 1 + Math.floor((total / max) * 3))
}

export function ActivityCalendar({ days }) {
  const [rangeId, setRangeId] = useState('ytd')
  const [hover, setHover] = useState(null)
  const [selected, setSelected] = useState(null)
  const range = HEAT_RANGES.find((r) => r.id === rangeId) || HEAT_RANGES[0]
  const dates = range.id === 'ytd' ? ytdDates() : lastNDates(range.days)
  const from = dates[0]
  const to = dates[dates.length - 1]

  const byDate = useMemo(() => {
    const m = new Map()
    for (const row of days || []) m.set(row.date, countsOf(row))
    return m
  }, [days])

  const weeks = useMemo(() => calendarWeeks(from, to), [from, to])
  const max = Math.max(1, ...dates.map((d) => byDate.get(d)?.total || 0))
  const focus = hover || selected
  const tip = focus ? { date: focus, ...(byDate.get(focus) || { total: 0, requests: 0 }) } : null

  const monthMarks = weeks.map((week, i) => {
    if (week.some((d) => d.slice(8, 10) === '01')) return { i, label: monthLabel(week.find((d) => d.slice(8, 10) === '01') || week[0]) }
    if (i === 0) return { i: 0, label: monthLabel(week[0]) }
    return null
  })

  return (
    <div className="heat">
      <div className="heat-head">
        <span>Activity</span>
        <div className="heat-ranges">
          {HEAT_RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              className={r.id === rangeId ? 'on' : ''}
              onClick={() => { setRangeId(r.id); setSelected(null) }}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      <div className="heat-cal-wrap">
        <div className="heat-cal">
          <div className="heat-months" style={{ gridTemplateColumns: `22px repeat(${weeks.length}, 14px)` }}>
            <span />
            {weeks.map((week, i) => (
              <span key={week[0]}>{monthMarks[i]?.label || ''}</span>
            ))}
          </div>
          <div className="heat-body">
            <div className="heat-dow">
              {DOW.map((d, i) => <span key={i}>{d}</span>)}
            </div>
            <div className="heat-weeks">
              {weeks.map((week) => (
                <div key={week[0]} className="heat-week">
                  {week.map((date) => {
                    const inRange = date >= from && date <= to
                    const tot = inRange ? (byDate.get(date)?.total || 0) : 0
                    const lvl = inRange ? levelFor(tot, max) : -1
                    const isSel = selected === date
                    const isHov = hover === date
                    return (
                      <button
                        key={date}
                        type="button"
                        disabled={!inRange}
                        className={`heat-cell l${lvl < 0 ? 'x' : lvl}${isSel ? ' sel' : ''}${isHov ? ' hov' : ''}`}
                        aria-label={`${date} ${fmtTokens(tot)} tokens`}
                        onMouseEnter={() => inRange && setHover(date)}
                        onMouseLeave={() => setHover(null)}
                        onClick={() => inRange && setSelected((cur) => (cur === date ? null : date))}
                      />
                    )
                  })}
                </div>
              ))}
            </div>
          </div>
          <div className="heat-foot">
            <span className="heat-legend">Less <i /><i /><i /><i /><i /> More</span>
          </div>
        </div>
      </div>
      <p className="heat-tip">
        {tip
          ? `${tip.date} · ${fmtTokens(tip.total)} tokens · ${tip.requests || 0} req${selected === tip.date ? ' · selected' : ''}`
          : `${range.id === 'ytd' ? 'Year to date' : `Last ${range.label.toLowerCase()}`}. Click a day to pin it. Store keeps a year of daily totals.`}
      </p>
    </div>
  )
}
