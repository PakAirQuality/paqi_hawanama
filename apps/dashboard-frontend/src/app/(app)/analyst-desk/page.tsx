"use client"

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { bandKey, normalizeBand } from '@/lib/aqi'
import { useSelection } from '@/lib/selection'
import { useQuery } from '@tanstack/react-query'
import { m, useDragControls } from 'motion/react'
import { useIsMobile } from '@/lib/useMediaQuery'
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
  const selection = useSelection()
  const [selectedDate, setSelectedDate] = useState('')
  const [selectedHorizon, setSelectedHorizon] = useState(0)
  const [stationMention, setStationMention] = useState<StationMention | null>(null)
  const [cityMention, setCityMention] = useState<string | null>(null)
  const [pendingAction, setPendingAction] = useState<CopilotAction | null>(null)
  const [networkFilter, setNetworkFilter] = useState<string | null>(null)

  // Sidebar state
  const [railTab, setRailTab] = useState<RailTab | null>(null)
  const isMobile = useIsMobile()
  const sheetDrag = useDragControls()
  const [isStreaming, setIsStreaming] = useState(false)

  // Layer toggles (lifted from ForecastMap so LayersPanel can control them)
  const [showStations, setShowStations] = useState(true)
  const [showSatellite, setShowSatellite] = useState(true)
  const [showFires, setShowFires] = useState(false)
  const [showWind, setShowWind] = useState(true)
  const [showPopulation, setShowPopulation] = useState(false)

  // Map ref for resize during panel animation
  const mapRef = useRef<{ resize: () => void } | null>(null)

  // Resize the map only when its container actually changes size (one call per frame at most)
  const mapWrapRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = mapWrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let raf = 0
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => mapRef.current?.resize())
    })
    ro.observe(el)
    return () => { ro.disconnect(); cancelAnimationFrame(raf) }
  }, [])

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

  // Mirror into the shared selection (header badge, chat context)
  useEffect(() => {
    if (selectedDate) selection.setDate(selectedDate, selectedDate === availableDates?.dates?.[0])
  }, [selectedDate, availableDates]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    selection.setLayer('fires', showFires); selection.setLayer('population', showPopulation)
  }, [showFires, showPopulation]) // eslint-disable-line react-hooks/exhaustive-deps

  const { data: currentStations } = useQuery({
    queryKey: ['analyst-current-stations'],
    queryFn: fetchCurrentStations,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  })

  const { data: forecast } = useQuery({
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
          return { pm25, band: bandKey(pm25), city: s.city || '' }
        })
    }
    return (forecast?.forecasts ?? [])
      .filter(f => f.lead_days === selectedHorizon)
      .map(f => {
        const pm25 = f.pm25_forecast
        // Classify from the value itself so stored legacy bands can never disagree with the markers
        const band = pm25 == null ? normalizeBand(f.risk_band) : bandKey(pm25)
        return { pm25, band, city: f.city_name || '' }
      })
  }, [forecast, currentStations, selectedHorizon])

  const isLoading = !forecast && !currentStations

  return (
    <div className="relative flex flex-1 min-h-0 overflow-hidden max-md:flex-col-reverse">
      {/* Icon rail (bottom bar on phones) */}
      <IconRail
        activeTab={railTab}
        onTabChange={setRailTab}
        isStreaming={isStreaming}
        tabs={['chat', 'analytics', 'layers']}
      />

      {/* Sliding panel: width springs open, content stays 370px wide so it never reflows mid-animation */}
      <m.div
        initial={false}
        animate={isMobile ? { height: railTab ? '72%' : 0 } : { width: railTab ? 370 : 0 }}
        transition={{ type: 'spring', stiffness: 380, damping: 40 }}
        className={isMobile ? 'absolute inset-x-0 bottom-14 z-30 flex flex-col rounded-t-2xl shadow-[0_-8px_32px_rgba(15,23,42,0.18)]' : ''}
        style={{ flexShrink: 0, background: '#fff', overflow: 'hidden' }}
        drag={isMobile ? 'y' : false}
        dragControls={sheetDrag}
        dragListener={false}
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={{ top: 0, bottom: 0.6 }}
        onDragEnd={(_, info) => { if (info.offset.y > 90 || info.velocity.y > 600) setRailTab(null) }}
      >
        {isMobile && (
          <div
            className="flex shrink-0 cursor-grab touch-none justify-center py-2.5"
            onPointerDown={e => sheetDrag.start(e)}
            aria-hidden
          >
            <span className="h-1 w-10 rounded-full bg-slate-300" />
          </div>
        )}
        <div style={{ width: isMobile ? '100%' : 370, ...(isMobile ? { flex: '1 1 0', minHeight: 0 } : { height: '100%' }), display: 'flex', flexDirection: 'column' }}>
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
      </m.div>

      {/* Map — always rendered, data loads on top */}
      <div ref={mapWrapRef} className="flex-1 relative">
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
      <div className="hidden lg:block w-[300px] shrink-0 bg-white overflow-hidden">
        <ContextPanel
          currentStations={currentStations?.stations ?? []}
          forecasts={forecast?.forecasts ?? []}
          firesGeoJSON={firesGeoJSON ?? null}
          selectedHorizon={selectedHorizon}
          selectedDate={selectedDate || null}
        />
      </div>
    </div>
  )
}
