'use client'

import { useMemo, useEffect } from 'react'
import type { CurrentStation, ForecastEntry } from './types'
import type { FiresGeoJSON } from './api'
import { loadPakBoundary, isInsidePakistan, isPakBoundaryLoaded } from './pakistan'
import { BAND_KEYS, BAND_SCALE_LABEL, bandColor, bandCounts, bandKey, bandLabel, unhealthyOrWorse } from '@/lib/aqi'
import { formatDateOnly, formatPkt, pktToday } from '@/lib/time'
import { firesShortLabel, firesStatus } from '@/lib/fires'

interface ContextPanelProps {
  currentStations: CurrentStation[]
  forecasts: ForecastEntry[]
  firesGeoJSON: FiresGeoJSON | null
  selectedHorizon: number
  /** the day the desk is describing (YYYY-MM-DD, Pakistan); defaults to today PKT */
  selectedDate?: string | null
}

export function ContextPanel({ currentStations, forecasts, firesGeoJSON, selectedDate }: ContextPanelProps) {
  // Load Pakistan boundary on mount
  useEffect(() => { loadPakBoundary() }, [])

  const stats = useMemo(() => {
    if (!isPakBoundaryLoaded()) return null

    const stations = currentStations.filter(s =>
      s.pm25 != null && s.latitude != null && s.longitude != null &&
      isInsidePakistan(s.longitude!, s.latitude!)
    )
    if (!stations.length) return null

    const pm25Values = stations.map(s => s.pm25!)
    const mean = pm25Values.reduce((a, b) => a + b, 0) / pm25Values.length
    const sorted = [...pm25Values].sort((a, b) => b - a)

    // Worst cities
    const cityPm25: Record<string, number[]> = {}
    stations.forEach(s => {
      if (s.city) {
        if (!cityPm25[s.city]) cityPm25[s.city] = []
        cityPm25[s.city].push(s.pm25!)
      }
    })
    const worstCities = Object.entries(cityPm25)
      .map(([city, vals]) => ({ city, avg: vals.reduce((a, b) => a + b, 0) / vals.length, count: vals.length }))
      .sort((a, b) => b.avg - a.avg)
      .slice(0, 5)

    // Ramp events from forecasts
    const ramps = forecasts.filter(f => f.ramp_detected && f.lead_days === 1)

    // Freshness of the observations behind the mean
    const latest = stations
      .map(s => s.last_reading)
      .filter((t): t is string => !!t)
      .sort()
      .at(-1) ?? null

    return {
      stationCount: stations.length,
      mean: Math.round(mean),
      max: Math.round(sorted[0]),
      band: bandKey(mean),
      bands: bandCounts(pm25Values),
      worstCities,
      rampCount: ramps.length,
      latestObservation: latest,
      fireCount: firesGeoJSON?.features?.filter(f => {
        const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates
        return isInsidePakistan(lng, lat)
      }).length || 0,
    }
  }, [currentStations, forecasts, firesGeoJSON])

  const fireLabel = firesShortLabel(firesGeoJSON, stats?.fireCount ?? 0)

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-xs">
        Loading brief...
      </div>
    )
  }

  const dayLabel = formatDateOnly(selectedDate || pktToday(), { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
  const bad = unhealthyOrWorse(stats.bands)

  return (
    <div className="flex flex-col h-full overflow-y-auto" style={{ scrollbarWidth: 'none' }}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">Pakistan Daily Brief</div>
        <div className="text-sm font-semibold text-slate-800 mt-0.5">{dayLabel} <span className="text-[10px] font-normal text-slate-400">PKT</span></div>
      </div>

      {/* Reporting-station mean */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider" title="Unweighted mean of the latest hourly PM2.5 across the stations that reported; not an area or population average">
              Reporting-station mean
            </div>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-3xl font-bold tabular-nums" style={{ color: bandColor(stats.band) }}>
                {stats.mean}
              </span>
              <span className="text-xs text-slate-400">µg/m³ PM2.5</span>
            </div>
            <div className="text-[11px] mt-0.5" style={{ color: bandColor(stats.band) }}>
              {bandLabel(stats.band)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-slate-400">Peak station</div>
            <div className="text-lg font-bold text-slate-700 tabular-nums">{stats.max}</div>
            <div className="text-[10px] text-slate-400">{stats.stationCount} stations reporting</div>
          </div>
        </div>
        <div className="mt-2 text-[9px] text-slate-400">
          Latest hourly readings · {stats.latestObservation ? `last observation ${formatPkt(stats.latestObservation)}` : 'observation time unknown'} · {BAND_SCALE_LABEL}
        </div>
      </div>

      {/* Band distribution */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-2">Stations by category</div>
        <div className="flex h-2 rounded-full overflow-hidden gap-px">
          {BAND_KEYS.map(band => {
            const pct = stats.bands[band] / stats.stationCount * 100
            if (pct === 0) return null
            return (
              <div
                key={band}
                style={{ width: `${pct}%`, backgroundColor: bandColor(band) }}
                title={`${bandLabel(band)}: ${stats.bands[band]} stations (${Math.round(pct)}%)`}
              />
            )
          })}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-2">
          {BAND_KEYS.map(band => {
            if (!stats.bands[band]) return null
            return (
              <div key={band} className="flex items-center gap-1 text-[10px] text-slate-500" title={bandLabel(band)}>
                <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: bandColor(band) }} />
                {stats.bands[band]} {bandLabel(band, true)}
              </div>
            )
          })}
        </div>
      </div>

      {/* Worst cities */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-2">Highest city means</div>
        <div className="space-y-1.5">
          {stats.worstCities.map((c, i) => {
            const band = bandKey(c.avg)
            return (
              <div key={c.city} className="flex items-center gap-2">
                <span className="text-[10px] text-slate-300 font-mono w-3">{i + 1}</span>
                <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: bandColor(band) }} />
                <span className="text-[11px] text-slate-700 flex-1 truncate">{c.city}</span>
                <span className="text-[11px] font-semibold tabular-nums" style={{ color: bandColor(band) }}>
                  {Math.round(c.avg)}
                </span>
                <span className="text-[9px] text-slate-400">({c.count})</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Alerts row */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-2">Evidence</div>
        <div className="grid grid-cols-2 gap-2">
          <div className="px-2.5 py-2 rounded-lg bg-orange-50 border border-orange-100">
            <div className="text-lg font-bold text-orange-600 tabular-nums">{firesStatus(firesGeoJSON) === 'unavailable' ? '—' : stats.fireCount}</div>
            <div className={`text-[10px] ${fireLabel.warn ? 'text-amber-700' : 'text-orange-500'}`}>
              {firesStatus(firesGeoJSON) === 'unavailable' ? 'Fire data unavailable'
                : firesStatus(firesGeoJSON) === 'stale' ? `Fire detections (${firesGeoJSON?.date})`
                : `Satellite fire detections${fireLabel.warn ? ` · ${fireLabel.text.split(' · ').slice(1).join(' · ')}` : ''}`}
            </div>
          </div>
          <div className="px-2.5 py-2 rounded-lg bg-amber-50 border border-amber-100">
            <div className="text-lg font-bold text-amber-600 tabular-nums">{stats.rampCount}</div>
            <div className="text-[10px] text-amber-500">Forecast ramp events</div>
          </div>
        </div>
      </div>

      {/* Unhealthy stations */}
      <div className="px-4 py-3">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-1">
          {bad} station{bad === 1 ? '' : 's'} Unhealthy or worse (AQI above 150)
        </div>
        <div className="text-[10px] text-slate-400 leading-relaxed">
          {(['hazardous', 'very_unhealthy', 'unhealthy'] as const)
            .filter(k => stats.bands[k] > 0)
            .map((k, i) => (
              <span key={k}>
                {i > 0 && ', '}
                <span className="font-medium" style={{ color: bandColor(k) }}>{stats.bands[k]} {bandLabel(k).toLowerCase()}</span>
              </span>
            ))}
          {stats.bands.unhealthy_sensitive > 0 && (
            <span className="text-slate-400">{bad > 0 ? '; ' : ''}{stats.bands.unhealthy_sensitive} unhealthy for sensitive groups</span>
          )}
        </div>
      </div>
    </div>
  )
}
