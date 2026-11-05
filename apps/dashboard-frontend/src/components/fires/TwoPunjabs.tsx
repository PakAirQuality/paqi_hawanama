'use client'

import { useMemo, useState } from 'react'
import { Bar, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { FIRES_API, isCropBasis, isN20Basis, type Basis, type SeasonId, type SeasonsResponse } from './api'
import { dayLabel, fmtCompact, fmtInt } from './format'
import { Pill, PillGroup } from './Pill'
import { axisTicks } from './seasonAlign'

const PANELS = [
  { key: 'punjab', label: 'Pakistan Punjab', color: '#0f172a' },
  { key: 'indian-punjab', label: 'Indian Punjab', color: '#2563eb' },
  { key: 'haryana', label: 'Haryana', color: '#60a5fa' },
] as const

type PanelKey = (typeof PANELS)[number]['key']
type Mode = 'daily' | 'cum'

/**
 * The two-Punjab product: Pakistan Punjab and Indian Punjab side by side (daily detections and the 7-day
 * mean, this season over last), then the cumulative curves of both Punjabs and Haryana. All three read
 * /seasons on the page's basis; the CSV link streams the same series with the basis in its header.
 */
export function TwoPunjabs({ data, season, basis }: { data: Partial<Record<PanelKey, SeasonsResponse>>; season: SeasonId; basis: Basis }) {
  const [mode, setMode] = useState<Mode>('daily')
  const first = data.punjab ?? data['indian-punjab'] ?? data.haryana
  if (!first) return null
  const days = first.days
  const ticks = axisTicks(days)
  const year = first.season.year
  const basisText = `${isCropBasis(basis) ? 'likely crop-residue detections' : 'deduplicated detection clusters'} · ${isN20Basis(basis) ? 'NOAA-20 only' : 'all satellites'}`
  const csv = `${FIRES_API}/export?season=${season}&basis=${basis}&format=csv`
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <PillGroup label="View">
            <Pill active={mode === 'daily'} onClick={() => setMode('daily')} title="Daily detections with the 7-day mean, this season over last">Daily</Pill>
            <Pill active={mode === 'cum'} onClick={() => setMode('cum')} title="Running total since the start of the season, every adequately observed year">Cumulative</Pill>
          </PillGroup>
          <p className="text-[12px] text-slate-600">{basisText} · {dayLabel(first.season.start)} – {dayLabel(first.season.end)}</p>
        </div>
        <a href={csv} className="text-[12px] text-slate-600 underline-offset-2 hover:underline" download>Download this season as CSV</a>
      </div>
      {mode === 'daily' ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {PANELS.slice(0, 2).map(p => data[p.key] && <DailyPanel key={p.key} label={p.label} color={p.color} data={data[p.key]!} ticks={ticks} />)}
        </div>
      ) : (
        <CumulativePanel data={data} ticks={ticks} year={year} />
      )}
      <Totals data={data} />
      <p className="mt-2 text-[11px] text-slate-500">
        A cumulative shortfall part-way through the season can still be a late season rather than a smaller one; only the completed season settles it. Year-on-year
        percentages in the headline above hold the satellite fixed (NOAA-20); the curves here are on the page&apos;s basis. Gap days add nothing and break the line.
      </p>
    </div>
  )
}

