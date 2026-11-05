'use client'

import type { SeasonsResponse } from './api'
import { fmtInt, fmtMw, fmtShare } from './format'
import { headlineParts } from './headlineText'

export function Headline({ data, regionLabel }: { data: SeasonsResponse; regionLabel: string }) {
  const p = headlineParts(data, regionLabel)
  const h = data.headline
  const tail: string[] = []
  if (p.vsLast) tail.push(p.vsLast)
  if (p.vsRef) tail.push(p.vsRef)
  const n20 = h.comparison_n20
  return (
    <div>
      <h1 className="text-[20px] font-semibold leading-snug tracking-tight text-slate-900 sm:text-[22px]">
        {p.lead} {regionLabel} has seen <span className="tabular-nums">{p.count}</span> {p.unit}
        {tail.length ? `, ${tail.join(' and ')}` : ''}
        {tail.length && p.basisNote ? <span className="text-slate-500"> ({p.basisNote})</span> : null}
        {p.rank ? <span className="text-slate-500"> ({p.rank})</span> : null}.
      </h1>
      <p className="mt-1.5 text-[13px] text-slate-600">{p.subline}</p>
      {data.note && <p className="mt-1 text-[12px] text-slate-500">{data.note}</p>}
      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Stat label="Detections season to date" value={fmtInt(h.fires)} hint={data.basis === 'n20' ? 'NOAA-20 only' : 'all satellites, deduplicated'} />
        <Stat label="Detections a day" value={h.fires_per_day == null ? '—' : fmtInt(h.fires_per_day)} />
        {n20 ? (
          <Stat label="NOAA-20 only" value={fmtInt(n20.fires)} hint={n20.last_year ? `${fmtInt(n20.last_year.fires)} on the same dates in ${n20.last_year.year}` : 'the comparable series'} />
        ) : (
          <Stat label="Night share" value={fmtShare(h.night_share)} hint="detections on the ~01:00 PKT pass" />
        )}
        <Stat label="Fire radiative power" value={fmtMw(h.frp_mw)} />
        <Stat label="Days observed" value={`${h.window.days_with_data} of ${h.window.days}`} hint={h.window.days_missing ? `${h.window.days_missing} missing` : undefined} />
      </dl>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-[17px] font-semibold tabular-nums text-slate-900">{value}</dd>
      {hint && <dd className="text-[11px] text-slate-500">{hint}</dd>}
    </div>
  )
}
