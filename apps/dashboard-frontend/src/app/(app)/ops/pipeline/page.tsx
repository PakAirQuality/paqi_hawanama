"use client"

import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { m, useDragControls } from 'motion/react'
import { useIsMobile } from '@/lib/useMediaQuery'
import { haversineKm } from '@/lib/geo'
import { ChevronLeft, ChevronRight, Calendar, LocateFixed, X } from 'lucide-react'

import { fetchTileDates, fetchStationDaily, fetchPredictionData, fetchRunReport, fetchStationDirectory } from '@/components/ops-pipeline'
import { PredictionMap, type MapFeatureClick } from '@/components/ops-pipeline/PredictionMap'
import { OpsContextPanel } from '@/components/ops-pipeline/ContextPanel'
import { DatePicker } from '@/components/ops-pipeline/DatePicker'
import { StructuresTab, type IndustryCategory, type IndustryItem, type KilnItem, type StructuresFocus } from '@/components/ops-pipeline/StructuresTab'
import { IconRail, type RailTab } from '@/components/analyst-desk/IconRail'
import { CopilotChat } from '@/components/analyst-desk/CopilotChat'
import type { CopilotAction } from '@/components/analyst-desk/types'
import { LayersPanel } from '@/components/analyst-desk/LayersPanel'
import { fetchAvailableDates, fetchCurrentStations, fetchFires, fetchForecast, fetchNowcast } from '@/components/analyst-desk/api'
import { bandKey } from '@/lib/aqi'
import { cityCentre } from '@/lib/chat/actions'
import { firesShortLabel, firesStatus } from '@/lib/fires'
import { availableHours, availableLeads, daysBetween, forecastReadings, hourStep, isForecastLead, isHourStep, latestReading, leadForDaysAhead, liveReadings, nowcastAgeMin, nowcastReadings, nowcastValidTime, parseViewParam, rampCount, sameStep, stepKey, targetDate, type ForecastLead, type FutureStep, type TimelineStep } from '@/lib/timeline'
import { loadPakBoundary, isInsidePakistan } from '@/components/analyst-desk/pakistan'
import { useSelection } from '@/lib/selection'
import { formatDateOnly, formatPkt, pktToday } from '@/lib/time'
import type { StationReading } from '@/components/ops-pipeline/types'
import { INDUSTRY_CATEGORIES, loadEmissionSources, loadKilnsGeoJSON } from '@/lib/staticLayers'

const ALL_INDUSTRY = INDUSTRY_CATEGORIES.map(c => c.key as string)
// Emission sources the Layers panel switches, in the Sources panel's order
const SOURCE_LAYERS = [{ key: 'kilns', label: 'Brick Kilns', color: '#d97706' }, ...INDUSTRY_CATEGORIES]
import { MapErrorBoundary, MapUnavailableNotice } from '@/components/MapErrorBoundary'
import type { MapUnavailableReason } from '@/lib/webgl'

