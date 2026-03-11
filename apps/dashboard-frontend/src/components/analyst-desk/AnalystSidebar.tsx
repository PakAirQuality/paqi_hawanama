"use client"

import type { ForecastResponse, SummaryResponse, WatchlistResponse, ForecastEntry, CitySummary } from './types'
import { BAND_COLORS, BAND_BG_COLORS, BAND_LABELS, TREND_ICONS, TREND_STYLES, formatPM25 } from './utils'

interface AnalystSidebarProps {
  forecast: ForecastResponse | undefined
  summary: SummaryResponse | undefined
  watchlists: WatchlistResponse | undefined
  selectedDate: string
  onStationClick: (sensorId: number) => void
}

export function AnalystSidebar({
  forecast,
  summary,
  watchlists,
  selectedDate,
  onStationClick,
}: AnalystSidebarProps) {
  const d1 = forecast?.forecasts?.filter(e => e.lead_days === 1) ?? []
  const cities = summary?.city_summaries ?? []

  // Generate briefing from data
  const briefing = generateBriefing(d1, cities, watchlists)

  // Top hotspots: cities sorted by worst D+1 PM2.5
  const hotspots = getTopHotspots(cities, 5)

  // Format date for display
  const dateLabel = selectedDate
    ? new Date(selectedDate + 'T00:00:00').toLocaleDateString('en-US', {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
      })
    : ''

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="px-5 py-4 border-b border-slate-100">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">Analyst Desk</h2>
          <span className="text-xs text-slate-400">{dateLabel}</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Today's Briefing */}
        <div className="px-5 py-4 border-b border-slate-100">
          <h3 className="text-sm font-semibold text-slate-800 mb-3">Today&apos;s Briefing</h3>
          {briefing ? (
            <p className="text-[13px] leading-relaxed text-slate-600">{briefing}</p>
          ) : (
            <div className="space-y-2">
              <div className="h-3 bg-slate-100 rounded animate-pulse" />
              <div className="h-3 bg-slate-100 rounded animate-pulse w-4/5" />
              <div className="h-3 bg-slate-100 rounded animate-pulse w-3/5" />
            </div>
          )}
        </div>

        {/* Top Hotspots */}
        <div className="px-5 py-4 border-b border-slate-100">
          <h3 className="text-sm font-semibold text-slate-800 mb-3">Top Hotspots</h3>
          {hotspots.length > 0 ? (
            <div className="space-y-2">
              {hotspots.map((city, i) => {
                const d1h = city.horizons['D+1']
                if (!d1h) return null
                const band = d1h.worst_band || 'moderate'
                const color = BAND_COLORS[band] || '#9ca3af'

                return (
                  <div
                    key={city.name}
                    className="flex items-center justify-between py-2 px-3 rounded-lg hover:bg-slate-50 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className="w-3 h-3 rounded-full shrink-0"
                        style={{ backgroundColor: color }}
                      />
                      <div>
                        <span className="text-sm font-medium text-slate-800">{city.name}</span>
                        {city.state_name && (
                          <span className="text-[11px] text-slate-400 ml-1.5">{city.state_name}</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-lg font-bold text-slate-900">
                        {formatPM25(d1h.pm25_max)}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${BAND_BG_COLORS[band] || 'bg-gray-100 text-gray-600'}`}>
                        {BAND_LABELS[band]}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-xs text-slate-400">No city data available.</p>
          )}
        </div>

        {/* Suggested Actions */}
        <div className="px-5 py-4">
          <h3 className="text-sm font-semibold text-slate-800 mb-3">Suggested Actions</h3>
          <div className="space-y-1.5">
            {getSuggestedActions(d1, cities, watchlists).map((action, i) => (
              <button
                key={i}
                className="w-full flex items-center gap-3 px-3 py-2.5 text-left rounded-lg hover:bg-slate-50 transition-colors group"
              >
                <span className="text-base shrink-0">{action.icon}</span>
                <span className="text-[13px] text-slate-600 group-hover:text-slate-900 flex-1">
                  {action.text}
                </span>
                <svg className="w-4 h-4 text-slate-300 group-hover:text-slate-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Briefing generator ─────────────────────────────────────────────

function generateBriefing(
  d1: ForecastEntry[],
  cities: CitySummary[],
  watchlists: WatchlistResponse | undefined,
): string | null {
  if (d1.length === 0 && cities.length === 0) return null

  const parts: string[] = []

  // National summary
  if (d1.length > 0) {
    const forecasts = d1.map(e => e.pm25_forecast).filter((v): v is number => v != null)
    const mean = forecasts.length ? Math.round(forecasts.reduce((a, b) => a + b, 0) / forecasts.length) : null
    const nUnhealthy = d1.filter(e =>
      e.risk_band === 'unhealthy' || e.risk_band === 'very_unhealthy' || e.risk_band === 'severe'
    ).length
    const nRamp = d1.filter(e => e.ramp_detected).length

    if (mean != null) {
      const severity = mean > 150 ? 'very unhealthy' : mean > 75 ? 'unhealthy' : mean > 35 ? 'moderate' : 'good'
      parts.push(`Air quality across Pakistan is currently ${severity}, with a national average PM2.5 of ${mean} µg/m³.`)
    }

    if (nUnhealthy > 0) {
      const pct = Math.round((nUnhealthy / d1.length) * 100)
      parts.push(`${nUnhealthy} stations (${pct}%) are forecasting unhealthy or worse conditions tomorrow.`)
    }

    if (nRamp > 0) {
      parts.push(`${nRamp} station${nRamp > 1 ? 's' : ''} ${nRamp > 1 ? 'have' : 'has'} ramp events detected.`)
    }
  }

  // Worst city
  if (cities.length > 0) {
    const worstCity = getTopHotspots(cities, 1)[0]
    if (worstCity) {
      const d1h = worstCity.horizons['D+1']
      if (d1h) {
        parts.push(`${worstCity.name} is the worst affected city with PM2.5 up to ${formatPM25(d1h.pm25_max)} µg/m³.`)
      }
    }

    const worsening = cities.filter(c => c.trend === 'worsening')
    if (worsening.length > 0) {
      const names = worsening.slice(0, 3).map(c => c.name).join(', ')
      parts.push(`Conditions are worsening in ${names}${worsening.length > 3 ? ` and ${worsening.length - 3} other cities` : ''}.`)
    }
  }

  return parts.length > 0 ? parts.join(' ') : null
}

// ── Hotspot ranking ────────────────────────────────────────────────

function getTopHotspots(cities: CitySummary[], n: number): CitySummary[] {
  return [...cities]
    .filter(c => c.horizons['D+1'])
    .sort((a, b) => {
      const aMax = a.horizons['D+1']?.pm25_max ?? 0
      const bMax = b.horizons['D+1']?.pm25_max ?? 0
      return bMax - aMax
    })
    .slice(0, n)
}

// ── Suggested actions ──────────────────────────────────────────────

function getSuggestedActions(
  d1: ForecastEntry[],
  cities: CitySummary[],
  watchlists: WatchlistResponse | undefined,
): { icon: string; text: string }[] {
  const actions: { icon: string; text: string }[] = []

  // Find worst city
  const hotspots = getTopHotspots(cities, 1)
  if (hotspots.length > 0) {
    actions.push({
      icon: '\u{1F50D}',
      text: `Why is ${hotspots[0].name} the worst today?`,
    })
  }

  // Worsening cities
  const worsening = cities.filter(c => c.trend === 'worsening')
  if (worsening.length > 0) {
    actions.push({
      icon: '\u{1F4C8}',
      text: `What changed since yesterday?`,
    })
  }

  // Ramp events
  const nRamp = d1.filter(e => e.ramp_detected).length
  if (nRamp > 0) {
    actions.push({
      icon: '\u26A1',
      text: `Review ${nRamp} stations with ramp events`,
    })
  }

  // Province breakdown
  actions.push({
    icon: '\u{1F5FA}',
    text: 'Show the worst districts in Punjab',
  })

  // Guidance
  actions.push({
    icon: '\u{1F3EB}',
    text: 'Give school guidance for sensitive groups',
  })

  return actions.slice(0, 5)
}
