'use client'

import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { SplitKey, SplitResponse } from './api'
import { dayLabel, fmtCompact, fmtInt, fmtShare } from './format'
import { axisTicks } from './seasonAlign'

const ORDER: SplitKey[] = ['pakistan', 'indian_punjab', 'haryana', 'other']
const COLORS: Record<SplitKey, string> = { pakistan: '#0f172a', indian_punjab: '#2563eb', haryana: '#60a5fa', other: '#cbd5e1' }

export function BorderSplit({ data }: { data: SplitResponse }) {
  const rows = useMemo(() => data.days.map((mmdd, i) => {
    const row: Record<string, number | string | null> = { d: i, label: dayLabel(mmdd) }
    for (const k of ORDER) row[k] = data.series[k][i]
    return row
  }), [data])
  const ticks = useMemo(() => axisTicks(data.days), [data.days])
  const grand = ORDER.reduce((s, k) => s + (data.totals[k] ?? 0), 0)
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-slate-600">
        {ORDER.map(k => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: COLORS[k] }} />
            {shortLabel(k)} <span className="tabular-nums font-medium text-slate-800">{fmtInt(data.totals[k])}</span>
            <span className="text-slate-400">{fmtShare(data.shares[k])}</span>
          </span>
        ))}
      </div>
      <div className="rounded-lg border border-slate-100 bg-white p-2" style={{ width: '100%', height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 44, bottom: 4, left: 0 }} barCategoryGap={1}>
            <CartesianGrid horizontal vertical={false} strokeDasharray="4 4" stroke="#e2e8f0" />
            <XAxis dataKey="d" type="number" domain={[0, data.days.length - 1]} ticks={ticks} tickFormatter={i => dayLabel(data.days[i] ?? '')}
              axisLine={{ stroke: '#e2e8f0' }} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} />
            <YAxis orientation="right" axisLine={false} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} width={40} tickFormatter={v => fmtCompact(Number(v))} />
            <Tooltip cursor={{ fill: 'rgba(15,23,42,0.04)' }} contentStyle={{ backgroundColor: 'white', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11, padding: 6 }}
              labelFormatter={i => dayLabel(data.days[Number(i)] ?? '')} formatter={(v, name) => [fmtInt(v as number), shortLabel(name as SplitKey)]} />
            {ORDER.map(k => (
              <Bar key={k} dataKey={k} stackId="a" fill={COLORS[k]} isAnimationActive={false} maxBarSize={10} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      {data.classes && (
        <p className="mt-1.5 text-[11px] text-slate-500">
          Source classes (class {data.class_version ?? '—'}, unvalidated): {(['pakistan_punjab', 'indian_punjab', 'haryana'] as const).filter(k => data.classes?.[k]).map(k => {
            const c = data.classes![k]
            const tot = c.crop + c.other + c.uncertain
            return `${data.labels[k]} ${tot ? Math.round((c.crop / tot) * 100) : 0}% likely crop-residue, ${tot ? Math.round((c.other / tot) * 100) : 0}% likely other`
          }).join(' · ')}.
        </p>
      )}
      <p className="mt-1.5 text-[11px] text-slate-500">
        {fmtInt(grand)} detection clusters in the box season to date{data.totals.pakistan_punjab != null ? ` (Pakistan Punjab ${fmtInt(data.totals.pakistan_punjab)} of Pakistan's ${fmtInt(data.totals.pakistan)})` : ''}{data.days_missing ? `; ${data.days_missing} day(s) unobserved` : ''}. Other = Rajasthan, J&K, Himachal, Afghanistan, Iran.{data.basis === 'n20' ? ' NOAA-20 only.' : ''}
      </p>
    </div>
  )
}

function shortLabel(k: SplitKey): string {
  return { pakistan: 'Pakistan', indian_punjab: 'Indian Punjab', haryana: 'Haryana', other: 'Other' }[k]
}
