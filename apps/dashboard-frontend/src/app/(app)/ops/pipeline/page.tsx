"use client"

import { useState, useEffect, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Calendar } from 'lucide-react'

import { fetchTileDates, fetchStationDaily, fetchPredictionData, fetchRunReport, fetchStationDirectory } from '@/components/ops-pipeline'
import { PredictionMap } from '@/components/ops-pipeline/PredictionMap'
import { OpsContextPanel } from '@/components/ops-pipeline/ContextPanel'
import { StructuresTab } from '@/components/ops-pipeline/StructuresTab'
import { IconRail, type RailTab } from '@/components/analyst-desk/IconRail'
import { CopilotChat } from '@/components/analyst-desk/CopilotChat'

export default function OpsPipelinePage() {
  const [selectedPredDate, setSelectedPredDate] = useState<string | null>(null)
  const [model, setModel] = useState<'backbone' | 'support_aware'>('backbone')

  // Side channel state
  const [railTab, setRailTab] = useState<RailTab | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)

  // Layer toggles
  const [showKilns, setShowKilns] = useState(true)
  const [showIndustry, setShowIndustry] = useState(false)

  // Map flyTo callback + static data
  const [flyTo, setFlyTo] = useState<((lng: number, lat: number, zoom?: number) => void) | null>(null)
  const [kilnsData, setKilnsData] = useState<any[]>([])
  const [industryData, setIndustryData] = useState<any[]>([])

  // Load static GeoJSON data for structures tab
  useEffect(() => {
    fetch('/brick_kilns.geojson')
      .then(r => r.json())
      .then(data => {
        setKilnsData(data.features.map((f: any) => ({
          ...f.properties,
          lat: f.geometry.coordinates[1],
          lon: f.geometry.coordinates[0],
        })))
      })
      .catch(() => {})

    fetch('/emission_sources.json')
      .then(r => r.json())
      .then(data => {
        const CATS = [
          { key: 'power_plants', color: '#ef4444', label: 'Power Plants' },
          { key: 'cement_plants', color: '#8b5cf6', label: 'Cement Plants' },
          { key: 'steel_sites', color: '#6366f1', label: 'Steel Sites' },
          { key: 'sugar_mills', color: '#10b981', label: 'Sugar Mills' },
          { key: 'industrial_sites', color: '#64748b', label: 'Industrial Sites' },
          { key: 'mines_quarries', color: '#78716c', label: 'Mines & Quarries' },
        ]
        setIndustryData(CATS.filter(c => data[c.key]?.features?.length).map(c => ({
          ...c,
          items: data[c.key].features.map((f: any) => ({
            ...f.properties,
            lat: f.geometry.coordinates[1],
            lon: f.geometry.coordinates[0],
          })),
        })))
      })
      .catch(() => {})
  }, [])

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

  const { data: tileDates, isLoading: tileDatesLoading } = useQuery({
    queryKey: ["ops-pipeline-tile-dates"],
    queryFn: () => fetchTileDates(365),
  })

  const { data: stationData } = useQuery({
    queryKey: ['ops-station-daily', selectedPredDate],
    queryFn: () => fetchStationDaily(selectedPredDate!, 'Pakistan'),
    enabled: !!selectedPredDate,
  })

  const { data: predictionData } = useQuery({
    queryKey: ['ops-prediction-data', selectedPredDate],
    queryFn: () => fetchPredictionData(selectedPredDate!),
    enabled: !!selectedPredDate,
  })

  const { data: runReport } = useQuery({
    queryKey: ['ops-run-report', selectedPredDate],
    queryFn: () => fetchRunReport(selectedPredDate!),
    enabled: !!selectedPredDate,
  })

  // Station directory — fetch once, used to resolve station_ids for navigation
  const { data: stationDirectory } = useQuery({
    queryKey: ['station-directory-pk'],
    queryFn: () => fetchStationDirectory('Pakistan'),
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

  // Enrich daily stations with station_ids from directory
  const enrichedStations = useMemo(() => {
    return (stationData?.stations ?? [])
      .map((s: any) => ({
        name: s.name,
        city: s.city,
        pm25: s.pm25,
        lat: s.lat ?? s.latitude,
        lon: s.lon ?? s.longitude,
        station_id: stationIdLookup.get(`${s.name}|${s.city}`) ?? undefined,
      }))
      .filter((s: any) => s.pm25 != null)
  }, [stationData, stationIdLookup])

  const dates = tileDates?.dates || []
  const currentIndex = selectedPredDate ? dates.indexOf(selectedPredDate) : -1

  useEffect(() => {
    if (dates.length > 0 && !selectedPredDate) {
      setSelectedPredDate(dates[dates.length - 1])
    }
  }, [dates, selectedPredDate])

  const formatDisplayDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

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
            onStreamingChange={setIsStreaming}
            activeTab={railTab === 'analytics' ? 'analytics' : 'chat'}
          />
        </div>

        {/* Structures panel */}
        <div style={{ display: railTab === 'structures' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <StructuresTab
            stations={enrichedStations}
            kilns={kilnsData}
            industryCategories={industryData}
            selectedDate={selectedPredDate}
            onFlyTo={(lng, lat, zoom) => flyTo?.(lng, lat, zoom)}
          />
        </div>

        {/* Layers panel — model selector for prediction map */}
        <div style={{ display: railTab === 'layers' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <div className="flex flex-col h-full">
            <div className="px-4 py-3 border-b border-slate-100">
              <h3 className="text-xs font-semibold text-slate-800 uppercase tracking-wide">
                Model Layers
              </h3>
            </div>
            <div className="flex-1 overflow-y-auto p-3 space-y-1">
              <button
                onClick={() => setModel('backbone')}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${
                  model === 'backbone'
                    ? 'bg-slate-50 hover:bg-slate-100'
                    : 'bg-white hover:bg-slate-50 opacity-50'
                }`}
              >
                <div className={`shrink-0 ${model === 'backbone' ? 'text-slate-700' : 'text-slate-300'}`}>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m8.66-13.66l-.71.71M4.05 19.95l-.71.71M21 12h-1M4 12H3m16.66 7.66l-.71-.71M4.05 4.05l-.71-.71" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <div className={`text-xs font-medium ${model === 'backbone' ? 'text-slate-700' : 'text-slate-400'}`}>
                    Satellite
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">
                    Backbone model (AOD + meteorology)
                  </div>
                </div>
                <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${
                  model === 'backbone' ? 'bg-slate-700 justify-end' : 'bg-slate-200 justify-start'
                }`}>
                  <div className={`w-3 h-3 rounded-full mx-0.5 transition-colors ${
                    model === 'backbone' ? 'bg-white' : 'bg-slate-400'
                  }`} />
                </div>
              </button>

              <button
                onClick={() => setModel('support_aware')}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${
                  model === 'support_aware'
                    ? 'bg-slate-50 hover:bg-slate-100'
                    : 'bg-white hover:bg-slate-50 opacity-50'
                }`}
              >
                <div className={`shrink-0 ${model === 'support_aware' ? 'text-emerald-600' : 'text-slate-300'}`}>
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <div className={`text-xs font-medium ${model === 'support_aware' ? 'text-slate-700' : 'text-slate-400'}`}>
                    Enhanced
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">
                    Station-aware with ground truth blending
                  </div>
                </div>
                <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${
                  model === 'support_aware' ? 'bg-emerald-600 justify-end' : 'bg-slate-200 justify-start'
                }`}>
                  <div className={`w-3 h-3 rounded-full mx-0.5 transition-colors ${
                    model === 'support_aware' ? 'bg-white' : 'bg-slate-400'
                  }`} />
                </div>
              </button>

              {/* Divider */}
              <div className="border-t border-slate-100 my-2" />

              {/* Brick Kilns toggle */}
              <button
                onClick={() => setShowKilns(v => !v)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${
                  showKilns
                    ? 'bg-slate-50 hover:bg-slate-100'
                    : 'bg-white hover:bg-slate-50 opacity-50'
                }`}
              >
                <div className={`shrink-0 ${showKilns ? 'text-amber-600' : 'text-slate-300'}`}>
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0H5m14 0h2M5 21H3m4-10h2m4 0h2m-6 4h2m4 0h2" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <div className={`text-xs font-medium ${showKilns ? 'text-slate-700' : 'text-slate-400'}`}>
                    Brick Kilns
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">
                    10,585 geolocated kilns with emissions
                  </div>
                </div>
                <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${
                  showKilns ? 'bg-amber-600 justify-end' : 'bg-slate-200 justify-start'
                }`}>
                  <div className={`w-3 h-3 rounded-full mx-0.5 transition-colors ${
                    showKilns ? 'bg-white' : 'bg-slate-400'
                  }`} />
                </div>
              </button>

              {/* Industry toggle */}
              <button
                onClick={() => setShowIndustry(v => !v)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-left ${
                  showIndustry
                    ? 'bg-slate-50 hover:bg-slate-100'
                    : 'bg-white hover:bg-slate-50 opacity-50'
                }`}
              >
                <div className={`shrink-0 ${showIndustry ? 'text-red-500' : 'text-slate-300'}`}>
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <div className={`text-xs font-medium ${showIndustry ? 'text-slate-700' : 'text-slate-400'}`}>
                    Industry & Power
                  </div>
                  <div className="text-[10px] text-slate-400 truncate">
                    Power plants, cement, steel, sugar, mines
                  </div>
                </div>
                <div className={`w-8 h-4 rounded-full transition-colors flex items-center ${
                  showIndustry ? 'bg-red-500 justify-end' : 'bg-slate-200 justify-start'
                }`}>
                  <div className={`w-3 h-3 rounded-full mx-0.5 transition-colors ${
                    showIndustry ? 'bg-white' : 'bg-slate-400'
                  }`} />
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Map — fills remaining space */}
      <div ref={mapWrapperRef} className="flex-1 relative min-h-0">
        <PredictionMap selectedDate={selectedPredDate} smoothed={true} model={model} showKilns={showKilns} showIndustry={showIndustry} onMapReady={(fn) => setFlyTo(() => fn)} />

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
