"use client"

import { useState, useCallback, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchForecast,
  fetchWatchlist,
  fetchSummary,
  fetchAvailableDates,
  fetchCurrentStations,
  fetchFires,
} from '@/components/analyst-desk'
import { ForecastMap } from '@/components/analyst-desk/ForecastMap'
import { CopilotChat } from '@/components/analyst-desk/CopilotChat'
import type { CopilotAction, StationMention } from '@/components/analyst-desk/types'

export default function AnalystDeskPage() {
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedHorizon, setSelectedHorizon] = useState(0) // 0 = Now
  const [stationMention, setStationMention] = useState<StationMention | null>(null)
  const [pendingAction, setPendingAction] = useState<CopilotAction | null>(null)
  const [networkFilter, setNetworkFilter] = useState<string | null>(null)

  // Fetch available dates and auto-select the latest
  const { data: availableDates } = useQuery({
    queryKey: ['analyst-dates'],
    queryFn: fetchAvailableDates,
    staleTime: 10 * 60 * 1000,
  })

  useEffect(() => {
    if (availableDates?.dates?.length && !selectedDate) {
      setSelectedDate(availableDates.dates[0])
    }
  }, [availableDates, selectedDate])

  // Current station readings (for "Now" view)
  const { data: currentStations } = useQuery({
    queryKey: ['analyst-current-stations'],
    queryFn: fetchCurrentStations,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  })

  // Forecast data queries
  const { data: forecast, isLoading: forecastLoading } = useQuery({
    queryKey: ['analyst-forecast', selectedDate],
    queryFn: () => fetchForecast(selectedDate),
    staleTime: 5 * 60 * 1000,
    retry: 2,
    enabled: !!selectedDate,
  })

  useQuery({
    queryKey: ['analyst-watchlists', selectedDate],
    queryFn: () => fetchWatchlist(selectedDate),
    staleTime: 5 * 60 * 1000,
    retry: 2,
    enabled: !!selectedDate,
  })

  useQuery({
    queryKey: ['analyst-summary', selectedDate],
    queryFn: () => fetchSummary(selectedDate),
    staleTime: 5 * 60 * 1000,
    retry: 2,
    enabled: !!selectedDate,
  })

  const { data: firesGeoJSON } = useQuery({
    queryKey: ['analyst-fires', selectedDate],
    queryFn: () => fetchFires(selectedDate),
    staleTime: 15 * 60 * 1000,
    retry: 1,
    enabled: !!selectedDate,
  })

  const handleStationClick = useCallback((mention: StationMention) => {
    setStationMention(mention)
  }, [])

  const handleMentionConsumed = useCallback(() => {
    setStationMention(null)
  }, [])

  const handleCopilotAction = useCallback((action: CopilotAction) => {
    if (action.type === 'set_horizon' && action.horizon != null) {
      setSelectedHorizon(action.horizon)
    } else if (action.type === 'filter_network') {
      setNetworkFilter(action.network ?? null)
    } else {
      setPendingAction(action)
    }
  }, [])

  const handleActionProcessed = useCallback(() => {
    setPendingAction(null)
  }, [])

  // Compute analytics stations for copilot sidebar
  const analyticsStations = useMemo(() => {
    if (selectedHorizon === 0) {
      return (currentStations?.stations ?? [])
        .filter(s => s.pm25 != null)
        .map(s => {
          const pm25 = s.pm25!
          const band = pm25 <= 35 ? 'good' : pm25 <= 75 ? 'moderate' : pm25 <= 150 ? 'unhealthy' : pm25 <= 250 ? 'very_unhealthy' : 'severe'
          return { pm25, band, city: s.city || '' }
        })
    }
    return (forecast?.forecasts ?? [])
      .filter(f => f.lead_days === selectedHorizon)
      .map(f => {
        const pm25 = f.pm25_forecast
        const rawBand = f.risk_band
        const band = (rawBand && rawBand !== 'unknown') ? rawBand : (pm25 == null ? 'moderate' : pm25 <= 35 ? 'good' : pm25 <= 75 ? 'moderate' : pm25 <= 150 ? 'unhealthy' : pm25 <= 250 ? 'very_unhealthy' : 'severe')
        return { pm25, band, city: f.city_name || '' }
      })
  }, [forecast, currentStations, selectedHorizon])

  const hasMapData = forecast || currentStations

  return (
    <div className="flex h-[calc(100vh-108px)]">
      {/* Left: Copilot chat */}
      <div className="w-[380px] shrink-0 border-r border-slate-200">
        <CopilotChat
          selectedDate={selectedDate}
          onAction={handleCopilotAction}
          stationMention={stationMention}
          onMentionConsumed={handleMentionConsumed}
          stations={analyticsStations}
        />
      </div>

      {/* Right: Full-bleed map */}
      <div className="flex-1 relative">
        {hasMapData ? (
          <ForecastMap
            forecasts={forecast?.forecasts ?? []}
            currentStations={currentStations?.stations ?? []}
            selectedHorizon={selectedHorizon}
            onHorizonChange={setSelectedHorizon}
            onStationClick={handleStationClick}
            pendingAction={pendingAction}
            onActionProcessed={handleActionProcessed}
            networkFilter={networkFilter}
            onClearNetworkFilter={() => setNetworkFilter(null)}
            firesGeoJSON={firesGeoJSON ?? null}
          />
        ) : forecastLoading ? (
          <div className="w-full h-full bg-slate-100 animate-pulse" />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-slate-50 text-slate-400 text-sm">
            No forecast data available.
          </div>
        )}
      </div>

    </div>
  )
}
