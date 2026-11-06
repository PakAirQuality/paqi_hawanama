'use client'

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { classifyPm25, pm25Color } from '@/lib/aqi'
import { stationNowcastPoints } from '@/lib/timeline'
import { formatPkt, hourLabel } from '@/lib/time'
import type { NowcastResponse } from '@/components/analyst-desk/types'
import { Skeleton } from './Skeleton'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

export interface HourlyPoint {
  hour: string
  pm25: number | null
  /** A nowcast value ahead of now, drawn as a dashed tail */
  forecast?: boolean
  lead?: number
}

interface StationRef {
  station_id?: string
  name: string
  city: string
}

const pkHour = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', hour12: false, timeZone: 'Asia/Karachi' })

/** The station's last 24 hourly readings and, when a nowcast is given, its hours still ahead. */
export function useStationHourly(station: StationRef | null, date: string | null, nowcast?: NowcastResponse) {
  const id = station?.station_id
  const { data: hourly, isLoading } = useQuery({
    queryKey: ['station-hourly', id, date],
    queryFn: async () => {
      if (!id) return null
      const dateParam = date ? `&date=${date}` : ''
      const res = await fetch(`${API_BASE}/api/v1/dashboard/stations/${id}/history/pm25?hours=24${dateParam}&all_providers=true`)
      if (!res.ok) return null
      return res.json() as Promise<{ timestamp_pk: string; pm25: number | null }[]>
    },
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
  })

  const observed = useMemo<HourlyPoint[]>(
    () => (hourly ?? []).map(d => ({ hour: pkHour(d.timestamp_pk), pm25: d.pm25 })),
    [hourly],
  )

  // Nowcast hours still ahead of now (as of first render), after the last observed hour
  const [openedAt] = useState(() => Date.now())
  const nowcastPoints = useMemo(
    () => (station
      ? stationNowcastPoints(nowcast, { station_id: station.station_id, name: station.name, city: station.city })
        .filter(p => Date.parse(p.valid_time) > openedAt)
      : []),
    [nowcast, station, openedAt],
  )

  const points = useMemo<HourlyPoint[]>(
    () => [...observed, ...nowcastPoints.map(p => ({ hour: pkHour(p.valid_time), pm25: p.pm25, forecast: true, lead: p.lead }))],
    [observed, nowcastPoints],
  )

  return { loading: !!id && isLoading, observed, nowcastPoints, points }
}

