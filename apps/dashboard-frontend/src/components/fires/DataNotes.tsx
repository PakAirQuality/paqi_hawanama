'use client'

import type { FiresMeta, SeasonId } from './api'
import { dateLabel } from './format'

export function DataNotes({ meta, season }: { meta?: FiresMeta; season: SeasonId }) {
  if (!meta) return null
  const gaps = meta.archive.gaps?.[season] ?? {}
  const gapText = Object.entries(gaps).map(([y, runs]) => `${y}: ${runs.map(([a, b]) => a === b ? dateLabel(a) : `${dateLabel(a)} – ${dateLabel(b)}`).join(', ')}`)
  const roster = Object.entries(meta.satellites_by_year).map(([y, s]) => `${y}: ${s.join(' + ')}`)
  return (
    <section aria-labelledby="fires-notes" className="rounded-2xl border border-slate-200/70 bg-white p-4 sm:p-5">
      <h2 id="fires-notes" className="text-[13px] font-semibold text-slate-800">About these numbers</h2>
      <ul className="mt-2 space-y-1.5 text-[12px] leading-relaxed text-slate-600">
        {meta.notes.map((n, i) => <li key={i}>{n}</li>)}
        <li><span className="font-medium text-slate-700">Satellites counted:</span> {roster.join(' · ')}.</li>
        {gapText.length > 0 && <li><span className="font-medium text-slate-700">Days without a file in this season:</span> {gapText.join(' · ')}.</li>}
        {Object.keys(meta.archive.suspect_days_by_year ?? {}).length > 0 && (
          <li><span className="font-medium text-slate-700">Thin archive days (far fewer rows than the 2020–2023 median):</span> {Object.entries(meta.archive.suspect_days_by_year).map(([y, n]) => `${y}: ${n}`).join(', ')}; those years are dashed and starred.</li>
        )}
        <li>Wind for the upwind cone comes from, in order: ERA5 reanalysis when it covers the day, the forecast pipeline&apos;s prevailing wind, then monitoring-station observations; each card names the source it used.</li>
        <li>Source: NASA FIRMS VIIRS (NOAA-20, NOAA-21, Suomi NPP), archived daily since {meta.archive.first_day ? dateLabel(meta.archive.first_day) : '2020'}; store built {meta.store_built_at ? meta.store_built_at.slice(0, 16).replace('T', ' ') + 'Z' : '—'}.</li>
      </ul>
    </section>
  )
}
