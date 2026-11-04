'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import type { DistrictRow, DistrictsResponse } from './api'
import { fmtInt, fmtMw, fmtPct, fmtShare } from './format'
import { trackerFireLink } from './mapLink'

type SortKey = 'fires' | 'fires_last' | 'pct_change' | 'night_share' | 'frp_mw' | 'district'

export function DistrictTable({ data, date }: { data: DistrictsResponse; date: string }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'fires', dir: -1 })
  const [all, setAll] = useState(false)
  const rows = useMemo(() => {
    const r = [...data.rows]
    r.sort((a, b) => {
      const av = a[sort.key], bv = b[sort.key]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return (av < bv ? -1 : av > bv ? 1 : 0) * sort.dir
    })
    return all ? r : r.slice(0, 25)
  }, [data.rows, sort, all])
  if (data.note) return <p className="text-[13px] text-slate-600">{data.note}</p>
  if (!data.rows.length) return <p className="text-[13px] text-slate-600">No fires in these districts in the window.</p>
  const th = (key: SortKey, label: string, cls = '') => (
    <th scope="col" aria-sort={sort.key === key ? (sort.dir === -1 ? 'descending' : 'ascending') : 'none'} className={`py-1.5 pr-3 font-medium ${cls}`}>
      <button type="button" className="hover:text-slate-900" onClick={() => setSort(s => ({ key, dir: s.key === key ? (s.dir === -1 ? 1 : -1) : key === 'district' ? 1 : -1 }))}>
        {label}{sort.key === key ? (sort.dir === -1 ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  )
  return (
    <div>
      <p className="mb-2 text-[12px] text-slate-500">
        {data.window.compared_dates ?? 'Season to date'} this season vs the same dates in {data.last_year}
        {data.totals ? ` · ${fmtInt(data.totals.fires)} fires vs ${fmtInt(data.totals.fires_last)}` : ''}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px] tabular-nums">
          <thead>
            <tr className="text-left text-slate-500">
              {th('district', 'District')}
              <th scope="col" className="py-1.5 pr-3 font-medium max-sm:hidden">Province</th>
              {th('fires', 'This season', 'text-right')}
              {th('fires_last', `Same dates ${data.last_year}`, 'text-right')}
              {th('pct_change', 'Change', 'text-right')}
              {th('night_share', 'Night', 'text-right max-sm:hidden')}
              {th('frp_mw', 'FRP', 'text-right max-sm:hidden')}
              <th scope="col" className="py-1.5 font-medium">Map</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => <Row key={r.district} r={r} date={date} />)}
          </tbody>
        </table>
      </div>
      {data.rows.length > 25 && (
        <button type="button" onClick={() => setAll(v => !v)} className="mt-2 text-[12px] text-slate-600 underline-offset-2 hover:underline">
          {all ? 'Show the top 25' : `Show all ${data.districts_total} districts`}
        </button>
      )}
    </div>
  )
}

function Row({ r, date }: { r: DistrictRow; date: string }) {
  const up = r.pct_change != null && r.pct_change >= 10
  return (
    <tr className="border-t border-slate-100">
      <td className="py-1.5 pr-3 font-medium text-slate-800">{r.district}</td>
      <td className="py-1.5 pr-3 text-slate-500 max-sm:hidden">{r.province}</td>
      <td className="py-1.5 pr-3 text-right">{fmtInt(r.fires)}</td>
      <td className="py-1.5 pr-3 text-right text-slate-600">{fmtInt(r.fires_last)}</td>
      <td className={`py-1.5 pr-3 text-right ${up ? 'text-red-700' : 'text-slate-700'}`}>{fmtPct(r.pct_change)}</td>
      <td className="py-1.5 pr-3 text-right text-slate-600 max-sm:hidden">{fmtShare(r.night_share)}</td>
      <td className="py-1.5 pr-3 text-right text-slate-600 max-sm:hidden">{fmtMw(r.frp_mw)}</td>
      <td className="py-1.5">
        {r.lat != null && r.lon != null && (
          <Link href={trackerFireLink({ date, lat: r.lat, lon: r.lon, zoom: 9 })} className="text-slate-500 underline-offset-2 hover:text-slate-900 hover:underline">open</Link>
        )}
      </td>
    </tr>
  )
}
