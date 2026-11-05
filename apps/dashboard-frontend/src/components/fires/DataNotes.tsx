'use client'

import type { Basis, FiresMeta, SeasonId } from './api'
import { dateLabel } from './format'

const SAT = { n20: 'NOAA-20', n21: 'NOAA-21', snpp: 'Suomi NPP' } as const

export function DataNotes({ meta, season, basis }: { meta?: FiresMeta; season: SeasonId; basis: Basis }) {
  if (!meta) return null
  const gaps = meta.archive.gaps?.[season] ?? {}
  const gapText = Object.entries(gaps).map(([y, runs]) => `${y}: ${runs.map(([a, b]) => a === b ? dateLabel(a) : `${dateLabel(a)} – ${dateLabel(b)}`).join(', ')}`)
  const roster = Object.entries(meta.satellites_by_year).map(([y, s]) => `${y}: ${s.join(' + ')}`)
  const noPass = Object.entries(meta.archive.days_without_pass_by_year ?? {})
    .map(([y, by]) => `${y}: ${Object.entries(by).map(([k, n]) => `${n} without ${SAT[k as keyof typeof SAT] ?? k}`).join(', ')}`)
  return (
    <section aria-labelledby="fires-notes" className="rounded-2xl border border-slate-200/70 bg-white p-4 sm:p-5">
      <h2 id="fires-notes" className="text-[13px] font-semibold text-slate-800">About these numbers</h2>
      <ul className="mt-2 space-y-1.5 text-[12px] leading-relaxed text-slate-600">
        <li><span className="font-medium text-slate-700">Counting basis on this page:</span> {meta.bases?.[basis] ?? (basis === 'n20' ? 'NOAA-20 only' : 'all satellites')}.</li>
        {meta.notes.map((n, i) => <li key={i}>{n}</li>)}
        {season === 'rice' && meta.season_window_note && <li>{meta.season_window_note}</li>}
        {meta.classification?.available && (
          <li><span className="font-medium text-slate-700">Source classes (class {meta.classification.class_version}):</span> likely crop-residue = {meta.classification.rules.crop}; likely other = {meta.classification.rules.other}; uncertain = {meta.classification.rules.uncertain}. Cropland is ESA WorldCover 2021 (CC BY 4.0); kilns and industrial sites come from the APAD/Zenodo kiln inventory, OpenStreetMap and the emission-source list. {meta.classification.rules.status}.</li>
        )}
        <li><span className="font-medium text-slate-700">Satellites counted:</span> {roster.join(' · ')}.</li>
        {noPass.length > 0 && <li><span className="font-medium text-slate-700">Days with a file but no rows from one satellite (a missing pass, shown as a gap on that basis):</span> {noPass.join(' · ')}.</li>}
        {gapText.length > 0 && <li><span className="font-medium text-slate-700">Days without a file in this season:</span> {gapText.join(' · ')}.</li>}
        {Object.keys(meta.archive.suspect_days_by_year ?? {}).length > 0 && (
          <li><span className="font-medium text-slate-700">Thin archive days (far fewer rows than the 2020–2023 median):</span> {Object.entries(meta.archive.suspect_days_by_year).map(([y, n]) => `${y}: ${n}`).join(', ')}; those years are dashed and starred.</li>
        )}
        {meta.archive.pkt_from && <li>Days are keyed by Pakistan calendar day with pass times from {dateLabel(meta.archive.pkt_from)}; earlier archive days are keyed by UTC date without pass times, so the night pass may belong to the neighbouring day.</li>}
        <li>Wind for the upwind cone comes from, in order: ERA5 reanalysis when it covers the day, the forecast pipeline&apos;s prevailing wind, then monitoring-station observations; each card names the source it used. The cone is a screen on one wind direction a day, not a trajectory.</li>
        <li>Source: NASA FIRMS VIIRS (NOAA-20, NOAA-21, Suomi NPP), archived daily since {meta.archive.first_day ? dateLabel(meta.archive.first_day) : '2020'}; store built {meta.store_built_at ? meta.store_built_at.slice(0, 16).replace('T', ' ') + 'Z' : '—'}{meta.store_schema_version ? ` (schema ${meta.store_schema_version})` : ''}.</li>
      </ul>
    </section>
  )
}
