"use client"

import { useState, useEffect, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { m, useDragControls } from 'motion/react'
import { useIsMobile } from '@/lib/useMediaQuery'
import { haversineKm } from '@/lib/geo'
import { ChevronLeft, ChevronRight, Calendar, LocateFixed } from 'lucide-react'

import { fetchTileDates, fetchStationDaily, fetchPredictionData, fetchRunReport, fetchStationDirectory } from '@/components/ops-pipeline'
import { PredictionMap, type MapFeatureClick } from '@/components/ops-pipeline/PredictionMap'
import { OpsContextPanel } from '@/components/ops-pipeline/ContextPanel'
import { DatePicker } from '@/components/ops-pipeline/DatePicker'
import { StructuresTab, type IndustryCategory, type IndustryItem, type KilnItem, type StructuresFocus } from '@/components/ops-pipeline/StructuresTab'
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
  const isMobile = useIsMobile()
  const sheetDrag = useDragControls()
  // Item a map click opened in the Stations or Sources panel
  const [mapFocus, setMapFocus] = useState<StructuresFocus | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)

  // Layer toggles
  const [showKilns, setShowKilns] = useState(false)
  const [showIndustry, setShowIndustry] = useState(false)
  const [showFires, setShowFires] = useState(false)

  // Map flyTo callback + static data
  const [flyTo, setFlyTo] = useState<((lng: number, lat: number, zoom?: number) => Promise<void>) | null>(null)
  const [kilnsData, setKilnsData] = useState<KilnItem[]>([])
  const [industryData, setIndustryData] = useState<IndustryCategory[]>([])

  // Static inventories for the Sources panel: same cached loads the map uses (parsed once).
  // Low priority: fetched the first time the panel is opened, not on page load.
  const sourcesWanted = railTab === 'sources'
  // Kilns and industry are shown on the map only while the Sources panel is open
  useEffect(() => {
    setShowKilns(railTab === 'sources')
    setShowIndustry(railTab === 'sources')
  }, [railTab])
  useEffect(() => {
    if (!sourcesWanted) return
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
  }, [sourcesWanted])

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

  // Tell mapbox about container changes only when the size actually changes
  const mapWrapperRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = mapWrapperRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let raf = 0
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => window.dispatchEvent(new Event('resize')))
    })
    ro.observe(el)
    return () => { ro.disconnect(); cancelAnimationFrame(raf) }
  }, [])

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
  const { data: firesGeoJSON } = useQuery({
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

  // ── Where the visitor is: inside Pakistan, fly there and show the nearest monitor ──
  const NEARBY_RADIUS_KM = 50
  const [userLoc, setUserLoc] = useState<{ lng: number; lat: number } | null>(null)
  const [locNote, setLocNote] = useState<string | null>(null)
  const [locating, setLocating] = useState(false)

  const nearby = useMemo(() => {
    if (!userLoc) return null
    let best: { s: (typeof enrichedStations)[number]; d: number } | null = null
    for (const s of enrichedStations) {
      if (s.lat == null || s.lon == null) continue
      const d = haversineKm(userLoc.lat, userLoc.lng, s.lat, s.lon)
      if (!best || d < best.d) best = { s, d }
    }
    return best && best.d <= NEARBY_RADIUS_KM
      ? { station: { name: best.s.name, city: best.s.city, pm25: best.s.pm25 }, distKm: best.d, radiusKm: NEARBY_RADIUS_KM }
      : { station: null, distKm: null, radiusKm: NEARBY_RADIUS_KM }
  }, [userLoc, enrichedStations])

  const locate = () => {
    if (!navigator.geolocation) { setLocNote('Location is not available in this browser.'); return }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        setLocating(false)
        const { latitude: lat, longitude: lng } = pos.coords
        await loadPakBoundary()
        if (!isInsidePakistan(lng, lat)) { setLocNote('You appear to be outside Pakistan, so there is no air quality to show here.'); return }
        await flyTo?.(lng, lat, 10.5) // let the fly-in finish before the card and puck appear
        setUserLoc({ lng, lat })
      },
      (err) => { setLocating(false); setLocNote(err.code === 1 ? 'Location permission was declined.' : 'Could not find your location.') },
      { timeout: 10000, maximumAge: 5 * 60 * 1000 },
    )
  }

  // Ask once per visit, as soon as the map and stations are ready
  const askedRef = useRef(false)
  useEffect(() => {
    if (askedRef.current || !flyTo || enrichedStations.length === 0) return
    askedRef.current = true
    try { if (sessionStorage.getItem('paqi-located')) return; sessionStorage.setItem('paqi-located', '1') } catch { /* storage unavailable */ }
    locate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyTo, enrichedStations.length])

  useEffect(() => {
    if (!locNote) return
    const t = setTimeout(() => setLocNote(null), 6000)
    return () => clearTimeout(t)
  }, [locNote])

  // A click on a map station, kiln or industrial site opens it in the sidebar
  const openFromMap = (f: MapFeatureClick) => {
    if (f.kind === 'station') {
      const s = f.station
      const station = enrichedStations.find(e => e.name === s.name && e.city === s.city)
        ?? { name: s.name, city: s.city, pm25: s.pm25, lat: s.lat ?? s.latitude, lon: s.lon ?? s.longitude, station_id: s.station_id }
      setMapFocus({ type: 'station-detail', station })
      setRailTab('stations')
    } else if (f.kind === 'kiln') {
      const kiln = kilnsData.find(k => String(k.id) === f.id)
      if (!kiln) return
      setMapFocus({ type: 'kiln-detail', kiln })
      setRailTab('sources')
    } else {
      // Rendered-feature coordinates are tile-quantised: match by name, then take the nearest
      const items = industryData.find(c => c.key === f.categoryKey)?.items ?? []
      const named = f.name ? items.filter(i => i.name === f.name) : []
      const pool = named.length ? named : items
      let item: IndustryItem | undefined
      let best = Infinity
      for (const i of pool) {
        const d = (i.lon - f.lng) ** 2 + (i.lat - f.lat) ** 2
        if (d < best) { best = d; item = i }
      }
      if (!item) return
      setMapFocus({ type: 'industry-detail', item, categoryKey: f.categoryKey })
      setRailTab('sources')
    }
  }

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
    <div className="relative flex flex-1 min-h-0 overflow-hidden max-md:flex-col-reverse">
      {/* Icon rail (bottom bar on phones) */}
      <IconRail
        activeTab={railTab}
        onTabChange={setRailTab}
        isStreaming={isStreaming}
        tabs={['chat', 'analytics', 'sources']}
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
            focus={mapFocus?.type === 'station-detail' ? mapFocus : null}
            onClose={() => setRailTab(null)}
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
            focus={mapFocus && mapFocus.type !== 'station-detail' ? mapFocus : null}
          />
        </div>

        </div>
      </m.div>

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
            userLocation={userLoc}
            onMapReady={(fn) => setFlyTo(() => fn)}
            onFeatureClick={openFromMap}
          />
        </MapErrorBoundary>

        {/* Floating assessment card — upper right (Gaza CausePanel pattern) */}
        <OpsContextPanel
          onFlyTo={(lng, lat, zoom) => flyTo?.(lng, lat, zoom)}
          nearby={nearby}
          selectedDate={selectedPredDate}
          model={model}
          onModelChange={setModel}
          stations={stationData?.stations ?? []}
          predictionStats={predictionData?.stats ?? null}
          runReport={runReport ?? null}
        />

        {/* Find me */}
        <button
          onClick={locate}
          disabled={locating}
          aria-label="Show air quality where I am"
          className="absolute bottom-[152px] right-3 md:bottom-[124px] md:right-4 z-10 flex h-11 w-11 items-center justify-center rounded-full text-slate-800 transition-colors hover:text-slate-950 disabled:opacity-60"
          style={{
            background: 'rgba(255,255,255,0.82)',
            backdropFilter: 'blur(20px) saturate(180%)',
            WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            border: '1px solid rgba(15,23,42,0.08)',
            boxShadow: '0 8px 32px rgba(15,23,42,0.14)',
          }}
        >
          <LocateFixed size={20} className={locating ? 'animate-pulse' : ''} />
        </button>
        {locNote && (
          <div
            role="status"
            className="absolute bottom-[152px] right-16 md:bottom-[128px] md:right-[68px] z-10 max-w-[260px] rounded-xl bg-slate-900 px-3 py-2 text-xs text-white shadow-lg"
          >
            {locNote}
          </div>
        )}

        {/* Fires layer switch */}
        <label
          className="absolute bottom-[104px] right-3 md:bottom-[76px] md:right-4 z-10 flex cursor-pointer items-center gap-2.5 rounded-full py-1.5 pl-3.5 pr-2 text-[13px] font-medium text-slate-900"
          style={{
            background: 'rgba(255,255,255,0.82)',
            backdropFilter: 'blur(20px) saturate(180%)',
            WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            border: '1px solid rgba(15,23,42,0.08)',
            boxShadow: '0 8px 32px rgba(15,23,42,0.14)',
          }}
        >
          Fires
          <button
            role="switch"
            aria-checked={showFires}
            aria-label="Show satellite fire detections"
            onClick={() => setShowFires(v => !v)}
            className={`relative h-6 w-10 rounded-full transition-colors ${showFires ? 'bg-slate-900' : 'bg-slate-300'}`}
          >
            <m.span
              className="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-sm"
              animate={{ left: showFires ? 18 : 2 }}
              transition={{ type: 'spring', stiffness: 500, damping: 34 }}
            />
          </button>
        </label>

        {/* Timeline — one glass pill floating at the bottom of the map */}
        <div
          className="absolute bottom-12 left-3 right-3 md:bottom-4 md:left-4 md:right-4 z-10 flex items-center gap-2 rounded-full px-2 py-1.5"
          style={{
            background: 'rgba(255,255,255,0.82)',
            backdropFilter: 'blur(20px) saturate(180%)',
            WebkitBackdropFilter: 'blur(20px) saturate(180%)',
            border: '1px solid rgba(15,23,42,0.08)',
            boxShadow: '0 8px 32px rgba(15,23,42,0.14)',
          }}
          role="group"
          aria-label="Date"
        >
          <button
            onClick={() => { if (currentIndex > 0) setSelectedPredDate(dates[currentIndex - 1]) }}
            disabled={currentIndex <= 0}
            aria-label="Previous day"
            className="h-8 w-8 shrink-0 flex items-center justify-center rounded-full text-slate-700 hover:bg-slate-900/[0.06] disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>

          <DatePicker
            dates={dates}
            value={selectedPredDate}
            onChange={setSelectedPredDate}
            label={formatDisplayDate(selectedPredDate)}
          />

          <button
            onClick={() => { if (currentIndex < dates.length - 1) setSelectedPredDate(dates[currentIndex + 1]) }}
            disabled={currentIndex >= dates.length - 1}
            aria-label="Next day"
            className="h-8 w-8 shrink-0 flex items-center justify-center rounded-full text-slate-700 hover:bg-slate-900/[0.06] disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <ChevronRight className="w-4 h-4" />
          </button>

          <div className="flex-1 relative flex items-center h-6 mx-1 max-md:hidden">
            <div className="absolute left-0 right-0 h-1 rounded-full bg-slate-300/70" />
            <div
              className="absolute left-0 h-1 rounded-full bg-slate-800"
              style={{ width: dates.length > 1 ? `${(Math.max(currentIndex, 0) / (dates.length - 1)) * 100}%` : '0%' }}
            />
            <input
              type="range"
              aria-label="Select date"
              aria-valuetext={formatDisplayDate(selectedPredDate)}
              min={0}
              max={dates.length - 1}
              value={currentIndex >= 0 ? currentIndex : 0}
              onChange={(e) => {
                const idx = parseInt(e.target.value, 10)
                if (dates[idx]) setSelectedPredDate(dates[idx])
              }}
              className="relative z-10 w-full h-1 appearance-none cursor-pointer bg-transparent
 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5
                [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white
                [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-grab
                [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-slate-300"
            />
          </div>
        </div>
      </div>

    </div>
  )
}
