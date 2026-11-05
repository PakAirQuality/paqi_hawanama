'use client'

import Link from 'next/link'
import type { City, ExposureResponse } from './api'
import { fmtInt, fmtMw } from './format'
import { trackerFireLink } from './mapLink'

interface Props {
  cities: City[]
  city: string
  date: string
  maxDate: string
  onCity: (c: string) => void
  onDate: (d: string) => void
  data?: ExposureResponse
}

const WIND_SOURCE: Record<string, string> = {
  era5: 'ERA5 reanalysis, 10 m wind at the city centroid',
  pipeline_summary: 'forecast pipeline, prevailing 10 m wind',
  station_vector_mean: 'monitoring stations, speed-weighted mean',
  none: 'no wind source for this day',
}

export function CityExposure({ cities, city, date, maxDate, onCity, onDate, data }: Props) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="text-[12px] text-slate-600">
          <span className="sr-only">City</span>
          <select value={city} onChange={e => onCity(e.target.value)} aria-label="City" className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-800">
            {cities.map(c => <option key={c.id} value={c.name}>{c.name}{c.province ? ` (${c.province})` : ''}</option>)}
          </select>
        </label>
        <label className="text-[12px] text-slate-600">
          <span className="sr-only">Day</span>
          <input type="date" value={date} min="2020-01-01" max={maxDate} onChange={e => e.target.value && onDate(e.target.value)} aria-label="Pakistan day"
            className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-800" />
        </label>
      </div>
      {!data ? null : data.status !== 'ok' || !data.rings ? (
        <p className="text-[13px] text-slate-600">{data.message ?? 'No fire data for this day.'}</p>
      ) : (
        <Body data={data} date={date} />
      )}
    </div>
  )
}

function Body({ data, date }: { data: ExposureResponse; date: string }) {
  const rings = data.rings!
  const countries = Array.from(new Set(Object.values(rings).flatMap(r => Object.keys(r.by_country))))
  const order = ['Pakistan', 'India (Punjab+Haryana)', 'other in bbox']
  countries.sort((a, b) => order.indexOf(a) - order.indexOf(b))
  const wind = data.wind
  const up = data.upwind
  return (
    <div className="space-y-3">
      <table className="w-full text-[12px] tabular-nums">
        <thead>
          <tr className="text-left text-slate-500"><th className="py-1 pr-3 font-medium">Within</th><th className="py-1 pr-3 text-right font-medium">Fires</th>
            {countries.map(c => <th key={c} className="py-1 pr-3 text-right font-medium">{shortCountry(c)}</th>)}<th className="py-1 text-right font-medium">FRP</th></tr>
        </thead>
        <tbody>
          {['50km', '100km', '200km'].filter(k => rings[k]).map(k => (
            <tr key={k} className="border-t border-slate-100">
              <td className="py-1 pr-3 text-slate-700">{k.replace('km', ' km')}</td>
              <td className="py-1 pr-3 text-right font-medium text-slate-800">{fmtInt(rings[k].fires)}</td>
              {countries.map(c => <td key={c} className="py-1 pr-3 text-right text-slate-600">{fmtInt(rings[k].by_country[c] ?? 0)}</td>)}
              <td className="py-1 text-right text-slate-600">{fmtMw(rings[k].frp_mw)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-slate-50 px-3 py-2 text-[12px]">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">Wind at {data.city}</div>
          {wind && wind.from_deg != null ? (
            <div className="mt-0.5 text-[15px] font-semibold text-slate-900">from the {wind.from_compass} ({Math.round(wind.from_deg)}°), {wind.speed_ms ?? '—'} m/s</div>
          ) : <div className="mt-0.5 text-[15px] font-semibold text-slate-900">no wind direction</div>}
          <div className="text-slate-500">{wind ? WIND_SOURCE[wind.source] ?? wind.source : '—'}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-3 py-2 text-[12px]">
          <div className="text-[11px] uppercase tracking-wide text-slate-500">Upwind cone, ±60°, 200 km</div>
          {up ? (
            <>
              <div className="mt-0.5 text-[15px] font-semibold text-slate-900">{fmtInt(up.fires_200km)} detections · {fmtMw(up.frp_mw_200km)}</div>
              <div className="text-slate-500">{Object.entries(up.by_country).map(([c, n]) => `${shortCountry(c)} ${fmtInt(n)}`).join(' · ') || 'none'}; {fmtInt(up.fires_100km)} within 100 km</div>
            </>
          ) : <div className="mt-0.5 text-slate-600">Not available without a wind direction.</div>}
        </div>
      </div>
      {data.top_upwind_fires && data.top_upwind_fires.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Strongest upwind detections</div>
          <ul className="divide-y divide-slate-100 text-[12px]">
            {data.top_upwind_fires.slice(0, 6).map((f, i) => (
              <li key={i} className="flex items-center gap-3 py-1.5 tabular-nums">
                <span className="w-24 shrink-0 whitespace-nowrap text-slate-700">{f.km} km {f.direction}</span>
                <span className="min-w-0 flex-1 truncate text-slate-800">{f.district ?? f.province ?? shortCountry(f.country)}{f.country !== 'Pakistan' ? ` (${shortCountry(f.country)})` : ''}</span>
                <span className="text-slate-500">{fmtMw(f.frp_mw)}</span>
                <span className="text-slate-500 max-sm:hidden">{f.transport_h_at_10m_wind != null ? `~${f.transport_h_at_10m_wind} h` : ''}</span>
                <Link href={trackerFireLink({ date, lat: f.lat, lon: f.lon, zoom: 11 })} className="text-slate-500 underline-offset-2 hover:text-slate-900 hover:underline">map</Link>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[11px] text-slate-500">Transport hours = distance over the 10 m wind speed; smoke moves faster aloft, so treat them as an upper bound.</p>
        </div>
      )}
      {data.nearest_fire && (
        <p className="text-[12px] text-slate-600">Nearest fire: {data.nearest_fire.km} km to the {data.nearest_fire.direction} ({data.nearest_fire.district ?? shortCountry(data.nearest_fire.country)}), {fmtMw(data.nearest_fire.frp_mw)}{data.nearest_fire.acq_pkt ? `, ${data.nearest_fire.acq_pkt}` : ''}.</p>
      )}
      {data.passes?.observation_period && (
        <p className="text-[11px] text-slate-500">Passes {data.passes.satellites?.map(s => s.replace('VIIRS_', '').replace('_NRT', '')).join(', ')} between {data.passes.observation_period.start.slice(11, 16)}Z and {data.passes.observation_period.end.slice(11, 16)}Z{data.caveats?.length ? ` · ${data.caveats.join(' ')}` : ''}</p>
      )}
    </div>
  )
}

function shortCountry(c: string): string {
  return { 'Pakistan': 'Pakistan', 'India (Punjab+Haryana)': 'India', 'other in bbox': 'Other' }[c] ?? c
}