export default function OpsPipelinePage() {
  const selection = useSelection()
  // The newest finished day unless a past day is chosen: its satellite surface sits under today's readings
  const [selectedPredDate, setSelectedPredDate] = useState<string | null>(null)
  // Today or a forecast day; null means a past day
  const [futureStep, setFutureStep] = useState<FutureStep | null>('now')
  // Days ahead asked for by a shared link, until the forecast it needs has loaded
  const [linkedDaysAhead, setLinkedDaysAhead] = useState<number | null>(null)
  const [model, setModel] = useState<'backbone' | 'support_aware'>('backbone')
  const [networkFilter, setNetworkFilter] = useState<string | null>(null)

  // Side channel state
  const [railTab, setRailTab] = useState<RailTab | null>(null)
  const isMobile = useIsMobile()
  const sheetDrag = useDragControls()
  // Item a map click opened in the Stations or Sources panel
  const [mapFocus, setMapFocus] = useState<StructuresFocus | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)

  // Layer toggles
  const [showKilns, setShowKilns] = useState(false)
  // Industry categories on the map, by key (power_plants, cement_plants, ...)
  const [industryKeys, setIndustryKeys] = useState<string[]>([])
  const showIndustry = industryKeys.length > 0
  const [showFires, setShowFires] = useState(false)
  const [showStations, setShowStations] = useState(true)
  const [showSurface, setShowSurface] = useState(true)
  const [showWind, setShowWind] = useState(false)
  const [showPopulation, setShowPopulation] = useState(false)

  // Map flyTo callback + static data
  const [flyTo, setFlyTo] = useState<((lng: number, lat: number, zoom?: number) => Promise<void>) | null>(null)
  // ?focus=lat,lon[,zoom] from a shared link (the Fire trends page): fly once the map is ready
  const [linkedFocus, setLinkedFocus] = useState<{ lat: number; lon: number; zoom: number } | null>(null)
  useEffect(() => {
    if (!flyTo || !linkedFocus) return
    flyTo(linkedFocus.lon, linkedFocus.lat, linkedFocus.zoom)
    setLinkedFocus(null)
  }, [flyTo, linkedFocus])
  const [kilnsData, setKilnsData] = useState<KilnItem[]>([])
  const [industryData, setIndustryData] = useState<IndustryCategory[]>([])

  // Static inventories for the Sources panel: same cached loads the map uses (parsed once).
  // Low priority: fetched the first time the panel is opened, not on page load.
  const sourcesWanted = railTab === 'sources'
  // Opening the Sources panel puts kilns and industry on the map; they stay until switched off in Layers
  useEffect(() => {
    if (railTab !== 'sources') return
    setShowKilns(true)
    setIndustryKeys(ALL_INDUSTRY)
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

  // Shareable URLs: ?date=YYYY-MM-DD or ?view=today|h3|h6|h12|h24|1|2|3, &model=support_aware&layers=kilns,industry,fires
  const urlApplied = useRef(false)
  useEffect(() => {
    if (urlApplied.current || typeof window === 'undefined') return
    urlApplied.current = true
    const q = new URLSearchParams(window.location.search)
    const d = q.get('date')
    if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) { setSelectedPredDate(d); setFutureStep(null) }
    const view = parseViewParam(q.get('view'))
    if (view?.daysAhead) setLinkedDaysAhead(view.daysAhead)
    else if (view?.hour) setFutureStep(hourStep(view.hour))
    const m = q.get('model'); if (m === 'support_aware' || m === 'backbone') setModel(m)
    const focus = q.get('focus')
    if (focus) {
      const [la, lo, z] = focus.split(',').map(Number)
      if (Number.isFinite(la) && Number.isFinite(lo)) setLinkedFocus({ lat: la, lon: lo, zoom: Number.isFinite(z) ? z : 9 })
    }
    const layers = q.get('layers')
    if (layers != null) {
      const on = new Set(layers.split(',').filter(Boolean))
      setShowKilns(on.has('kilns')); setShowFires(on.has('fires'))
      // "industry" (older links) means every category
      setIndustryKeys(on.has('industry') ? ALL_INDUSTRY : ALL_INDUSTRY.filter(k => on.has(k)))
      setShowWind(on.has('wind')); setShowPopulation(on.has('population'))
    }
  }, [])

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
    enabled: !!selectedPredDate && futureStep === null,
  })

  const today = pktToday()

  // Latest hourly readings, for Today
  const { data: liveData, isError: liveFailed } = useQuery({
    queryKey: ['current-stations'],
    queryFn: fetchCurrentStations,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: 2,
  })

  // The newest forecast run, for the days ahead
  const { data: forecastDates } = useQuery({
    queryKey: ['forecast-dates'],
    queryFn: fetchAvailableDates,
    staleTime: 10 * 60 * 1000,
  })
  const forecastIssue = forecastDates?.dates?.[0] ?? null
  const { data: forecastData } = useQuery({
    queryKey: ['forecast', forecastIssue],
    queryFn: () => fetchForecast(forecastIssue as string),
    enabled: !!forecastIssue,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  })
  const forecasts = useMemo(() => forecastData?.forecasts ?? [], [forecastData])
  const daysAheadOf = (lead: ForecastLead) => {
    const date = targetDate(forecasts, lead)
    return date ? daysBetween(today, date) : lead
  }
  const leads = useMemo(() => availableLeads(forecasts, today), [forecasts, today])

  // The latest hourly nowcast (+3/+6/+12/+24 h), issued every 3 h; null until the first cycle is published
  const { data: nowcastData } = useQuery({
    queryKey: ['nowcast-latest'],
    queryFn: fetchNowcast,
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    retry: 1,
  })
  const hours = useMemo(() => availableHours(nowcastData, new Date().toISOString()), [nowcastData])
  const hourSteps = useMemo(() => hours.map(hourStep), [hours])
  useEffect(() => {
    if (linkedDaysAhead == null || !forecastData) return
    setLinkedDaysAhead(null)
    const lead = leadForDaysAhead(forecasts, today, linkedDaysAhead)
    if (lead) setFutureStep(lead)
  }, [linkedDaysAhead, forecastData, forecasts, today])
  useEffect(() => {
    if (!selectedPredDate || typeof window === 'undefined') return
    const q = new URLSearchParams()
    if (futureStep === null) q.set('date', selectedPredDate)
    else if (futureStep === 'now') q.set('view', 'today')
    else if (isHourStep(futureStep)) q.set('view', stepKey(futureStep))
    else q.set('view', String(daysAheadOf(futureStep)))
    if (model !== 'backbone') q.set('model', model)
    const industry = industryKeys.length === ALL_INDUSTRY.length ? ['industry'] : industryKeys
    const layers = [showKilns && 'kilns', ...industry, showFires && 'fires', showWind && 'wind', showPopulation && 'population'].filter(Boolean).join(',')
    q.set('layers', layers)
    window.history.replaceState(null, '', `${window.location.pathname}?${q}`)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPredDate, futureStep, forecastData, model, showKilns, industryKeys, showFires, showWind, showPopulation])

  // Never leave the page empty: fall back if today's readings fail or a forecast day is not available
  useEffect(() => { if (futureStep === 'now' && liveFailed) setFutureStep(null) }, [futureStep, liveFailed])
  useEffect(() => {
    if (isForecastLead(futureStep) && forecastData && !leads.includes(futureStep)) setFutureStep('now')
  }, [futureStep, forecastData, leads])
  useEffect(() => {
    if (isHourStep(futureStep) && nowcastData !== undefined && !hours.includes(futureStep.h)) setFutureStep('now')
  }, [futureStep, nowcastData, hours])

  const readings = useMemo<StationReading[]>(() => {
    if (futureStep === 'now') return liveReadings(liveData?.stations ?? [])
    if (isHourStep(futureStep)) return nowcastReadings(nowcastData, futureStep.h)
    if (isForecastLead(futureStep)) return forecastReadings(forecasts, futureStep)
    return stationData?.stations ?? []
  }, [futureStep, liveData, nowcastData, forecasts, stationData])

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

  // Satellite fire detections — fetched for the Pakistan day in view, filtered to Pakistan.
  // The response carries an explicit status (ok/empty/partial/stale/unavailable); the panel
  // shows it, so a stale or missing day is never disguised as "no fires".
  const fireDay = futureStep === null ? selectedPredDate : today
  const { data: firesGeoJSON } = useQuery({
    queryKey: ['ops-fires', fireDay],
    queryFn: async () => {
      await loadPakBoundary()
      const data = await fetchFires(fireDay as string)
      return {
        ...data,
        features: data.features.filter(f => {
          const [lng, lat] = f.geometry.coordinates
          return isInsidePakistan(lng, lat)
        }),
      }
    },
    enabled: !!fireDay,
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
    return readings
      .map(s => {
        const sid = s.station_id?.trim() || stationIdLookup.get(`${s.name}|${s.city}`)
        return {
          name: s.name,
          city: s.city,
          pm25: s.pm25,
          lat: s.lat ?? s.latitude,
          lon: s.lon ?? s.longitude,
          station_id: sid ?? undefined,
          valid_hours: s.valid_hours,
          network: providerMap?.by_name_city?.[`${s.name}|${s.city}`] || (sid && providerMap?.by_station_id?.[sid]) || providerMap?.by_name?.[s.name] || undefined,
        }
      })
      .filter(s => s.pm25 != null)
  }, [readings, stationIdLookup, providerMap])

  const shownStations = useMemo(() => {
    if (!networkFilter) return enrichedStations
    const wanted = networkFilter.toLowerCase()
    return enrichedStations.filter(s => s.network?.toLowerCase().includes(wanted))
  }, [enrichedStations, networkFilter])

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

  // The open station follows the day in view; one with no reading on that day closes
  const followedStation = mapFocus?.type === 'station-detail'
    ? enrichedStations.find(s => s.name === mapFocus.station.name && s.city === mapFocus.station.city)
    : undefined
  const stationFocus = useMemo(
    () => (mapFocus?.type === 'station-detail' && followedStation ? { ...mapFocus, station: followedStation } : null),
    [mapFocus, followedStation],
  )
  useEffect(() => {
    if (mapFocus?.type !== 'station-detail' || followedStation || !enrichedStations.length) return
    setMapFocus(null)
    setRailTab(tab => (tab === 'stations' ? null : tab))
  }, [mapFocus, followedStation, enrichedStations.length])

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

  // Stations for the Analytics charts and for recognising city names in chat answers
  const chatStations = useMemo(() => enrichedStations.map(s => ({
    pm25: s.pm25,
    band: bandKey(s.pm25 as number),
    city: s.city || '',
  })), [enrichedStations])

  const handleCopilotAction = useCallback((action: CopilotAction, fromClick: boolean) => {
    if (action.type === 'show_station_trend') {
      setRailTab('analytics')
      return
    }
    if (action.type === 'filter_network') {
      setNetworkFilter(action.network ?? null)
      return
    }
    if (action.type === 'set_horizon') {
      if (action.horizon === 0) { setFutureStep('now'); return }
      const lead = leadForDaysAhead(forecasts, today, action.horizon ?? 0)
      if (lead) setFutureStep(lead)
      return
    }
    let place: { lng: number; lat: number } | null = null
    if (action.type === 'zoom_to_city' && action.city) {
      place = cityCentre(enrichedStations, action.city)
    } else if (action.type === 'zoom_to_station') {
      const station = enrichedStations.find(s => s.station_id === action.station_id)
      const lng = action.lng ?? station?.lon
      const lat = action.lat ?? station?.lat
      if (lng != null && lat != null) place = { lng, lat }
    }
    if (!place) return
    flyTo?.(place.lng, place.lat, action.type === 'zoom_to_city' ? 10 : 12)
    // On phones the chat covers the map: close it when the person asked to see the place
    if (fromClick && isMobile) setRailTab(null)
  }, [enrichedStations, flyTo, isMobile, forecasts, today])

  // Only days whose Pakistan calendar day has ended (station daily aggregation can exist).
  // The API says which (details[].complete); fall back to the PKT date, never the browser's UTC date.
  const dates = useMemo(() => {
    const details = tileDates?.details
    if (details?.length) return details.filter(d => d.complete).map(d => d.date)
    const today = pktToday()
    return (tileDates?.dates || []).filter((d: string) => d < today)
  }, [tileDates, today])
  const currentIndex = selectedPredDate ? dates.indexOf(selectedPredDate) : -1

  // One timeline: past days, today, then the forecast days
  const steps = useMemo<TimelineStep[]>(() => [...dates, 'now', ...hourSteps, ...leads], [dates, hourSteps, leads])
  const stepIndex = steps.findIndex(s => sameStep(s, futureStep ?? selectedPredDate ?? ''))
  const goToStep = (step: TimelineStep | undefined) => {
    if (step === undefined) return
    if (step === 'now' || isForecastLead(step) || isHourStep(step)) { setFutureStep(step); return }
    setFutureStep(null)
    setSelectedPredDate(step)
  }

  // Today and forecast days sit on the newest finished day's surface and model data
  useEffect(() => {
    if (futureStep !== null && dates.length) setSelectedPredDate(dates[dates.length - 1])
  }, [futureStep, dates])

  useEffect(() => {
    if (dates.length > 0 && !selectedPredDate) {
      setSelectedPredDate(dates[dates.length - 1])
    }
  }, [dates, selectedPredDate])

  const viewDay = futureStep === null ? selectedPredDate
    : futureStep === 'now' || isHourStep(futureStep) ? today
    : targetDate(forecasts, futureStep)

  // Mirror the page's choices into the shared selection (map, cards, chat all read it)
  useEffect(() => {
    selection.setDate(viewDay, futureStep === 'now')
  }, [viewDay, futureStep]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { selection.setModel(model) }, [model]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    selection.setLayer('kilns', showKilns); selection.setLayer('industry', showIndustry); selection.setLayer('fires', showFires)
  }, [showKilns, showIndustry, showFires]) // eslint-disable-line react-hooks/exhaustive-deps

  const formatDisplayDate = (dateStr: string) => formatDateOnly(dateStr)

  // ── How the page words the day in view ──
  const mode = futureStep === null ? 'day' : futureStep === 'now' ? 'now' : isHourStep(futureStep) ? 'nowcast' : 'forecast'
  const hourAhead = isHourStep(futureStep) ? futureStep.h : null
  const nowcastValid = hourAhead ? nowcastValidTime(nowcastData, hourAhead) : null
  const longDay = (d: string | null) => d ? formatDateOnly(d, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) : ''
  const timelineLabel = mode === 'day' ? (selectedPredDate ? formatDisplayDate(selectedPredDate) : '')
    : mode === 'now' ? 'Today'
    : mode === 'nowcast' ? (nowcastValid ? formatPkt(nowcastValid) : `+${hourAhead} h`)
    : viewDay ? formatDateOnly(viewDay, { weekday: 'short', month: 'short', day: 'numeric' }) : ''
  const dayLabel = mode === 'now' ? `Today, ${longDay(today)}`
    : mode === 'nowcast' ? `Nowcast for ${nowcastValid ? formatPkt(nowcastValid) : `${hourAhead} hours ahead`}`
    : mode === 'forecast' ? `Forecast for ${longDay(viewDay)}` : undefined
  const readingLabel = mode === 'now' ? 'Latest hourly PM2.5' : mode === 'nowcast' ? 'Nowcast hourly PM2.5' : mode === 'forecast' ? 'Forecast PM2.5' : 'PM2.5 daily mean'

  // Today's run lands in the afternoon, so yesterday's is normal until then; two days means one was missed
  const issueLag = forecastIssue ? daysBetween(forecastIssue, today) : 0
  // A nowcast cycle is due every 3 h; one older than 4 h means cycles were missed
  const nowcastAge = nowcastAgeMin(nowcastData, new Date().toISOString())
  const forecastNotice = mode === 'nowcast'
    ? (nowcastData && nowcastAge != null && nowcastAge > 240
      ? `Nowcast last issued ${formatPkt(nowcastData.init_time)}, ${Math.round(nowcastAge / 60)} h old`
      : null)
    : mode !== 'day' && issueLag > 1 && forecastIssue
      ? `Forecasts last issued ${formatDateOnly(forecastIssue, { month: 'short', day: 'numeric' })}, ${issueLag} days old`
      : null

  const lastReading = latestReading(liveData?.stations ?? [])
  const viewDetail = mode === 'now'
    ? `${lastReading ? `Latest hourly readings, last observation ${formatPkt(lastReading)}.` : 'Latest hourly readings.'}${selectedPredDate ? ` Map shading is the satellite estimate for ${formatDisplayDate(selectedPredDate)}.` : ''}`
    : mode === 'nowcast'
      ? `Hourly PM2.5 expected ${nowcastValid ? `at ${formatPkt(nowcastValid)}` : `${hourAhead} hours ahead`}${nowcastData ? `, issued ${formatPkt(nowcastData.init_time)}` : ''}. Stations without recent readings are estimated from nearby stations; those with none nearby are left out.`
    : mode === 'forecast' ? 'Station forecasts only: there is no satellite estimate for days ahead.' : null

  const fireCount = firesGeoJSON?.features?.length ?? 0
  const fireStatus = firesStatus(firesGeoJSON ?? null)
  const fireLabel = firesShortLabel(firesGeoJSON ?? null, fireCount)
  const evidence = mode === 'day' ? null : {
    fires: fireStatus === 'unavailable' ? '—' : String(fireCount),
    firesLabel: fireStatus === 'unavailable' ? 'Fire data unavailable'
      : fireStatus === 'stale' ? `Fire detections (${firesGeoJSON?.date})`
      : `${mode === 'forecast' ? 'Fire detections today' : 'Satellite fire detections'}${fireLabel.warn ? `, ${fireLabel.text.split(', ').slice(1).join(', ')}` : ''}`,
    firesWarn: fireLabel.warn,
    ramps: rampCount(forecasts, isForecastLead(futureStep) ? futureStep : 1),
  }

  // Questions on today or the days ahead belong to the newest forecast run
  const chatDate = futureStep === null ? selectedPredDate : forecastIssue ?? selectedPredDate

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

  if (!selectedPredDate || !chatDate) return null

  return (
    <div className="relative flex flex-1 min-h-0 overflow-hidden max-md:flex-col-reverse">
      {/* Icon rail (bottom bar on phones) */}
      <IconRail
        activeTab={railTab}
        onTabChange={setRailTab}
        isStreaming={isStreaming}
        tabs={['chat', 'layers', 'sources', 'fires']}
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
            selectedDate={chatDate}
            briefDate={selectedPredDate}
            onAction={handleCopilotAction}
            stations={chatStations}
            onStreamingChange={setIsStreaming}
            activeTab={railTab === 'analytics' ? 'analytics' : 'chat'}
            onCloseTrend={() => setRailTab('chat')}
          />
        </div>

        {/* Stations panel */}
        <div style={{ display: railTab === 'stations' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <StructuresTab
            stations={shownStations}
            kilns={[]}
            industryCategories={[]}
            selectedDate={futureStep === null ? selectedPredDate : today}
            onFlyTo={(lng, lat, zoom) => flyTo?.(lng, lat, zoom)}
            initialView="stations"
            focus={stationFocus}
            onClose={() => setRailTab(null)}
            stationCaption={readingLabel}
            stationForecast={mode === 'forecast' ? { forecasts, today, date: viewDay } : undefined}
            stationNowcast={futureStep !== null ? nowcastData ?? undefined : undefined}
          />
        </div>

        {/* Layers panel */}
        <div style={{ display: railTab === 'layers' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
          <LayersPanel
            showStations={showStations}
            onToggleStations={() => setShowStations(v => !v)}
            showSatellite={showSurface}
            onToggleSatellite={() => setShowSurface(v => !v)}
            showFires={showFires}
            onToggleFires={() => setShowFires(v => !v)}
            showWind={showWind}
            onToggleWind={() => setShowWind(v => !v)}
            showPopulation={showPopulation}
            onTogglePopulation={() => setShowPopulation(v => !v)}
            sources={SOURCE_LAYERS.map(s => ({ ...s, on: s.key === 'kilns' ? showKilns : industryKeys.includes(s.key) }))}
            onToggleSource={(key) => {
              if (key === 'kilns') setShowKilns(v => !v)
              else setIndustryKeys(keys => (keys.includes(key) ? keys.filter(k => k !== key) : [...keys, key]))
            }}
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
                  stations={shownStations}
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
            industryKeys={industryKeys}
            showFires={showFires}
            firesData={firesGeoJSON ?? null}
            stations={shownStations as StationReading[]}
            onMapUnavailable={setMapUnavailable}
            userLocation={userLoc}
            onMapReady={(fn) => setFlyTo(() => fn)}
            onFeatureClick={openFromMap}
            panelOpen={!!railTab && !isMobile}
            showStations={showStations}
            showSurface={showSurface && mode !== 'forecast'}
            showWind={showWind}
            showPopulation={showPopulation}
            stationCaption={mode === 'day' ? undefined : readingLabel}
          />
        </MapErrorBoundary>

        {/* Floating assessment card — upper right (Gaza CausePanel pattern) */}
        <OpsContextPanel
          onFlyTo={(lng, lat, zoom) => flyTo?.(lng, lat, zoom)}
          nearby={nearby}
          selectedDate={selectedPredDate}
          model={model}
          onModelChange={setModel}
          stations={shownStations as StationReading[]}
          predictionStats={predictionData?.stats ?? null}
          runReport={runReport ?? null}
          mode={mode}
          dayLabel={dayLabel}
          readingLabel={readingLabel}
          notice={forecastNotice}
          detail={viewDetail}
          evidence={evidence}
        />

        {/* Network filter set from the chat */}
        {networkFilter && (
          <button
            onClick={() => setNetworkFilter(null)}
            aria-label={`Stop showing only ${networkFilter} stations`}
            className="absolute left-3 top-3 z-10 inline-flex items-center gap-1.5 rounded-full bg-slate-900 px-3 py-1.5 text-xs font-medium text-white shadow-lg max-md:top-14"
          >
            {networkFilter} stations only
            <X size={13} />
          </button>
        )}

        {/* Find me */}
        <button
          onClick={locate}
          disabled={locating}
          aria-label="Show air quality where I am"
          className="absolute bottom-[104px] right-3 md:bottom-[76px] md:right-4 z-10 flex h-11 w-11 items-center justify-center rounded-full text-slate-800 transition-colors hover:text-slate-950 disabled:opacity-60"
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
            className="absolute bottom-[104px] right-16 md:bottom-[80px] md:right-[68px] z-10 max-w-[260px] rounded-xl bg-slate-900 px-3 py-2 text-xs text-white shadow-lg"
          >
            {locNote}
          </div>
        )}

        {/* Timeline — one glass pill floating at the bottom of the map */}
        <div
          className="absolute bottom-12 left-3 right-3 md:bottom-4 md:left-4 md:right-4 z-10 flex items-center gap-1 rounded-full px-2 py-1.5 lg:gap-2"
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
            onClick={() => goToStep(steps[stepIndex - 1])}
            disabled={stepIndex <= 0}
            aria-label="Previous day"
            className="h-8 w-8 shrink-0 flex items-center justify-center rounded-full text-slate-700 hover:bg-slate-900/[0.06] disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>

          <DatePicker
            dates={dates}
            value={selectedPredDate}
            onChange={goToStep}
            label={timelineLabel}
          />

          <button
            onClick={() => goToStep(steps[stepIndex + 1])}
            disabled={stepIndex >= steps.length - 1}
            aria-label="Next day"
            className="h-8 w-8 shrink-0 flex items-center justify-center rounded-full text-slate-700 hover:bg-slate-900/[0.06] disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
          >
            <ChevronRight className="w-4 h-4" />
          </button>

          <div className="flex-1 relative flex items-center h-6 mx-1 max-lg:hidden">
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
                goToStep(dates[idx])
              }}
              className="relative z-10 w-full h-1 appearance-none cursor-pointer bg-transparent
 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5
                [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white
                [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-grab
                [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-slate-300"
            />
          </div>

          {/* Today, the next hours (nowcast) and the forecast days */}
          <div className="ml-auto flex shrink-0 items-center gap-0.5 rounded-full bg-slate-900/[0.06] p-0.5" role="group" aria-label="Today, the next hours and forecast days">
            {(['now', ...hourSteps, ...leads] as FutureStep[]).map(step => {
              const active = sameStep(futureStep, step)
              const date = isForecastLead(step) ? targetDate(forecasts, step) : null
              const valid = isHourStep(step) ? nowcastValidTime(nowcastData, step.h) : null
              const title = step === 'now' ? 'Latest readings'
                : isHourStep(step) ? `Nowcast for ${valid ? formatPkt(valid) : `${step.h} hours ahead`}`
                : `Forecast for ${longDay(date)}`
              return (
                <button
                  key={stepKey(step)}
                  onClick={() => goToStep(step)}
                  aria-pressed={active}
                  aria-label={step === 'now' ? 'Today' : title}
                  title={title}
                  className={`rounded-full px-2 py-2 text-xs font-medium tabular-nums transition-colors md:px-2.5 md:py-1 ${active ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-900/[0.06]'}`}
                >
                  {step === 'now' ? 'Today' : isHourStep(step) ? `+${step.h}h` : `+${daysAheadOf(step)}`}
                </button>
              )
            })}
          </div>
        </div>
      </div>

    </div>
  )
}
