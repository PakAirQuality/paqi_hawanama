"use client"

import { Card, CardContent } from '@/components/ui/card'
import type { ForecastResponse, SummaryResponse, WatchlistResponse } from './types'
import {
  BAND_BG_COLORS,
  BAND_LABELS,
  CONFIDENCE_STYLES,
  TREND_ICONS,
  TREND_STYLES,
  formatPM25,
  formatDate,
} from './utils'

interface DailyOverviewProps {
  forecast: ForecastResponse | undefined
  summary: SummaryResponse | undefined
  watchlists: WatchlistResponse | undefined
  loading: boolean
}

export function DailyOverview({ forecast, summary, watchlists, loading }: DailyOverviewProps) {
  if (loading) {
    return (
      <div className="grid gap-3 md:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <div className="h-16 bg-gray-200 rounded animate-pulse" />
            </CardContent>
          </Card>
        ))}
      </div>
    )
  }

  if (!forecast) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-gray-500">
          No forecast data available. Select a date or check pipeline status.
        </CardContent>
      </Card>
    )
  }

  const entries = forecast.forecasts
  const d1 = entries.filter(e => e.lead_days === 1)

  // National stats
  const nStations = forecast.n_stations
  const nSevere = d1.filter(e => e.risk_band === 'severe' || e.risk_band === 'very_unhealthy').length
  const nUnhealthy = d1.filter(e => e.risk_band === 'unhealthy' || e.risk_band === 'very_unhealthy' || e.risk_band === 'severe').length
  const nEscalate = d1.filter(e => e.priority === 'escalate').length
  const nRamp = d1.filter(e => e.ramp_detected).length

  // Confidence distribution
  const nHigh = d1.filter(e => e.confidence === 'high').length
  const nMedium = d1.filter(e => e.confidence === 'medium').length
  const nLow = d1.filter(e => e.confidence === 'low').length
  const confLabel = nLow > d1.length * 0.3 ? 'low' : nHigh > d1.length * 0.5 ? 'high' : 'medium'

  // Cities flagged
  const flaggedCities = summary?.city_summaries?.filter(
    c => c.horizons?.['D+1']?.worst_band && ['unhealthy', 'very_unhealthy', 'severe'].includes(c.horizons['D+1'].worst_band)
  ).length ?? 0

  // Watchlist totals
  const totalWatchlistEntries = watchlists
    ? Object.values(watchlists.watchlists).reduce((sum, entries) => sum + entries.length, 0)
    : 0

  // Worst band nationally
  const bandOrder = ['good', 'moderate', 'unhealthy', 'very_unhealthy', 'severe']
  const worstBand = d1.reduce((worst, e) => {
    const idx = bandOrder.indexOf(e.risk_band)
    const wIdx = bandOrder.indexOf(worst)
    return idx > wIdx ? e.risk_band : worst
  }, 'good')

  // Worsening cities
  const worseningCities = summary?.city_summaries?.filter(c => c.trend === 'worsening').length ?? 0

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">
            Forecast: {formatDate(forecast.init_date)}
          </h2>
          <p className="text-xs text-gray-500">
            {nStations} stations &middot; D+1 through D+{Math.max(...forecast.horizons)} &middot; Generated {new Date(forecast.generated_at).toLocaleTimeString()}
          </p>
        </div>
        <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${BAND_BG_COLORS[worstBand] || 'bg-gray-100 text-gray-600'}`}>
          National: {BAND_LABELS[worstBand] || worstBand}
        </span>
      </div>

      {/* Key metrics row */}
      <div className="grid gap-3 md:grid-cols-5">
        {/* Escalate count */}
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-1">Escalate Priority</div>
            <div className="text-2xl font-bold text-red-600">{nEscalate}</div>
            <div className="text-xs text-gray-400">of {d1.length} D+1 stations</div>
          </CardContent>
        </Card>

        {/* Severe / Very Unhealthy */}
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-1">Severe + Very Unhealthy</div>
            <div className="text-2xl font-bold text-purple-700">{nSevere}</div>
            <div className="text-xs text-gray-400">{nUnhealthy} total unhealthy+</div>
          </CardContent>
        </Card>

        {/* Ramps detected */}
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-1">Ramp Detected</div>
            <div className="text-2xl font-bold text-amber-600">{nRamp}</div>
            <div className="text-xs text-gray-400">stations tomorrow</div>
          </CardContent>
        </Card>

        {/* Flagged cities */}
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-1">Cities Unhealthy+</div>
            <div className="text-2xl font-bold text-orange-600">{flaggedCities}</div>
            <div className="text-xs text-gray-400">{worseningCities} worsening</div>
          </CardContent>
        </Card>

        {/* Confidence */}
        <Card>
          <CardContent className="p-4">
            <div className="text-xs font-medium text-gray-500 mb-1">Confidence</div>
            <div className="flex items-baseline gap-2">
              <span className={`px-2 py-0.5 rounded text-xs font-semibold ${CONFIDENCE_STYLES[confLabel]}`}>
                {confLabel.toUpperCase()}
              </span>
            </div>
            <div className="text-xs text-gray-400 mt-1">
              {nHigh}H / {nMedium}M / {nLow}L
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Watchlist summary bar */}
      {watchlists && totalWatchlistEntries > 0 && (
        <div className="flex items-center gap-3 px-4 py-2.5 bg-slate-50 rounded-lg border border-slate-200">
          <span className="text-xs font-medium text-slate-600">Watchlists:</span>
          {Object.entries(watchlists.watchlists).map(([name, entries]) => {
            if (entries.length === 0) return null
            const displayName = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
            return (
              <span key={name} className="text-xs text-slate-500">
                <span className="font-medium text-slate-700">{entries.length}</span> {displayName}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
