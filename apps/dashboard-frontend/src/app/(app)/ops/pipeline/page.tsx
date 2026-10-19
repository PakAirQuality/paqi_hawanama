"use client"

import { useState, useEffect, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Calendar } from 'lucide-react'

import { fetchTileDates, fetchStationDaily, fetchPredictionData, fetchRunReport, fetchStationDirectory } from '@/components/ops-pipeline'
import { PredictionMap } from '@/components/ops-pipeline/PredictionMap'
import { OpsContextPanel } from '@/components/ops-pipeline/ContextPanel'
import { StructuresTab, type IndustryCategory, type IndustryItem, type KilnItem } from '@/components/ops-pipeline/StructuresTab'
import { FiresPanel } from '@/components/ops-pipeline/FiresPanel'
import { IconRail, type RailTab } from '@/components/analyst-desk/IconRail'
import { CopilotChat } from '@/components/analyst-desk/CopilotChat'
import { fetchFires } from '@/components/analyst-desk/api'
import { loadPakBoundary, isInsidePakistan } from '@/components/analyst-desk/pakistan'
import { useSelection } from '@/lib/selection'
import { formatDateOnly, pktToday } from '@/lib/time'
import { INDUSTRY_CATEGORIES, loadEmissionSources, loadKilnsGeoJSON } from '@/lib/staticLayers'
import { MapErrorBoundary, MapUnavailableNotice } from '@/components/MapErrorBoundary'
import type { MapUnavailableReason } from '@/lib/webgl'

