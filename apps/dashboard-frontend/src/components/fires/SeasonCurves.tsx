'use client'

import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { SeasonsResponse, SeasonYear } from './api'
import { dayLabel, fmtCompact, fmtInt } from './format'
import { axisTicks, lastNonNullIndex, niceMax, stackPx, toChartRows, yearKey } from './seasonAlign'

const COLORS = { current: '#dc2626', last: '#0f172a', reference: '#cbd5e1' } as const
const WIDTHS = { current: 2.25, last: 1.75, reference: 1.25 } as const
const CHART_H = 340
const X_AXIS_H = 30                                                      // Recharts default
const MARGIN = { top: 14, right: 46, bottom: 4, left: 0 }
const PLOT_TOP = MARGIN.top
const PLOT_H = CHART_H - MARGIN.top - MARGIN.bottom - X_AXIS_H

export function SeasonCurves({ data }: { data: SeasonsResponse }) {
  const [showTable, setShowTable] = useState(false)
  const rows = useMemo(() => toChartRows(data), [data])
  const ticks = useMemo(() => axisTicks(data.days), [data.days])
  const yMax = useMemo(() => niceMax(data.years), [data.years])
  const years = useMemo(() => [...data.years].sort((a, b) => rank(a) - rank(b)), [data.years])     // references first, current last (on top)
  const current = years.find(y => y.role === 'current')
  const currentEnd = current ? lastNonNullIndex(current.r7) : -1
  // year labels for the finished seasons sit in a column at the right edge, stacked so they never overlap
  const column = useMemo(() => {
    const items = years.filter(y => y.role !== 'current').map(y => {
      const idx = lastNonNullIndex(y.r7)
      const v = idx >= 0 ? (y.r7[idx] ?? 0) : 0
      return { key: yearKey(y.year), y: PLOT_TOP + (1 - v / yMax) * PLOT_H, year: y }
    })
    const pos = stackPx(items.map(i => ({ key: i.key, y: i.y })), 12, PLOT_TOP + PLOT_H)
    return items.map(i => ({ ...i, top: pos[i.key] }))
  }, [years, yMax])

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[12px] text-slate-600">Fires a day, 7-day mean · each line is one {data.season.id === 'rice' ? '1 Oct – 30 Nov' : '15 Apr – 31 May'} season</p>
        <p className="text-[11px] text-slate-500">
          <span className="font-semibold text-[#dc2626]">{data.season.year}</span> in red · {data.season.year - 1} in black · earlier years grey · dashed = thin archive year
        </p>
      </div>
      <div className="relative rounded-lg border border-slate-100 bg-white p-2" style={{ width: '100%', height: CHART_H + 16 }}>
        <div style={{ width: '100%', height: CHART_H }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={MARGIN}>
              <CartesianGrid horizontal vertical={false} strokeDasharray="4 4" stroke="#e2e8f0" />
              <XAxis dataKey="d" type="number" domain={[0, data.days.length - 1]} ticks={ticks} tickFormatter={i => dayLabel(data.days[i] ?? '')}
                axisLine={{ stroke: '#e2e8f0' }} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} height={X_AXIS_H} />
              <YAxis orientation="left" domain={[0, yMax]} axisLine={false} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} width={40}
                tickFormatter={v => fmtCompact(Number(v))} />
              <Tooltip content={<CurvesTooltip years={data.years} days={data.days} />} cursor={{ stroke: '#cbd5e1' }} />
              {data.today_index != null && !data.season.complete && (
                <ReferenceLine x={data.today_index} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: 'yesterday', position: 'top', fontSize: 10, fill: '#64748b' }} />
              )}
              {years.map(y => {
                const key = yearKey(y.year)
                const isCurrent = y.role === 'current'
                return (
                  <Line key={key} dataKey={key} type="monotone" dot={false} isAnimationActive={false} connectNulls={false}
                    stroke={COLORS[y.role]} strokeWidth={WIDTHS[y.role]} strokeDasharray={y.suspect_days > 0 ? '4 3' : undefined}
                    activeDot={{ r: 3, strokeWidth: 0 }}
                    label={isCurrent ? (props: { x?: number | string; y?: number | string; index?: number }) => {
                      if (props.index !== currentEnd || props.x == null || props.y == null) return <g key={`${key}-${props.index}`} />
                      return (
                        <text key={`${key}-label`} x={Number(props.x) + 6} y={Number(props.y) + 3} fontSize={10} fontWeight={700} fill={COLORS.current}>
                          {y.year}
                        </text>
                      )
                    } : undefined} />
                )
              })}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="pointer-events-none absolute right-2 top-2 w-10 text-[10px] leading-none" aria-hidden style={{ height: CHART_H }}>
          {column.map(c => (
            <span key={c.key} className="absolute right-0" style={{ top: c.top - 5, fontWeight: c.year.role === 'last' ? 700 : 500, color: c.year.role === 'last' ? COLORS.last : '#94a3b8' }}>
              {c.year.year}{c.year.suspect_days > 0 ? '*' : ''}
            </span>
          ))}
        </div>
      </div>
      <button type="button" onClick={() => setShowTable(v => !v)} className="mt-2 text-[12px] text-slate-600 underline-offset-2 hover:underline" aria-expanded={showTable}>
        {showTable ? 'Hide season totals' : 'Show season totals as a table'}
      </button>
      {showTable && (
        <table className="mt-2 w-full text-[12px] tabular-nums">
          <thead><tr className="text-left text-slate-500"><th className="py-1 pr-3 font-medium">Season</th><th className="py-1 pr-3 font-medium">Fires, whole season</th><th className="py-1 pr-3 font-medium">Fires to the same date</th><th className="py-1 font-medium">Days with data</th></tr></thead>
          <tbody>
            {[...data.years].sort((a, b) => b.year - a.year).map(y => (
              <tr key={y.year} className="border-t border-slate-100"><td className="py-1 pr-3">{y.year}{y.suspect_days > 0 ? '*' : ''}</td><td className="py-1 pr-3">{y.days_missing > 0 ? '—' : fmtInt(y.total)}</td><td className="py-1 pr-3">{fmtInt(y.total_to_date)}</td><td className="py-1">{y.days_with_data} of {data.days.length}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function rank(y: SeasonYear): number {
  return y.role === 'current' ? 2 : y.role === 'last' ? 1 : 0
}

function CurvesTooltip({ active, payload, years, days }: { active?: boolean; payload?: { dataKey?: string | number; value?: number | null }[]; years: SeasonYear[]; days: string[] }) {
  if (!active || !payload?.length) return null
  const idx = (payload[0] as { payload?: { d?: number } }).payload?.d
  if (idx == null) return null
  const entries = years
    .map(y => ({ year: y.year, role: y.role, r7: y.r7[idx], fires: y.fires[idx] }))
    .filter(e => e.r7 != null)
    .sort((a, b) => (b.r7 ?? 0) - (a.r7 ?? 0))
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-[11px] shadow-sm">
      <div className="mb-1 font-semibold text-slate-800">{dayLabel(days[idx] ?? '')}</div>
      {entries.map(e => (
        <div key={e.year} className="flex items-center gap-2 tabular-nums">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: COLORS[e.role] }} />
          <span className={e.role === 'reference' ? 'text-slate-500' : 'font-semibold text-slate-800'}>{e.year}</span>
          <span className="ml-auto">{fmtInt(e.r7)}</span>
          <span className="text-slate-400">(day {fmtInt(e.fires)})</span>
        </div>
      ))}
    </div>
  )
}
