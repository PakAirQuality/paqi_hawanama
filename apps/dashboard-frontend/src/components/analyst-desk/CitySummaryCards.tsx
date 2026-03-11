"use client"

import { Card, CardContent } from '@/components/ui/card'
import type { SummaryResponse, CitySummary, HorizonStats } from './types'
import {
  BAND_COLORS,
  BAND_BG_COLORS,
  BAND_LABELS,
  CONFIDENCE_STYLES,
  TREND_ICONS,
  TREND_STYLES,
  formatPM25,
  formatPercent,
} from './utils'

interface CitySummaryCardsProps {
  summary: SummaryResponse | undefined
  loading: boolean
  showProvince?: boolean
}

export function CitySummaryCards({ summary, loading, showProvince }: CitySummaryCardsProps) {
  if (loading) {
    return (
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {[...Array(6)].map((_, i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <div className="h-32 bg-gray-200 rounded animate-pulse" />
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  const items = showProvince
    ? summary?.province_summaries ?? []
    : summary?.city_summaries ?? []

  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-gray-500 text-sm">
          No summary data available.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {items.map(city => (
        <CityCard key={city.name} city={city} />
      ))}
    </div>
  )
}

function CityCard({ city }: { city: CitySummary }) {
  const d1 = city.horizons['D+1']
  const d2 = city.horizons['D+2']
  const d3 = city.horizons['D+3']

  // Sparkline data (median across horizons)
  const sparkData = [d1, d2, d3].filter(Boolean).map(h => h?.pm25_median ?? 0)

  return (
    <Card className="overflow-hidden">
      {/* Color strip on top based on worst D+1 band */}
      <div
        className="h-1"
        style={{ backgroundColor: d1 ? BAND_COLORS[d1.worst_band] || '#9ca3af' : '#e5e7eb' }}
      />
      <CardContent className="p-4">
        {/* City header */}
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">{city.name}</h3>
            {city.state_name && (
              <p className="text-[11px] text-slate-400">{city.state_name}</p>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            {/* Trend badge */}
            <span className={`text-sm font-bold ${TREND_STYLES[city.trend] || 'text-slate-400'}`}>
              {TREND_ICONS[city.trend] || '—'}
            </span>
            {city.trend !== 'stable' && city.trend !== 'insufficient_data' && (
              <span className={`text-[10px] font-medium ${TREND_STYLES[city.trend]}`}>
                {city.trend_delta > 0 ? '+' : ''}{Math.round(city.trend_delta)}
              </span>
            )}
          </div>
        </div>

        {/* D+1 headline stats */}
        {d1 && (
          <div className="space-y-2 mb-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">{d1.n_stations} stations</span>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${BAND_BG_COLORS[d1.worst_band] || 'bg-gray-100 text-gray-600'}`}>
                {BAND_LABELS[d1.worst_band] || d1.worst_band}
              </span>
            </div>

            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="text-lg font-bold text-slate-900">{formatPM25(d1.pm25_median)}</div>
                <div className="text-[10px] text-slate-400">Median</div>
              </div>
              <div>
                <div className="text-lg font-bold text-slate-700">{formatPM25(d1.q90_max)}</div>
                <div className="text-[10px] text-slate-400">Max Q90</div>
              </div>
              <div>
                <div className="text-lg font-bold text-slate-700">{formatPercent(d1.frac_unhealthy)}</div>
                <div className="text-[10px] text-slate-400">Unhealthy+</div>
              </div>
            </div>
          </div>
        )}

        {/* Bottom row: ramps, confidence, priority counts */}
        {d1 && (
          <div className="flex items-center justify-between pt-2 border-t border-slate-100">
            <div className="flex items-center gap-2">
              {d1.n_ramp > 0 && (
                <span className="text-[10px] font-medium text-amber-600">
                  {d1.n_ramp} ramps
                </span>
              )}
              {d1.n_escalate > 0 && (
                <span className="text-[10px] font-medium text-red-600">
                  {d1.n_escalate} escalate
                </span>
              )}
              {d1.n_review > 0 && (
                <span className="text-[10px] font-medium text-orange-600">
                  {d1.n_review} review
                </span>
              )}
            </div>
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${CONFIDENCE_STYLES[d1.confidence] || 'bg-gray-100 text-gray-600'}`}>
              {d1.confidence}
            </span>
          </div>
        )}

        {/* Horizon trajectory mini bar */}
        {sparkData.length > 1 && (
          <div className="mt-2 pt-2 border-t border-slate-100">
            <div className="flex items-end gap-1 h-6">
              {sparkData.map((val, i) => {
                const maxVal = Math.max(...sparkData, 1)
                const height = Math.max(4, (val / maxVal) * 24)
                const horizonStats = [d1, d2, d3][i]
                const band = horizonStats?.worst_band || 'good'
                return (
                  <div key={i} className="flex-1 flex flex-col items-center">
                    <div
                      className="w-full rounded-sm"
                      style={{
                        height: `${height}px`,
                        backgroundColor: BAND_COLORS[band] || '#d1d5db',
                        opacity: 0.8,
                      }}
                    />
                    <span className="text-[9px] text-slate-400 mt-0.5">D+{i + 1}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
