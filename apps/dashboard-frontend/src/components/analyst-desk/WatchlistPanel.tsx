"use client"

import { useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import type { WatchlistResponse, WatchlistEntry } from './types'
import { WATCHLIST_CONFIG, BAND_BG_COLORS, formatPM25 } from './utils'

interface WatchlistPanelProps {
  watchlists: WatchlistResponse | undefined
  loading: boolean
  onStationClick: (sensorId: number) => void
}

export function WatchlistPanel({ watchlists, loading, onStationClick }: WatchlistPanelProps) {
  const [activeList, setActiveList] = useState('severe_tomorrow')

  if (loading) {
    return (
      <Card>
        <CardContent className="p-4">
          <div className="h-64 bg-gray-200 rounded animate-pulse" />
        </CardContent>
      </Card>
    )
  }

  if (!watchlists) {
    return (
      <Card>
        <CardContent className="p-6 text-center text-gray-500 text-sm">
          No watchlist data available.
        </CardContent>
      </Card>
    )
  }

  const lists = watchlists.watchlists
  const activeEntries = lists[activeList] || []

  // Compute tab counts
  const nonEmptyLists = Object.entries(lists).filter(([, entries]) => entries.length > 0)

  return (
    <div className="space-y-3">
      {/* Watchlist tabs */}
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(WATCHLIST_CONFIG).map(([key, config]) => {
          const count = lists[key]?.length ?? 0
          const isActive = activeList === key
          return (
            <button
              key={key}
              onClick={() => setActiveList(key)}
              className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-slate-800 text-white'
                  : count > 0
                    ? 'bg-slate-100 text-slate-700 hover:bg-slate-200'
                    : 'bg-slate-50 text-slate-400'
              }`}
            >
              <span>{config.icon}</span>
              <span>{config.label}</span>
              {count > 0 && (
                <span className={`ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
                  isActive ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-600'
                }`}>
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Entries list */}
      <Card>
        <CardContent className="p-0">
          {activeEntries.length === 0 ? (
            <div className="p-6 text-center text-gray-400 text-sm">
              No entries in this watchlist.
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {activeEntries.map((entry, i) => (
                <WatchlistRow
                  key={`${entry.sensor_id}-${i}`}
                  entry={entry}
                  listType={activeList}
                  onClick={() => onStationClick(entry.sensor_id)}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ── Row component ─────────────────────────────────────────────────────

function WatchlistRow({
  entry,
  listType,
  onClick,
}: {
  entry: WatchlistEntry
  listType: string
  onClick: () => void
}) {
  const band = (entry.risk_band || entry.today_band || entry.worst_band || entry.d3_band) as string | undefined
  const forecast = (entry.pm25_forecast || entry.today_d1 || entry.max_forecast || entry.d3_forecast) as number | undefined

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-slate-50 transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-900 truncate">
            {entry.station_name || `Station ${entry.sensor_id}`}
          </span>
          {band && (
            <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${BAND_BG_COLORS[band] || 'bg-gray-100 text-gray-600'}`}>
              {band.replace(/_/g, ' ')}
            </span>
          )}
        </div>
        <div className="text-xs text-slate-500 mt-0.5">
          {entry.city_name && <span>{entry.city_name} &middot; </span>}
          {entry.reason}
        </div>
      </div>

      <div className="flex items-center gap-3 ml-3 shrink-0">
        {forecast != null && (
          <span className="text-sm font-semibold text-slate-700">
            {formatPM25(forecast)}
            <span className="text-[10px] text-slate-400 ml-0.5">µg/m³</span>
          </span>
        )}
        {(entry.delta as number) != null && (entry.delta as number) > 0 && (
          <span className="text-xs font-medium text-red-500">
            +{Math.round(entry.delta as number)}
          </span>
        )}
        {Array.isArray(entry.drivers) && (
          <div className="flex gap-1">
            {(entry.drivers as string[]).map(d => (
              <span key={d} className="px-1.5 py-0.5 bg-orange-50 text-orange-700 rounded text-[10px] font-medium">
                {d}
              </span>
            ))}
          </div>
        )}
        <svg className="w-4 h-4 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </button>
  )
}
