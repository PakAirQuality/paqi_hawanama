'use client'

import { useMemo } from 'react'
import { Bar, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Pm25LinkResponse } from './api'
import { dayLabel, fmtCompact, fmtInt } from './format'

export function FirePm25Chart({ data }: { data: Pm25LinkResponse }) {
  const rows = useMemo(() => (data.rows ?? []).map((r, i) => ({ ...r, i })), [data.rows])
  const ticks = useMemo(() => rows.filter(r => r.day.endsWith('-01') || r.day.endsWith('-15')).map(r => r.i), [rows])
  if (data.status !== 'ok' || !rows.length) {
    return <p className="text-[13px] text-slate-600">{data.message ?? 'No data for this window.'}</p>
  }
  const corr = data.correlations?.frp_upwind
  return (
    <div>
      <p className="text-[13px] text-slate-700">{data.summary}</p>
      <div className="mt-3 rounded-lg border border-slate-100 bg-white p-2" style={{ width: '100%', height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 44, bottom: 4, left: 0 }}>
            <CartesianGrid horizontal vertical={false} strokeDasharray="4 4" stroke="#e2e8f0" />
            <XAxis dataKey="i" type="number" domain={[0, rows.length - 1]} ticks={ticks.length ? ticks : undefined} tickFormatter={i => dayLabel(rows[Number(i)]?.day ?? '')}
              axisLine={{ stroke: '#e2e8f0' }} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} />
            <YAxis yAxisId="frp" orientation="left" axisLine={false} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} width={40} tickFormatter={v => fmtCompact(Number(v))} />
            <YAxis yAxisId="pm" orientation="right" axisLine={false} tickLine={false} stroke="#9ca3af" tick={{ fontSize: 10 }} width={40} />
            <Tooltip contentStyle={{ backgroundColor: 'white', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11, padding: 6 }}
              labelFormatter={i => { const r = rows[Number(i)]; return r ? `${dayLabel(r.day)}${r.flag ? ' · fire-influenced' : ''}` : '' }}
              formatter={(v, name) => name === 'pm25' ? [`${v} µg/m³`, 'PM2.5 (reporting-station mean)'] : [`${fmtInt(v as number)} MW`, 'Upwind fire FRP']} />
            <Bar yAxisId="frp" dataKey="frp_upwind" isAnimationActive={false} maxBarSize={12} radius={[2, 2, 0, 0]}>
              {rows.map(r => <Cell key={r.day} fill={r.flag ? '#dc2626' : '#cbd5e1'} />)}
            </Bar>
            <Line yAxisId="pm" dataKey="pm25" type="monotone" stroke="#0f172a" strokeWidth={1.75} dot={false} connectNulls={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <span><span className="inline-block h-2.5 w-2.5 rounded-sm bg-[#cbd5e1]" /> upwind FRP (MW, left)</span>
        <span><span className="inline-block h-2.5 w-2.5 rounded-sm bg-[#dc2626]" /> fire-influenced day</span>
        <span><span className="inline-block h-0.5 w-3 bg-[#0f172a] align-middle" /> PM2.5 (µg/m³, right)</span>
      </div>
      {corr && (
        <table className="mt-3 text-[12px] tabular-nums">
          <thead><tr className="text-left text-slate-500"><th className="pr-4 font-medium">Upwind FRP vs PM2.5</th><th className="pr-4 font-medium">same day</th><th className="pr-4 font-medium">next day</th><th className="font-medium">two days later</th></tr></thead>
          <tbody>
            <tr>
              <td className="pr-4 text-slate-600">Spearman (n)</td>
              {(['lag0', 'lag1', 'lag2'] as const).map(l => (
                <td key={l} className="pr-4">{corr[l].spearman == null ? '—' : `${corr[l].spearman} ${corr[l].strength}`} <span className="text-slate-400">({corr[l].n})</span></td>
              ))}
            </tr>
          </tbody>
        </table>
      )}
      <p className="mt-2 text-[11px] text-slate-500">Upwind FRP sums fires within 200 km inside a ±60° cone on that day&apos;s station wind. A day is flagged when that FRP (on the day or the day before) is above the window&apos;s 75th percentile and PM2.5 is at least 20% and 10 µg/m³ above the prior three days. Consistent with smoke transport, never a proof of cause.</p>
    </div>
  )
}
