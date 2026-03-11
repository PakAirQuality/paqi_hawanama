"use client"

import { useState, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchForecast,
  fetchWatchlist,
  fetchSummary,
  fetchAvailableDates,
  fetchCurrentStations,
} from '@/components/analyst-desk'
import { ForecastMap } from '@/components/analyst-desk/ForecastMap'
import { CopilotChat } from '@/components/analyst-desk/CopilotChat'
import { StationDetailDrawer } from '@/components/analyst-desk/StationDetailDrawer'
import type { CopilotAction } from '@/components/analyst-desk/types'

export default function AnalystDeskPage() {
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedHorizon, setSelectedHorizon] = useState(0) // 0 = Now
  const [selectedStation, setSelectedStation] = useState<number | null>(null)
  const [pendingAction, setPendingAction] = useState<CopilotAction | null>(null)

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

  const handleStationClick = useCallback((sensorId: number) => {
    setSelectedStation(sensorId)
  }, [])

  const handleCopilotAction = useCallback((action: CopilotAction) => {
    if (action.type === 'set_horizon' && action.horizon != null) {
      setSelectedHorizon(action.horizon)
    } else {
      setPendingAction(action)
    }
  }, [])

  const handleActionProcessed = useCallback(() => {
    setPendingAction(null)
  }, [])

  const hasMapData = forecast || currentStations

  return (
    <div className="flex" style={{ height: 'calc(100vh - 108px)' }}>
      {/* Left: Copilot chat */}
      <div className="w-[340px] shrink-0">
        <CopilotChat
          selectedDate={selectedDate}
          onAction={handleCopilotAction}
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
          />
        ) : forecastLoading ? (
          <div className="w-full h-full bg-slate-100 animate-pulse" />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-slate-50 text-slate-400 text-sm">
            No forecast data available.
          </div>
        )}
      </div>

      {/* Station detail drawer */}
      {selectedStation != null && forecast && (
        <>
          <div
            className="fixed inset-0 bg-black/20 z-40"
            onClick={() => setSelectedStation(null)}
          />
          <StationDetailDrawer
            sensorId={selectedStation}
            forecasts={forecast.forecasts}
            onClose={() => setSelectedStation(null)}
          />
        </>
      )}
    </div>
  )
}