export default function OpsPipelinePage() {
  const selection = useSelection()
  const [selectedPredDate, setSelectedPredDate] = useState<string | null>(null)
  const [model, setModel] = useState<'backbone' | 'support_aware'>('backbone')

  // Side channel state
  const [railTab, setRailTab] = useState<RailTab | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)

  // Layer toggles
  const [showKilns, setShowKilns] = useState(true)
  const [showIndustry, setShowIndustry] = useState(true)
  const [showFires, setShowFires] = useState(false)

  // Map flyTo callback + static data
  const [flyTo, setFlyTo] = useState<((lng: number, lat: number, zoom?: number) => void) | null>(null)
  const [kilnsData, setKilnsData] = useState<KilnItem[]>([])
  const [industryData, setIndustryData] = useState<IndustryCategory[]>([])

  // Static inventories for the Sources panel: same cached loads the map uses (parsed once)
  useEffect(() => {
    loadKilnsGeoJSON()
      .then(data => {
        setKilnsData(data.features.map(f => ({
          ...f.properties,
          lat: (f.geometry as GeoJSON.Point).coordinates[1],
          lon: (f.geometry as GeoJSON.Point).coordinates[0],
        }) as KilnItem))
      })
      .catch(() => {})

    loadEmissionSources()
      .then(data => {
        setIndustryData(INDUSTRY_CATEGORIES.filter(c => data[c.key]?.features?.length).map(c => ({
          ...c,
          items: data[c.key].features.map(f => ({
            ...f.properties,
            lat: (f.geometry as GeoJSON.Point).coordinates[1],
            lon: (f.geometry as GeoJSON.Point).coordinates[0],
          }) as IndustryItem),
        })))
      })
      .catch(() => {})
  }, [])

  // Map availability: a map failure stays inside the map area (nav, panels, reports keep working)
  const [mapUnavailable, setMapUnavailable] = useState<MapUnavailableReason | null>(null)
  const [mapKey, setMapKey] = useState(0)
  const retryMap = () => { setMapUnavailable(null); setMapKey(k => k + 1) }

  // Shareable URLs: ?date=YYYY-MM-DD&model=support_aware&layers=kilns,industry,fires
  const urlApplied = useRef(false)
  useEffect(() => {
    if (urlApplied.current || typeof window === 'undefined') return
    urlApplied.current = true
    const q = new URLSearchParams(window.location.search)
    const d = q.get('date'); if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) setSelectedPredDate(d)
    const m = q.get('model'); if (m === 'support_aware' || m === 'backbone') setModel(m)
    const layers = q.get('layers')
    if (layers != null) {
      const on = new Set(layers.split(',').filter(Boolean))
      setShowKilns(on.has('kilns')); setShowIndustry(on.has('industry')); setShowFires(on.has('fires'))
    }
  }, [])
  useEffect(() => {
    if (!selectedPredDate || typeof window === 'undefined') return
    const q = new URLSearchParams()
    q.set('date', selectedPredDate)
    if (model !== 'backbone') q.set('model', model)
    const layers = [showKilns && 'kilns', showIndustry && 'industry', showFires && 'fires'].filter(Boolean).join(',')
    q.set('layers', layers)
    window.history.replaceState(null, '', `${window.location.pathname}?${q}`)
  }, [selectedPredDate, model, showKilns, showIndustry, showFires])

  // Force map resize when panel opens/closes
  const mapWrapperRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // Dispatch a resize event so mapbox-gl picks up the container change
    let raf: number
    const tick = () => {
      window.dispatchEvent(new Event('resize'))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const stop = setTimeout(() => cancelAnimationFrame(raf), 350)
    return () => { cancelAnimationFrame(raf); clearTimeout(stop) }
  }, [railTab])

  // Auto-show fires on map when fires tab is active
  useEffect(() => {
    setShowFires(railTab === 'fires')
  }, [railTab])

  const { data: tileDates, isLoading: tileDatesLoading } = useQuery({
    queryKey: ["ops-pipeline-tile-dates"],
    queryFn: () => fetchTileDates(365),
  })

  // One station query for map markers and panels (the map used to fetch its own copy with
  // different parameters, so markers and the Stations panel could disagree).
  const { data: stationData } = useQuery({
    queryKey: ['ops-station-daily', selectedPredDate, 6],
    queryFn: () => fetchStationDaily(selectedPredDate!, 'Pakistan', 6),
    enabled: !!selectedPredDate,
  })

  // Grid stats for the model the map is showing (area average over the model domain)
  const { data: predictionData } = useQuery({
    queryKey: ['ops-prediction-data', selectedPredDate, model],
    queryFn: () => fetchPredictionData(selectedPredDate!, model),
    enabled: !!selectedPredDate,
  })

  const { data: runReport } = useQuery({
    queryKey: ['ops-run-report', selectedPredDate],
    queryFn: () => fetchRunReport(selectedPredDate!),
    enabled: !!selectedPredDate,
  })

  // Satellite fire detections — fetched for the selected Pakistan day, filtered to Pakistan.
  // The response carries an explicit status (ok/empty/partial/stale/unavailable); the panel
  // shows it, so a stale or missing day is never disguised as "no fires".
  const { data: firesGeoJSON, isLoading: firesLoading, isFetching: firesFetching, isError: firesError, error: firesErrorObj } = useQuery({
    queryKey: ['ops-fires', selectedPredDate],
    queryFn: async () => {
      await loadPakBoundary()
      const data = await fetchFires(selectedPredDate!)
      return {
        ...data,
        features: data.features.filter(f => {
          const [lng, lat] = f.geometry.coordinates
          return isInsidePakistan(lng, lat)
        }),
      }
    },
    enabled: !!selectedPredDate,
    retry: 1,
  })

  // Station directory — fetch once, used to resolve station_ids for navigation
  const { data: stationDirectory } = useQuery({
    queryKey: ['station-directory-pk'],
    queryFn: () => fetchStationDirectory('Pakistan'),
    staleTime: Infinity,
  })

  // Provider map — maps station_id/name/name+city to network
  const { data: providerMap } = useQuery<{ by_station_id: Record<string, string>; by_name: Record<string, string>; by_name_city?: Record<string, string> }>({
    queryKey: ['station-providers'],
    queryFn: () => fetch('/station-providers.json?v=3').then(r => r.json()),
    staleTime: Infinity,
  })

  // Build lookup: "name|city" → station_id
  const stationIdLookup = useMemo(() => {
    const map = new Map<string, string>()
    if (!stationDirectory) return map
    for (const s of stationDirectory) {
      map.set(`${s.name}|${s.city}`, s.station_id)
    }
    return map
  }, [stationDirectory])

  // Enrich daily stations with station_ids + network from directory
  const enrichedStations = useMemo(() => {
    return (stationData?.stations ?? [])
      .map(s => {
        const sid = s.station_id?.trim() || stationIdLookup.get(`${s.name}|${s.city}`)
        return {
          name: s.name,
          city: s.city,
          pm25: s.pm25,
          lat: s.lat ?? s.latitude,
          lon: s.lon ?? s.longitude,
          station_id: sid ?? undefined,
          network: providerMap?.by_name_city?.[`${s.name}|${s.city}`] || (sid && providerMap?.by_station_id?.[sid]) || providerMap?.by_name?.[s.name] || undefined,
        }
      })
      .filter(s => s.pm25 != null)
  }, [stationData, stationIdLookup, providerMap])

  // Only days whose Pakistan calendar day has ended (station daily aggregation can exist).
  // The API says which (details[].complete); fall back to the PKT date, never the browser's UTC date.
  const dates = useMemo(() => {
    const details = tileDates?.details
    if (details?.length) return details.filter(d => d.complete).map(d => d.date)
    const today = pktToday()
    return (tileDates?.dates || []).filter((d: string) => d < today)
  }, [tileDates])
  const currentIndex = selectedPredDate ? dates.indexOf(selectedPredDate) : -1

  useEffect(() => {
    if (dates.length > 0 && !selectedPredDate) {
      setSelectedPredDate(dates[dates.length - 1])
    }
  }, [dates, selectedPredDate])

  // Mirror the page's choices into the shared selection (map, cards, chat all read it)
  useEffect(() => {
    selection.setDate(selectedPredDate, !!selectedPredDate && selectedPredDate === dates[dates.length - 1])
  }, [selectedPredDate, dates]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { selection.setModel(model) }, [model]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    selection.setLayer('kilns', showKilns); selection.setLayer('industry', showIndustry); selection.setLayer('fires', showFires)
  }, [showKilns, showIndustry, showFires]) // eslint-disable-line react-hooks/exhaustive-deps

  const formatDisplayDate = (dateStr: string) => formatDateOnly(dateStr)

  if (tileDatesLoading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-slate-50">
        <div className="flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-slate-800/90 text-white text-sm font-medium shadow-lg">
          <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          Loading predictions...
        </div>
      </div>
    )
  }

  if (dates.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center bg-slate-50">
        <div className="text-center text-gray-500">
          <Calendar className="w-6 h-6 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No predictions available</p>
        </div>
      </div>
    )
  }

  if (!selectedPredDate) return null

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* Icon rail */}
      <IconRail
        activeTab={railTab}
        onTabChange={setRailTab}
        isStreaming={isStreaming}
        tabs={['chat', 'analytics', 'stations', 'sources', 'fires']}
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
        {/* Chat / Analytics panel */}
        <div style={{
          display: railTab === 'chat' || railTab === 'analytics' ? 'flex' : 'none',
          flexDirection: 'column',
          height: '100%',
        }}>
          <CopilotChat
            selectedDate={selectedPredDate}
            trackerMode={true}
            onStreamingChange={setIsStreaming}
            activeTab={railTab === 'analytics' ? 'analytics' : 'chat'}
          />
        </div>

        {/* Stations panel */}
        <div style={{ display: railTab === 'stations' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <StructuresTab
            stations={enrichedStations}
            kilns={[]}
            industryCategories={[]}
            selectedDate={selectedPredDate}
            onFlyTo={(lng, lat, zoom) => flyTo?.(lng, lat, zoom)}
            initialView="stations"
          />
        </div>

        {/* Sources panel */}
        <div style={{ display: railTab === 'sources' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <StructuresTab
            stations={[]}
            kilns={kilnsData}
            industryCategories={industryData}
            selectedDate={selectedPredDate}
            onFlyTo={(lng, lat, zoom) => flyTo?.(lng, lat, zoom)}
            initialView="sources"
          />
        </div>

        {/* Fires panel */}
        <div style={{ display: railTab === 'fires' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <FiresPanel
            firesData={firesGeoJSON ?? null}
            onFlyTo={(lng, lat, zoom) => flyTo?.(lng, lat, zoom)}
            selectedDate={selectedPredDate}
            isLoading={firesLoading}
            isFetching={firesFetching}
            isError={firesError}
            errorMessage={firesErrorObj instanceof Error ? firesErrorObj.message : null}
          />
        </div>

      </div>

      {/* Map — fills remaining space */}
      <div ref={mapWrapperRef} className="flex-1 relative min-h-0 flex flex-col">
        <MapErrorBoundary
          unavailable={mapUnavailable}
          onRetry={retryMap}
          fallback={({ message, retry }) => (
            <MapUnavailableNotice message={message} retry={retry}>
              <div className="h-full rounded-xl border bg-white overflow-hidden">
                <StructuresTab
                  stations={enrichedStations}
                  kilns={[]}
                  industryCategories={[]}
                  selectedDate={selectedPredDate}
                  onFlyTo={() => {}}
                  initialView="stations"
                />
              </div>
            </MapUnavailableNotice>
          )}
        >
          <PredictionMap
            key={mapKey}
            selectedDate={selectedPredDate}
            smoothed={true}
            model={model}
            showKilns={showKilns}
            showIndustry={showIndustry}
            showFires={showFires}
            firesData={firesGeoJSON ?? null}
            stations={stationData?.stations ?? []}
            onMapUnavailable={setMapUnavailable}
            onMapReady={(fn) => setFlyTo(() => fn)}
          />
        </MapErrorBoundary>

        {/* Floating assessment card — upper right (Gaza CausePanel pattern) */}
        <OpsContextPanel
          selectedDate={selectedPredDate}
          model={model}
          onModelChange={setModel}
          stations={stationData?.stations ?? []}
          predictionStats={predictionData?.stats ?? null}
          runReport={runReport ?? null}
        />

        {/* Timeline bar — slim, floating at bottom of map */}
        <div className="absolute bottom-3 left-4 right-4 z-10 flex items-center gap-3">
          <button
            onClick={() => { if (currentIndex > 0) setSelectedPredDate(dates[currentIndex - 1]) }}
            disabled={currentIndex <= 0}
            className="p-1.5 rounded-full bg-slate-800/80 hover:bg-slate-700/80 disabled:opacity-30 transition-colors"
          >
            <ChevronLeft className="w-4 h-4 text-white" />
          </button>

          <div className="text-center min-w-[110px] text-sm font-semibold text-slate-800 bg-white/90 backdrop-blur-sm rounded-full px-3 py-1 shadow-sm">
            {formatDisplayDate(selectedPredDate)}
          </div>

          <button
            onClick={() => { if (currentIndex < dates.length - 1) setSelectedPredDate(dates[currentIndex + 1]) }}
            disabled={currentIndex >= dates.length - 1}
            className="p-1.5 rounded-full bg-slate-800/80 hover:bg-slate-700/80 disabled:opacity-30 transition-colors"
          >
            <ChevronRight className="w-4 h-4 text-white" />
          </button>

          <div className="flex-1 relative flex items-center h-6">
            <div className="absolute left-0 right-0 h-[5px] rounded-full bg-slate-300/60" />
            <div
              className="absolute left-0 h-[5px] rounded-full bg-slate-700"
              style={{ width: dates.length > 1 ? `${(currentIndex / (dates.length - 1)) * 100}%` : '0%' }}
            />
            <input
              type="range"
              min={0}
              max={dates.length - 1}
              value={currentIndex >= 0 ? currentIndex : 0}
              onChange={(e) => {
                const idx = parseInt(e.target.value, 10)
                if (dates[idx]) setSelectedPredDate(dates[idx])
              }}
              className="relative z-10 w-full h-[5px] appearance-none cursor-pointer bg-transparent
                [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5
                [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-400
                [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:cursor-grab
                [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-white"
            />
          </div>
        </div>
      </div>

    </div>
  )
}