/** Interactive hourly PM2.5 bars: hover, touch or arrow keys to read any hour. Nowcast hours are a dashed tail. */
export function PM25BarChart({ data, height = 150 }: { data: HourlyPoint[]; height?: number }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [active, setActive] = useState<number | null>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const [tipWidth, setTipWidth] = useState(0)

  useLayoutEffect(() => {
    if (tipRef.current) setTipWidth(tipRef.current.offsetWidth)
  }, [active])

  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    setWidth(el.clientWidth)
    const ro = new ResizeObserver(() => setWidth(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const H = height
  const pad = { top: 28, right: 4, bottom: 22, left: 4 }
  const vals = data.filter(d => d.pm25 != null).map(d => d.pm25 as number)

  if (!vals.length) {
    return <div ref={wrapRef} className="flex items-center justify-center text-xs text-slate-600" style={{ height: H }}>No data</div>
  }

  const maxVal = Math.ceil(Math.max(...vals, 20) / 10) * 10
  const w = Math.max(0, width - pad.left - pad.right)
  const h = H - pad.top - pad.bottom
  const slot = w / data.length
  const barW = Math.max(3, slot - 3)
  const step = Math.max(1, Math.floor(data.length / 5))

  const move = (delta: number) => {
    setActive(cur => {
      const start = cur ?? (delta > 0 ? -1 : data.length)
      let i = start + delta
      while (i >= 0 && i < data.length && data[i].pm25 == null) i += delta
      return i >= 0 && i < data.length ? i : cur
    })
  }

  const a = active != null ? data[active] : null
  const tip = a && a.pm25 != null ? (() => {
    const band = classifyPm25(a.pm25)
    const cx = pad.left + (active as number) * slot + slot / 2
    const left = Math.max(0, Math.min(cx - tipWidth / 2, width - tipWidth))
    return { left, label: a.forecast ? `${hourLabel(a.hour)} (+${a.lead} h)` : hourLabel(a.hour), value: Math.round(a.pm25), band }
  })() : null

  // The dashed tail: from the last observed hour through each nowcast point
  const cxOf = (i: number) => pad.left + i * slot + slot / 2
  const cyOf = (v: number) => pad.top + h - Math.max(2, (v / maxVal) * h)
  const lastObs = data.map((d, i) => ({ d, i })).filter(x => !x.d.forecast && x.d.pm25 != null).at(-1)
  const tailIdx = data.map((d, i) => ({ d, i })).filter(x => x.d.forecast && x.d.pm25 != null)
  const tailPath = tailIdx.length
    ? [...(lastObs ? [lastObs] : []), ...tailIdx].map(x => `${cxOf(x.i)},${cyOf(x.d.pm25 as number)}`).join(' ')
    : null
  // Where the nowcast starts: a faint band behind the hours ahead
  const firstAhead = tailIdx[0]?.i

  // Axis labels: every few hours, each nowcast lead, but never two closer than they can be read.
  // Walk from the right so the last nowcast lead always keeps its label.
  const labelled = new Set<number>()
  {
    let lastX = Infinity
    for (let i = data.length - 1; i >= 0; i--) {
      const d = data[i]
      const wanted = d.forecast ? true : i % step === 0
      if (!wanted) continue
      const x = pad.left + i * slot + slot / 2
      const minGap = d.forecast || data[i + 1]?.forecast ? 32 : 22
      if (lastX - x < minGap) continue
      labelled.add(i)
      lastX = x
    }
  }

  return (
    <div ref={wrapRef} className="relative select-none" style={{ height: H }}>
      {width > 0 && (
        <svg
          width={width}
          height={H}
          tabIndex={0}
          role="img"
          aria-label={tailIdx.length ? `Hourly PM2.5 for the last 24 hours and the expected values ${tailIdx.map(x => `${x.d.lead} hours`).join(', ')} ahead (dashed). Use the left and right arrow keys to read each hour.` : `Hourly PM2.5 for the last 24 hours. Use the left and right arrow keys to read each hour.`}
          onKeyDown={e => {
            if (e.key === 'ArrowRight') { e.preventDefault(); move(1) }
            else if (e.key === 'ArrowLeft') { e.preventDefault(); move(-1) }
            else if (e.key === 'Escape') setActive(null)
          }}
          onBlur={() => setActive(null)}
          onPointerLeave={() => setActive(null)}
          className="block outline-none focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-slate-900/30"
        >
          {firstAhead != null && (
            <rect x={pad.left + firstAhead * slot} y={pad.top - 6} width={w - firstAhead * slot} height={h + 6} rx={6} fill="#0f172a" fillOpacity={0.035} />
          )}
          {tailPath && <polyline points={tailPath} fill="none" stroke="#475569" strokeWidth="1.5" strokeDasharray="4 3" strokeLinejoin="round" />}
          {data.map((d, i) => {
            const x = pad.left + i * slot + (slot - barW) / 2
            const bh = d.pm25 == null ? 0 : Math.max(2, (d.pm25 / maxVal) * h)
            const y = pad.top + h - bh
            return (
              <g key={i}>
                {d.pm25 != null && d.forecast && (
                  <circle
                    cx={cxOf(i)} cy={cyOf(d.pm25)} r={Math.min(4, Math.max(2.5, barW / 2))}
                    fill="#fff" stroke={pm25Color(d.pm25)} strokeWidth="2"
                    opacity={active == null || active === i ? 1 : 0.4}
                    style={{ transition: 'opacity 120ms' }}
                  />
                )}
                {d.pm25 != null && !d.forecast && (
                  <rect
                    x={x} y={y} width={barW} height={bh} rx={Math.min(2.5, barW / 2)}
                    fill={pm25Color(d.pm25)}
                    opacity={active == null || active === i ? 1 : 0.4}
                    className="bar-grow"
                    style={{ transition: 'opacity 120ms', animationDelay: `${i * 14}ms` }}
                  />
                )}
                {/* full-height hit area so thin bars are easy to hover or tap */}
                <rect
                  x={pad.left + i * slot} y={0} width={slot} height={H} fill="transparent"
                  onPointerEnter={() => d.pm25 != null && setActive(i)}
                  onPointerDown={() => d.pm25 != null && setActive(i)}
                />
                {labelled.has(i) && (
                  <text x={pad.left + i * slot + slot / 2} y={H - 6} textAnchor="middle" fontSize="11" fill={d.forecast ? '#475569' : '#64748b'} fontStyle={d.forecast ? 'italic' : undefined}>{d.forecast ? `+${d.lead}h` : d.hour}</text>
                )}
              </g>
            )
          })}
        </svg>
      )}

      {tip && (
        <div
          ref={tipRef}
          className="pointer-events-none absolute top-0 max-w-full truncate whitespace-nowrap rounded-lg bg-slate-900 px-2.5 py-1 text-xs text-white shadow-lg"
          style={{ left: tip.left }}
          role="status"
        >
          <span className="tabular-nums">{tip.label}</span>
          <span className="mx-1.5 font-semibold tabular-nums">{tip.value} µg/m³</span>
          <span className="opacity-80">{tip.band.label}</span>
        </div>
      )}
    </div>
  )
}

/** Skeleton, chart or empty note for a station's last 24 hours (plus the nowcast tail). */
export function StationHourlyChart({ station, date, nowcast, height = 150, showNote = true }: {
  station: StationRef
  date: string | null
  nowcast?: NowcastResponse
  height?: number
  /** The line under the chart that explains the dashed tail */
  showNote?: boolean
}) {
  const { loading, points, nowcastPoints } = useStationHourly(station, date, nowcast)
  return (
    <>
      {loading ? (
        <div className="flex items-end gap-1 px-1 pb-6" style={{ height }} aria-busy="true" aria-label="Loading chart">
          {Array.from({ length: 24 }, (_, i) => <Skeleton key={i} className="flex-1 rounded-t-md" style={{ height: `${30 + ((i * 37) % 70)}%` }} />)}
        </div>
      ) : points.length ? (
        <PM25BarChart data={points} height={height} />
      ) : (
        <div className="flex items-center justify-center text-xs text-slate-600" style={{ height }}>No hourly data available</div>
      )}
      {showNote && nowcastPoints.length > 0 && (
        <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
          Dashed: expected hourly PM2.5 {nowcastPoints.map(p => `+${p.lead} h`).join(', ')} ahead
          {nowcast ? `, issued ${formatPkt(nowcast.init_time)}` : ''}.
          {nowcastPoints[0].basis === 'neighbours' ? ' Estimated from nearby stations: this station had no recent readings.' : ''}
        </p>
      )}
    </>
  )
}
