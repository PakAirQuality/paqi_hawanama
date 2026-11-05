'use client'

import Link from 'next/link'
import type { PersistentResponse } from './api'
import { fmtInt, fmtMw, fmtShare } from './format'
import { trackerFireLink } from './mapLink'

export function PersistentSources({ data, date }: { data: PersistentResponse; date: string }) {
  if (data.message && !data.rows?.length) return <p className="text-[13px] text-slate-600">{data.message}</p>
  const oneOff = data.one_off_share == null ? null : Math.round(data.one_off_share * 100)
  return (
    <div>
      <p className="text-[13px] text-slate-700">
        In the last {data.window_days} days ({fmtInt(data.fires_in_area)} fires in {data.region.label}), {oneOff != null ? `${oneOff}% of burning cells lit on a single day` : 'most burning cells lit once'};{' '}
        <span className="font-semibold">{fmtInt(data.persistent_cells)}</span> cell{data.persistent_cells === 1 ? '' : 's'} burned on {data.min_days} or more days.
      </p>
      <p className="mt-1 text-[12px] text-slate-500">A flag for investigation, not a verdict: kilns, gas flares, landfills and industry burn like this, but so do many fields in one ~2 km cell lighting on successive days. Persistent cells stay in every count above.</p>
      {data.rows.length > 0 && (
        <ul className="mt-3 divide-y divide-slate-100 text-[12px]">
          {data.rows.slice(0, 12).map(r => (
            <li key={`${r.lat},${r.lon}`} className="flex items-center gap-3 py-1.5">
              <span className="w-28 shrink-0 font-medium text-slate-800">{r.district ?? r.country ?? '—'}</span>
              <span className="tabular-nums text-slate-700">{r.days_active} of {data.window_days} days</span>
              <span className="tabular-nums text-slate-500 max-sm:hidden">{fmtMw(r.frp_mean_mw)} mean</span>
              <span className="tabular-nums text-slate-500">{fmtShare(r.night_share)} night</span>
              <Link href={trackerFireLink({ date, lat: r.lat, lon: r.lon, zoom: 11 })} className="ml-auto text-slate-500 underline-offset-2 hover:text-slate-900 hover:underline">open on map</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
