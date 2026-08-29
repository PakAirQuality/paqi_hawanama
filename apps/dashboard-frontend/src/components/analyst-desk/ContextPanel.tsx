'use client'

import { useMemo, useEffect } from 'react'
import type { CurrentStation, ForecastEntry } from './types'
import type { FiresGeoJSON } from './api'
import { loadPakBoundary, isInsidePakistan, isPakBoundaryLoaded } from './pakistan'

interface ContextPanelProps {
  currentStations: CurrentStation[]
  forecasts: ForecastEntry[]
  firesGeoJSON: FiresGeoJSON | null
  selectedHorizon: number
}

function getBand(pm25: number): string {
  if (pm25 <= 35) return 'good'
  if (pm25 <= 75) return 'moderate'
  if (pm25 <= 150) return 'unhealthy'
  if (pm25 <= 250) return 'very_unhealthy'
  return 'severe'
}

const BAND_COLORS: Record<string, string> = {
  good: '#6ecc39',
  moderate: '#f0c20c',
  unhealthy: '#f18017',
  very_unhealthy: '#a070b5',
  severe: '#991b1b',
}

const BAND_LABELS: Record<string, string> = {
  good: 'Good',
  moderate: 'Moderate',
  unhealthy: 'Unhealthy',
  very_unhealthy: 'Very Unhealthy',
  severe: 'Severe',
}

export function ContextPanel({ currentStations, forecasts, firesGeoJSON, selectedHorizon }: ContextPanelProps) {
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

    // Band distribution
    const bands: Record<string, number> = { good: 0, moderate: 0, unhealthy: 0, very_unhealthy: 0, severe: 0 }
    stations.forEach(s => { bands[getBand(s.pm25!)]++ })

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

    return {
      stationCount: stations.length,
      mean: Math.round(mean),
      max: Math.round(sorted[0]),
      band: getBand(mean),
      bands,
      worstCities,
      rampCount: ramps.length,
      fireCount: firesGeoJSON?.features?.filter((f: any) => {
        const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates
        return isInsidePakistan(lng, lat)
      }).length || 0,
    }
  }, [currentStations, forecasts, firesGeoJSON])

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400 text-xs">
        Loading brief...
      </div>
    )
  }

  const today = new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })

  return (
    <div className="flex flex-col h-full overflow-y-auto" style={{ scrollbarWidth: 'none' }}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">Pakistan Daily Brief</div>
        <div className="text-sm font-semibold text-slate-800 mt-0.5">{today}</div>
      </div>

      {/* National average */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider">Pakistan Average</div>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-3xl font-bold tabular-nums" style={{ color: BAND_COLORS[stats.band] }}>
                {stats.mean}
              </span>
              <span className="text-xs text-slate-400">µg/m³</span>
            </div>
            <div className="text-[11px] mt-0.5" style={{ color: BAND_COLORS[stats.band] }}>
              {BAND_LABELS[stats.band]}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-slate-400">Peak</div>
            <div className="text-lg font-bold text-slate-700 tabular-nums">{stats.max}</div>
            <div className="text-[10px] text-slate-400">{stats.stationCount} stations</div>
          </div>
        </div>
      </div>

      {/* Band distribution */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-2">Air Quality Distribution</div>
        <div className="flex h-2 rounded-full overflow-hidden gap-px">
          {(['good', 'moderate', 'unhealthy', 'very_unhealthy', 'severe'] as const).map(band => {
            const pct = stats.bands[band] / stats.stationCount * 100
            if (pct === 0) return null
            return (
              <div
                key={band}
                style={{ width: `${pct}%`, backgroundColor: BAND_COLORS[band] }}
                title={`${BAND_LABELS[band]}: ${stats.bands[band]} stations (${Math.round(pct)}%)`}
              />
            )
          })}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-2">
          {(['good', 'moderate', 'unhealthy', 'very_unhealthy', 'severe'] as const).map(band => {
            if (!stats.bands[band]) return null
            return (
              <div key={band} className="flex items-center gap-1 text-[10px] text-slate-500">
                <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: BAND_COLORS[band] }} />
                {stats.bands[band]}
              </div>
            )
          })}
        </div>
      </div>

      {/* Worst cities */}
      <div className="px-4 py-3 border-b border-slate-100">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-2">Most Polluted Cities</div>
        <div className="space-y-1.5">
          {stats.worstCities.map((c, i) => {
            const band = getBand(c.avg)
            return (
              <div key={c.city} className="flex items-center gap-2">
                <span className="text-[10px] text-slate-300 font-mono w-3">{i + 1}</span>
                <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: BAND_COLORS[band] }} />
                <span className="text-[11px] text-slate-700 flex-1 truncate">{c.city}</span>
                <span className="text-[11px] font-semibold tabular-nums" style={{ color: BAND_COLORS[band] }}>
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
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-2">Alerts</div>
        <div className="grid grid-cols-2 gap-2">
          <div className="px-2.5 py-2 rounded-lg bg-orange-50 border border-orange-100">
            <div className="text-lg font-bold text-orange-600 tabular-nums">{stats.fireCount}</div>
            <div className="text-[10px] text-orange-500">Active fires</div>
          </div>
          <div className="px-2.5 py-2 rounded-lg bg-amber-50 border border-amber-100">
            <div className="text-lg font-bold text-amber-600 tabular-nums">{stats.rampCount}</div>
            <div className="text-[10px] text-amber-500">Ramp events</div>
          </div>
        </div>
      </div>

      {/* Unhealthy stations */}
      <div className="px-4 py-3">
        <div className="text-[10px] text-slate-400 font-medium uppercase tracking-wider mb-1">
          {stats.bands.unhealthy + stats.bands.very_unhealthy + stats.bands.severe} stations above unhealthy threshold
        </div>
        <div className="text-[10px] text-slate-400 leading-relaxed">
          {stats.bands.severe > 0 && <span className="text-red-600 font-medium">{stats.bands.severe} severe</span>}
          {stats.bands.severe > 0 && stats.bands.very_unhealthy > 0 && ', '}
          {stats.bands.very_unhealthy > 0 && <span className="text-purple-600 font-medium">{stats.bands.very_unhealthy} very unhealthy</span>}
          {(stats.bands.severe > 0 || stats.bands.very_unhealthy > 0) && stats.bands.unhealthy > 0 && ', '}
          {stats.bands.unhealthy > 0 && <span className="text-orange-600 font-medium">{stats.bands.unhealthy} unhealthy</span>}
        </div>
      </div>
    </div>
  )
}
