'use client'

import Link from 'next/link'
import type { CityOutlookResponse } from './api'
import { fmtMw } from './format'
import { trackerFireLink } from './mapLink'
import { BAND_CLASS, BAND_LABEL, leadSentence, leadTitle } from './outlookText'

export function SmokeOutlook({ data, today }: { data: CityOutlookResponse; today: string }) {
  if (data.status === 'unavailable' || !data.leads) return <p className="text-[13px] text-slate-600">{data.message ?? 'No smoke outlook yet.'}</p>
  const generated = data.generated_at ? data.generated_at.slice(0, 16).replace('T', ' ') + 'Z' : '—'
  return (
    <div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {data.leads.map(l => (
          <div key={l.lead} className="rounded-xl bg-slate-50 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] uppercase tracking-wide text-slate-500">{leadTitle(l, today)}</span>
              {l.band && <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${BAND_CLASS[l.band]}`}>{BAND_LABEL[l.band]}</span>}
            </div>
            <div className="mt-1 text-[15px] font-semibold tabular-nums text-slate-900">{l.upwind_load_mw == null ? '—' : fmtMw(l.upwind_load_mw)}</div>
            <div className="text-[12px] text-slate-600">{leadSentence(l)}</div>
            {l.top_fires && l.top_fires.length > 0 && (
              <ul className="mt-1.5 space-y-0.5 text-[11px] text-slate-500">
                {l.top_fires.slice(0, 3).map((f, i) => (
                  <li key={i} className="flex items-center gap-1.5 tabular-nums">
                    <span className="truncate">{f.district ?? f.country}</span>
                    <span>{f.km} km {f.direction}</span>
                    <span>{fmtMw(f.frp_mw)}</span>
                    <Link href={trackerFireLink({ date: l.day <= today ? l.day : today, lat: f.lat, lon: f.lon, zoom: 11 })} className="ml-auto underline-offset-2 hover:text-slate-900 hover:underline">map</Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      {data.others_at_alert_d1 && data.others_at_alert_d1.length > 0 && (
        <p className="mt-2 text-[12px] text-slate-600">
          Also high tomorrow: {data.others_at_alert_d1.slice(0, 8).map(o => `${o.city} (${fmtMw(o.upwind_load_mw)} from ${o.from_compass ?? '—'})`).join(', ')}.
        </p>
      )}
      <p className="mt-2 text-[11px] text-slate-500">
        ECMWF wind at 850 hPa (transport) × the fires seen on {data.fires_as_of?.days?.join(' and ') ?? 'the last two days'}, assumed to keep burning; a smoke-source outlook, not a PM2.5 forecast. Bands: elevated above 300 MW, high above 1,000, very high above 3,000; unvalidated screening categories, not an air-quality claim. Generated {generated}{data.status === 'stale' ? ' (older than 6 h)' : ''}.
      </p>
    </div>
  )
}
