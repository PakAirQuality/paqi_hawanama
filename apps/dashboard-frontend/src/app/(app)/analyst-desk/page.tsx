"use client"

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
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
import { IconRail, type RailTab } from '@/components/analyst-desk/IconRail'
import { LayersPanel } from '@/components/analyst-desk/LayersPanel'
import { ContextPanel } from '@/components/analyst-desk/ContextPanel'
import type { CopilotAction, StationMention } from '@/components/analyst-desk/types'

export default function AnalystDeskPage() {
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedHorizon, setSelectedHorizon] = useState(0)
  const [stationMention, setStationMention] = useState<StationMention | null>(null)
  const [cityMention, setCityMention] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<CopilotAction | null>(null)
  const [networkFilter, setNetworkFilter] = useState<string | null>(null)

  // Sidebar state
  const [railTab, setRailTab] = useState<RailTab | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)

  // Layer toggles (lifted from ForecastMap so LayersPanel can control them)
  const [showStations, setShowStations] = useState(true)
  const [showSatellite, setShowSatellite] = useState(true)
  const [showFires, setShowFires] = useState(true)
  const [showWind, setShowWind] = useState(true)
  const [showPopulation, setShowPopulation] = useState(false)

  // Map ref for resize during panel animation
  const mapRef = useRef<{ resize: () => void } | null>(null)

  // Smooth map resize during panel transition
  useEffect(() => {
    let raf: number
    const tick = () => {
      mapRef.current?.resize()
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const stop = setTimeout(() => cancelAnimationFrame(raf), 350)
    return () => { cancelAnimationFrame(raf); clearTimeout(stop) }
  }, [railTab])

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

  const { data: currentStations } = useQuery({
    queryKey: ['analyst-current-stations'],
    queryFn: fetchCurrentStations,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  })

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
    // Don't force open — just notify the analytics tab
  }, [])

  const handleMentionConsumed = useCallback(() => {
    setStationMention(null)
    setCityMention(null)
  }, [])

  const handleDistrictClick = useCallback((cityName: string) => {
    setCityMention(cityName)
  }, [])

  const handleCopilotAction = useCallback((action: CopilotAction) => {
    if (action.type === 'set_horizon' && action.horizon != null) {
      setSelectedHorizon(action.horizon)
    } else if (action.type === 'filter_network') {
      setNetworkFilter(action.network ?? null)
    } else if (action.type === 'show_station_trend') {
      setRailTab('analytics')
      setPendingAction(action)
    } else {
      setPendingAction(action)
    }
  }, [])

  const handleActionProcessed = useCallback(() => {
    setPendingAction(null)
  }, [])

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

  const isLoading = !forecast && !currentStations

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* Icon rail */}
      <IconRail
        activeTab={railTab}
        onTabChange={setRailTab}
        isStreaming={isStreaming}
      />

      {/* Sliding panel */}
      <div
        style={{
          width: railTab ? 370 : 0,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          background: '#fff',
          borderRight: railTab ? '1px solid #e2e8f0' : 'none',
          overflow: 'hidden',
          transition: 'width 250ms cubic-bezier(0.4, 0, 0.2, 1)',
        }}
      >
        {/* Chat / Analytics panel (single instance) */}
        <div style={{
          display: railTab === 'chat' || railTab === 'analytics' ? 'flex' : 'none',
          flexDirection: 'column',
          height: '100%',
        }}>
          <CopilotChat
            selectedDate={selectedDate}
            onAction={handleCopilotAction}
            stationMention={stationMention}
            cityMention={cityMention}
            onMentionConsumed={handleMentionConsumed}
            stations={analyticsStations}
            onStreamingChange={setIsStreaming}
            activeTab={railTab === 'analytics' ? 'analytics' : 'chat'}
          />
        </div>

        {/* Layers panel */}
        <div style={{ display: railTab === 'layers' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <LayersPanel
            showStations={showStations}
            onToggleStations={() => setShowStations(v => !v)}
            showSatellite={showSatellite}
            onToggleSatellite={() => setShowSatellite(v => !v)}
            showFires={showFires}
            onToggleFires={() => setShowFires(v => !v)}
            showWind={showWind}
            onToggleWind={() => setShowWind(v => !v)}
            showPopulation={showPopulation}
            onTogglePopulation={() => setShowPopulation(v => !v)}
          />
        </div>
      </div>

      {/* Map — always rendered, data loads on top */}
      <div className="flex-1 relative">
        <ForecastMap
          forecasts={forecast?.forecasts ?? []}
          currentStations={currentStations?.stations ?? []}
          selectedHorizon={selectedHorizon}
          onHorizonChange={setSelectedHorizon}
          onStationClick={handleStationClick}
          onDistrictClick={handleDistrictClick}
          pendingAction={pendingAction}
          onActionProcessed={handleActionProcessed}
          networkFilter={networkFilter}
          onClearNetworkFilter={() => setNetworkFilter(null)}
          firesGeoJSON={firesGeoJSON ?? null}
          showStations={showStations}
          showSatellite={showSatellite}
          showFires={showFires}
          showWind={showWind}
          onToggleStations={() => setShowStations(v => !v)}
          onToggleSatellite={() => setShowSatellite(v => !v)}
          onToggleFires={() => setShowFires(v => !v)}
          onToggleWind={() => setShowWind(v => !v)}
          showPopulation={showPopulation}
          onTogglePopulation={() => setShowPopulation(v => !v)}
          mapRef={mapRef}
        />
        {isLoading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/60 backdrop-blur-[2px]">
            <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-slate-800/90 text-white text-sm font-medium shadow-lg">
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Loading station data...
            </div>
          </div>
        )}
      </div>

      {/* Right context panel — persistent daily brief */}
      <div className="w-[260px] shrink-0 bg-white border-l border-slate-100 overflow-hidden">
        <ContextPanel
          currentStations={currentStations?.stations ?? []}
          forecasts={forecast?.forecasts ?? []}
          firesGeoJSON={firesGeoJSON ?? null}
          selectedHorizon={selectedHorizon}
        />
      </div>
    </div>
  )
}