function DailyPanel({ label, color, data, ticks }: { label: string; color: string; data: SeasonsResponse; ticks: number[] }) {
  const cur = data.years.find(y => y.role === 'current')
  const last = data.years.find(y => y.role === 'last')
  const rows = useMemo(() => data.days.map((mmdd, i) => ({ d: i, label: dayLabel(mmdd), cur: cur?.fires[i] ?? null, curR7: cur?.r7[i] ?? null, lastR7: last?.r7[i] ?? null })), [data.days, cur, last])
  const yMax = useMemo(() => {
    let m = 0
    for (const r of rows) for (const v of [r.cur, r.curR7, r.lastR7]) if (v != null && v > m) m = v
    return m || 10
  }, [rows])
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <p className="text-[13px] font-semibold text-slate-800">{label}</p>
        <p className="text-[11px] text-slate-500"><span style={{ color }}>■</span> {data.season.year} daily · <span style={{ color }}>—</span> {data.season.year} 7-day · <span className="text-slate-400">—</span> {data.season.year - 1} 7-day</p>
      </div>
      <div className="rounded-lg border border-slate-100 bg-white p-2" style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 0 }} barCategoryGap={1}>
            <CartesianGrid horizontal vertical={false} strokeDasharray="4 4" stroke="#e2e8f0" />
            <XAxis dataKey="d" type="number" domain={[0, data.days.length - 1]} ticks={ticks} tickFormatter={i => dayLabel(data.days[i] ?? '')} axisLine={{ stroke: '#e2e8f0' }} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} />
            <YAxis domain={[0, yMax]} axisLine={false} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} width={40} tickFormatter={v => fmtCompact(Number(v))} />
            <Tooltip contentStyle={{ backgroundColor: 'white', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11, padding: 6 }} labelFormatter={i => dayLabel(data.days[Number(i)] ?? '')}
              formatter={(v, name) => [fmtInt(v as number), name === 'cur' ? `${data.season.year} daily` : name === 'curR7' ? `${data.season.year} 7-day mean` : `${data.season.year - 1} 7-day mean`]} />
            <Bar dataKey="cur" fill={color} fillOpacity={0.25} isAnimationActive={false} maxBarSize={8} />
            <Line dataKey="lastR7" type="monotone" stroke="#cbd5e1" strokeWidth={1.75} dot={false} connectNulls={false} isAnimationActive={false} />
            <Line dataKey="curR7" type="monotone" stroke={color} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function CumulativePanel({ data, ticks, year }: { data: Partial<Record<PanelKey, SeasonsResponse>>; ticks: number[]; year: number }) {
  const first = (data.punjab ?? data['indian-punjab'] ?? data.haryana)!
  const series = useMemo(() => {
    const out: { key: string; label: string; color: string; width: number; dash?: string; values: (number | null)[] }[] = []
    for (const p of PANELS) {
      const d = data[p.key]
      if (!d) continue
      for (const y of d.years) {
        if (!y.cum || (y.role === 'reference' && (y.days_missing > 0.2 * d.days.length))) continue
        out.push({ key: `${p.key}-${y.year}`, label: `${p.label} ${y.year}`, color: y.role === 'reference' ? '#e2e8f0' : p.color, width: y.role === 'current' ? 2.25 : y.role === 'last' ? 1.5 : 1,
          dash: y.role === 'last' ? '5 3' : undefined, values: y.cum })
      }
    }
    return out
  }, [data])
  const rows = useMemo(() => first.days.map((mmdd, i) => { const r: Record<string, number | string | null> = { d: i, label: dayLabel(mmdd) }; for (const s of series) r[s.key] = s.values[i] ?? null; return r }), [first.days, series])
  return (
    <div>
      <p className="mb-1 text-[11px] text-slate-500">Solid = {year} · dashed = {year - 1} · pale = earlier adequately observed seasons · Pakistan Punjab black, Indian Punjab blue, Haryana light blue</p>
      <div className="rounded-lg border border-slate-100 bg-white p-2" style={{ width: '100%', height: 300 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid horizontal vertical={false} strokeDasharray="4 4" stroke="#e2e8f0" />
            <XAxis dataKey="d" type="number" domain={[0, first.days.length - 1]} ticks={ticks} tickFormatter={i => dayLabel(first.days[i] ?? '')} axisLine={{ stroke: '#e2e8f0' }} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} />
            <YAxis axisLine={false} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} width={44} tickFormatter={v => fmtCompact(Number(v))} />
            <Tooltip contentStyle={{ backgroundColor: 'white', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11, padding: 6 }} labelFormatter={i => dayLabel(first.days[Number(i)] ?? '')}
              formatter={(v, name) => [fmtInt(v as number), series.find(s => s.key === name)?.label ?? String(name)]} itemSorter={(a: { value?: unknown }) => -Number(a.value ?? 0)} />
            {series.map(s => <Line key={s.key} dataKey={s.key} type="monotone" stroke={s.color} strokeWidth={s.width} strokeDasharray={s.dash} dot={false} connectNulls={false} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Totals({ data }: { data: Partial<Record<PanelKey, SeasonsResponse>> }) {
  const cols = PANELS.filter(p => data[p.key])
  if (!cols.length) return null
  const both = (data.punjab && data['indian-punjab']) ? { cur: (data.punjab.headline.fires ?? 0) + (data['indian-punjab'].headline.fires ?? 0) } : null
  return (
    <table className="mt-3 w-full text-[12px] tabular-nums">
      <thead>
        <tr className="text-left text-slate-500">
          <th className="py-1 pr-3 font-medium">Season to date</th>
          {cols.map(p => <th key={p.key} className="py-1 pr-3 font-medium">{p.label}</th>)}
          {both && <th className="py-1 pr-3 font-medium">Both Punjabs</th>}
        </tr>
      </thead>
      <tbody>
        <tr className="border-t border-slate-100">
          <td className="py-1 pr-3 text-slate-600">Detections, this basis</td>
          {cols.map(p => <td key={p.key} className="py-1 pr-3">{fmtInt(data[p.key]!.headline.fires)}</td>)}
          {both && <td className="py-1 pr-3">{fmtInt(both.cur)}</td>}
        </tr>
        <tr className="border-t border-slate-100">
          <td className="py-1 pr-3 text-slate-600">Same dates last year, NOAA-20 only</td>
          {cols.map(p => { const c = data[p.key]!.headline.comparison_n20 ?? data[p.key]!.headline; return <td key={p.key} className="py-1 pr-3">{c.last_year ? `${fmtInt(c.last_year.fires)} (${c.last_year.pct_change == null ? '—' : `${c.last_year.pct_change > 0 ? '+' : ''}${c.last_year.pct_change}%`})` : '—'}</td> })}
          {both && <td className="py-1 pr-3 text-slate-400">—</td>}
        </tr>
        <tr className="border-t border-slate-100">
          <td className="py-1 pr-3 text-slate-600">Days observed</td>
          {cols.map(p => <td key={p.key} className="py-1 pr-3">{data[p.key]!.headline.window.days_with_data} of {data[p.key]!.headline.window.days}</td>)}
          {both && <td className="py-1 pr-3 text-slate-400">—</td>}
        </tr>
      </tbody>
    </table>
  )
}
