"use client"

import { useRef, useState, useEffect, useMemo } from 'react'
import { canRenderMap, type MapErrorEvent, type MapUnavailableReason } from '@/lib/webgl'
import { INVENTORY_NOTE, loadEmissionSources, loadKilnsGeoJSON } from '@/lib/staticLayers'
import { formatDateOnly, formatPkt } from '@/lib/time'
import { bandKey, normalizeBand, bandColor, cardTextColor, classifyPm25, pm25ToAqi } from '@/lib/aqi'
import { esc } from '@/lib/html'
import { CITY_RANGE, SURFACE_RANGE, rangeTicks } from '@/lib/turbo'
import { paletteGradient } from '@/lib/mapviz/colormap'
import type { PredictionData } from './types'
import { AqiCard, GaugeIcon } from '@/components/shared/AqiCard'
import { AnimatePresence, m } from 'motion/react'
import { loadCountryPolygons, useBasemapTuning, useCitySurfaces, useEstimateSurface, useFireAnimation, useHeatSources, useOutlookCone, useSmokeOutlook, useSmokePlumes, OUTLOOK_BAND_COLOR, OUTLOOK_BAND_LABEL, type HeatSource, type OutlookCityPoint } from './mapViz'
import { useQuery } from '@tanstack/react-query'
import { fetchCityOutlook, type OutlookBand } from '@/components/fires/api'
import { WindParticleRenderer, type WindMetadata } from '@/components/analyst-desk/WindParticleLayer'
import { loadWindField } from '@/lib/mapviz/wind'
import { ChevronDown, Loader2, X } from 'lucide-react'
import mapboxgl from 'mapbox-gl'
import 'mapbox-gl/dist/mapbox-gl.css'
import { API_BASE } from './api'
import type { FiresGeoJSON } from '@/components/analyst-desk/api'
import { loadPakBoundary, isInsidePakistan } from '@/components/analyst-desk/pakistan'

// the deployed build reads a token restricted to this site's own addresses
// (.env.production.local); the literal is the development fallback
mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN || ''

const STYLE_URL = 'mapbox://styles/rehan0900/cmmh9p69z009m01qu0nnn3iwu'
const INITIAL_CENTER: [number, number] = [69.3459, 30.3]
// Opens on the whole country: tighter on large screens, wider on phones so it still fits
const initialZoom = () => (typeof window !== 'undefined' && window.innerWidth < 768 ? 4 : 4.6)

// Urban cities for 1km downscaler overlay
const URBAN_CITIES = [
  { key: 'lahore', bounds: [74.0, 31.2, 74.6, 31.8] as [number, number, number, number] },
  { key: 'isb_rwp', bounds: [72.6, 33.3, 73.3, 33.9] as [number, number, number, number] },
  { key: 'peshawar', bounds: [71.3, 33.8, 71.9, 34.3] as [number, number, number, number] },
  { key: 'karachi', bounds: [66.7, 24.7, 67.3, 25.3] as [number, number, number, number] },
]

interface UrbanGrid {
  resolution: number
  bounds: { west: number; east: number; south: number; north: number }
  shape: [number, number]
  pm25: (number | null)[]
}

interface StationReading {
  name: string
  city: string
  pm25: number
  lat: number
  lon: number
  latitude?: number
  longitude?: number
  valid_hours?: number | null
  complete?: boolean
  station_id?: string
  basis?: string
  obs_available?: boolean
  /** A live reading older than three hours */
  stale?: boolean
}

interface PredictionMapProps {
  selectedDate: string
  smoothed?: boolean
  model?: 'backbone' | 'support_aware'
  showKilns?: boolean
  showIndustry?: boolean
  /** Industry categories to show; every category when left out */
  industryKeys?: readonly string[]
  showFires?: boolean
  firesData?: FiresGeoJSON | null
  /** Station daily means from the page's shared query; when given, the map does not fetch its own copy */
  stations?: StationReading[]
  /** Called when the map cannot render; the page shows a non-map fallback */
  onMapUnavailable?: (reason: MapUnavailableReason | null) => void
  /** Hands the page a flyTo whose promise resolves when the camera has stopped moving */
  onMapReady?: (flyTo: (lng: number, lat: number, zoom?: number) => Promise<void>) => void
  /** A station, brick kiln or industrial site was clicked; the page opens it in the sidebar */
  onFeatureClick?: (feature: MapFeatureClick) => void
  /** The visitor's position (only passed when it is inside Pakistan) */
  userLocation?: { lng: number; lat: number } | null
  /** A side panel is taking width from the map (desktop only; on phones it floats over) */
  panelOpen?: boolean
  showStations?: boolean
  /** The satellite PM2.5 surface. It only exists for past days, so forecast days turn it off. */
  showSurface?: boolean
  showWind?: boolean
  showPopulation?: boolean
  /** What a station's number means in this view, for the hover card */
  stationCaption?: string
  /** Told when the district card opens or closes, so the page can make room for it */
  onDistrictOpenChange?: (open: boolean) => void
  /** Bump to close the district card (the page needs the space for another card) */
  closeDistrictSignal?: number
  /** Shown first in the left-hand stack of map cards (above the colour scale) */
  leftSlot?: React.ReactNode
  /** Tuck the colour scale away: another card needs the room */
  hideLegend?: boolean
  /** Which part of the timeline is in view: past days use the satellite surface, the rest a surface between stations */
  mode?: 'day' | 'now' | 'nowcast' | 'forecast'
  /** Smoke outlook layer (fire report §9) */
  showSmoke?: boolean
  /** Illustrative smoke plumes downwind of the fires on the map */
  showPlumes?: boolean
  /** Tomorrow's smoke outlook per city (fire report §9) */
  outlookCities?: OutlookCityPoint[]
  /** Persistent heat sources of the last 30 days (fire report §8.4), shown with the fire layer */
  heatSources?: HeatSource[]
  heatWindowDays?: number
  /** The estimate grid for the day and model in view; the map paints it */
  estimateGrid?: PredictionData | null
}

export type MapFeatureClick =
  | { kind: 'station'; station: StationReading }
  | { kind: 'kiln'; id: string }
  | { kind: 'industry'; categoryKey: string; name?: string; lng: number; lat: number }

interface HoverPM25 {
  pm25: number
  lat: number
  lon: number
  label: string
}

// Health classification: one implementation for the whole dashboard (lib/aqi, US EPA 2024)
function pm25ToBand(pm25: number): string {
  return bandKey(pm25)
}

const BAND_COLORS: Record<string, string> = new Proxy({}, { get: (_t, k: string) => bandColor(k) })

/** Round marker icon: flat band colour with a soft shadow, no edge. */
function makeCircleImage(color: string): { data: ImageData; options: { pixelRatio: number } } {
  const S = 72, r = 28
  const canvas = document.createElement('canvas')
  canvas.width = S; canvas.height = S
  const ctx = canvas.getContext('2d')!
  ctx.shadowColor = 'rgba(15,23,42,0.30)'; ctx.shadowBlur = 4; ctx.shadowOffsetY = 1.5
  ctx.beginPath(); ctx.arc(S / 2, S / 2 - 1, r, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill()
  return { data: ctx.getImageData(0, 0, S, S), options: { pixelRatio: 2 } }
}

/** Marker icons by data quality: filled (live), ring (estimated from neighbours), diamond (model only), stale (a fainter disc, no edge). */
function makeMarkerImage(color: string, shape: 'fill' | 'ring' | 'diamond' | 'stale'): { data: ImageData; options: { pixelRatio: number } } {
  if (shape === 'fill') return makeCircleImage(color)
  const S = 72, r = 27
  const canvas = document.createElement('canvas')
  canvas.width = S; canvas.height = S
  const ctx = canvas.getContext('2d')!
  ctx.shadowColor = 'rgba(15,23,42,0.28)'; ctx.shadowBlur = 4; ctx.shadowOffsetY = 1.5
  const cx = S / 2, cy = S / 2 - 1
  if (shape === 'diamond') {
    ctx.beginPath(); ctx.moveTo(cx, cy - r - 3); ctx.lineTo(cx + r + 3, cy); ctx.lineTo(cx, cy + r + 3); ctx.lineTo(cx - r - 3, cy); ctx.closePath()
    ctx.fillStyle = '#ffffff'; ctx.fill(); ctx.shadowColor = 'transparent'
    ctx.lineWidth = 6; ctx.strokeStyle = color; ctx.stroke()
  } else if (shape === 'ring') {
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = '#ffffff'; ctx.fill(); ctx.shadowColor = 'transparent'
    ctx.beginPath(); ctx.arc(cx, cy, r - 3, 0, Math.PI * 2); ctx.lineWidth = 6; ctx.strokeStyle = color; ctx.stroke()
  } else {
    ctx.globalAlpha = 0.35
    ctx.shadowColor = 'transparent'
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill()
    ctx.globalAlpha = 1
  }
  return { data: ctx.getImageData(0, 0, S, S), options: { pixelRatio: 2 } }
}

/** Station markers draw above kilns and industry, so a click on one belongs to the station. */
function hitsStation(map: mapboxgl.Map, e: mapboxgl.MapMouseEvent): boolean {
  return !!map.getLayer('stations-label') && map.queryRenderedFeatures(e.point, { layers: ['stations-label'] }).length > 0
}

// Zoom range: a whole-country view at the lowest level (fits a phone), street level at the highest
interface SelectedDistrict {
  name: string
  pm25: number | null
  stations: StationReading[]
}

/** Average of a ring's points: near enough a district's middle for a point reading. */
function ringCentre(ring: number[][]): [number, number] {
  let x = 0, y = 0
  for (const [lon, lat] of ring) { x += lon; y += lat }
  return [x / ring.length, y / ring.length]
}

/** Is the point inside a Polygon or MultiPolygon (holes respected)? */
function pointInGeometry(lon: number, lat: number, geom: GeoJSON.Geometry): boolean {
  const inRing = (ring: number[][]) => {
    let inside = false
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j]
      if ((yi > lat) !== (yj > lat) && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside
    }
    return inside
  }
  const inPolygon = (rings: number[][][]) => inRing(rings[0]) && !rings.slice(1).some(inRing)
  if (geom.type === 'Polygon') return inPolygon(geom.coordinates)
  if (geom.type === 'MultiPolygon') return geom.coordinates.some(inPolygon)
  return false
}

const SURFACE_GRADIENT = paletteGradient()
const NO_OUTLOOK: OutlookCityPoint[] = []
const NO_HEAT: HeatSource[] = []
const NO_PLUME_FIRES: FiresGeoJSON['features'] = []
const SURFACE_TICKS = rangeTicks(SURFACE_RANGE)

const MIN_ZOOM = 3.6
const MAX_ZOOM = 16

const PAKISTAN_BOUNDS: [[number, number], [number, number]] = [[60.8, 23.5], [77.9, 37.2]]
const SUMMARY_CARD_PX = 380 // the floating card's width plus its margin
const PANEL_SETTLE_MS = 350 // the side panel's spring has finished by then

export function PredictionMap({ selectedDate, smoothed = false, model = 'backbone', showKilns = true, showIndustry = false, industryKeys, showFires = false, firesData = null, stations: stationsProp, onMapUnavailable, onMapReady, onFeatureClick, userLocation, panelOpen = false, showStations = true, showSurface = true, showWind = false, showPopulation = false, stationCaption, onDistrictOpenChange, closeDistrictSignal, leftSlot, hideLegend = false, mode = 'day', showSmoke = true, showPlumes = true, outlookCities = NO_OUTLOOK, heatSources = NO_HEAT, heatWindowDays = 30, estimateGrid = null }: PredictionMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [, setHoveredDistrict] = useState<string | null>(null)
  const [hoverPM25, setHoverPM25] = useState<HoverPM25 | null>(null)

  // Station markers
  const [stations, setStations] = useState<StationReading[]>([])
  const [hoveredStation, setHoveredStation] = useState<StationReading | null>(null)
  // The district clicked on the map: its modelled PM2.5 and the stations inside it
  const [selectedDistrict, setSelectedDistrict] = useState<SelectedDistrict | null>(null)
  const clearDistrictRef = useRef<(() => void) | null>(null)
  // Zoomed into a city with its own 1 km layer, which uses a narrower colour range
  const [inCityDetail, setInCityDetail] = useState(false)
  const surfaceRef = useRef({ selectedDate, model, smoothed })
  surfaceRef.current = { selectedDate, model, smoothed }
  // The satellite estimate: the day in view, or the newest finished day under today's readings.
  // Days ahead have none.
  const satelliteOn = showSurface && mode !== 'forecast'

  // Fire layer refs
  const fireSourceAdded = useRef(false)
  const firesRef = useRef(firesData)
  firesRef.current = firesData

  const loadSourcesRef = useRef<(() => Promise<void>) | null>(null)
  const sourcesStartedRef = useRef(false)
  const [sourcesReady, setSourcesReady] = useState(false)
  const onMapUnavailableRef = useRef(onMapUnavailable)
  onMapUnavailableRef.current = onMapUnavailable
  // Click handlers are registered once at map creation; read the latest callback
  const onFeatureClickRef = useRef(onFeatureClick)
  onFeatureClickRef.current = onFeatureClick
  const panelOpenRef = useRef(panelOpen)
  const [wind, setWind] = useState<{ image: HTMLImageElement; meta: WindMetadata } | null>(null)
  const viewChosenRef = useRef(false)

  // Refs for urban grid hover (same pattern as ForecastMap)
  const urbanGridsRef = useRef<Map<string, UrbanGrid>>(new Map())
  const urbanGridLoadingRef = useRef<Set<string>>(new Set())
  const selectedDateRef = useRef(selectedDate)

  useEffect(() => {
    selectedDateRef.current = selectedDate
  }, [selectedDate])

  // Station daily means for the selected date: from the page's shared query when provided
  // (one request for map and panels), else fetched here (same QA filter as model training).
  useEffect(() => {
    if (stationsProp) {
      setStations(stationsProp)
      return
    }
    const fetchStations = async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/ops/pipeline/stations/daily/${selectedDate}?min_hours=6&country=Pakistan`
        )
        if (res.ok) {
          const data = await res.json()
          const s = data?.stations ?? []
          setStations(s)
        } else {
          setStations([])
        }
      } catch {
        setStations([])
      }
    }
    fetchStations()
  }, [selectedDate, stationsProp])

  // A side panel narrows the map: refit Pakistan into the space left beside the summary card,
  // unless the visitor has already chosen their own view.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded || panelOpenRef.current === panelOpen) return
    panelOpenRef.current = panelOpen
    if (viewChosenRef.current) return
    const timer = setTimeout(() => {
      map.resize()
      const right = Math.min(SUMMARY_CARD_PX, map.getContainer().clientWidth * 0.45)
      map.fitBounds(PAKISTAN_BOUNDS, { padding: { top: 32, bottom: 96, left: 32, right }, duration: 500 })
    }, PANEL_SETTLE_MS)
    return () => clearTimeout(timer)
  }, [panelOpen, mapLoaded])

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return
    if (!canRenderMap()) {
      onMapUnavailableRef.current?.('no-webgl')
      return
    }

    let map: mapboxgl.Map
    try {
      map = new mapboxgl.Map({
      container: mapContainer.current,
      style: STYLE_URL,
      center: INITIAL_CENTER,
      zoom: initialZoom(),
      minZoom: MIN_ZOOM,
      maxZoom: MAX_ZOOM,
      // Map credits are shown in the summary card (ContextPanel)
      attributionControl: false,
      transformRequest: (url: string) => {
        if (url.includes('/ops/pipeline/tiles/') || url.includes('/ops/downscaler/tiles/')) {
          return { url }
        }
        return { url }
      }
    })
    } catch (err) {
      console.warn('[map] init failed', err)
      onMapUnavailableRef.current?.('init-failed')
      return
    }

    mapRef.current = map

    // Tile 404s are routine (no COG for a date); anything else is a real failure.
    map.on('error', (ev: MapErrorEvent) => {
      const status = ev?.error?.status ?? ev?.error?.statusCode
      if (status === 404 || status === 400) return
      if (ev?.sourceId || ev?.tile) return
      console.warn('[map] error', ev?.error?.message ?? ev)
    })
    // preventDefault lets the browser restore the context; Mapbox then redraws on its own
    map.getCanvas().addEventListener('webglcontextlost', (e) => {
      e.preventDefault()
      if (mapRef.current !== map) return // a removed (stale) map also fires this event
      onMapUnavailableRef.current?.('context-lost')
    })
    map.getCanvas().addEventListener('webglcontextrestored', () => {
      if (mapRef.current !== map) return
      onMapUnavailableRef.current?.(null)
    })

    // Someone moving the map keeps their view; only drags, scrolls and pinches carry originalEvent
    map.on('movestart', (e) => { if (e.originalEvent) viewChosenRef.current = true })
    map.on('moveend', () => {
      const { lng, lat } = map.getCenter()
      setInCityDetail(map.getZoom() >= 9.5 && URBAN_CITIES.some(({ bounds: [w, so, e, n] }) => lng >= w && lng <= e && lat >= so && lat <= n))
    })

    // Expose flyTo callback to parent
    onMapReady?.((lng: number, lat: number, zoom?: number) => new Promise<void>((resolve) => {
      viewChosenRef.current = true
      const done = () => { clearTimeout(timer); resolve() }
      const timer = setTimeout(() => { map.off('moveend', done); resolve() }, 4000) // already there: no move event
      map.once('moveend', done)
      map.flyTo({ center: [lng, lat], zoom: zoom ?? 12, duration: 1200 })
    }))

    map.on('load', async () => {
      try {
      // Load boundaries concurrently (they were awaited one after another)
      const [districtsGeoJSON, adm1GeoJSON] = await Promise.all([
        fetch('/pakistan_districts.geojson').then(r => r.json()),
        fetch('/pakistan_adm1.geojson').then(r => r.json()),
      ])

      // Add sources
      map.addSource('pakistan-districts', { type: 'geojson', data: districtsGeoJSON, promoteId: 'shapeName' })
      map.addSource('pakistan-adm1', { type: 'geojson', data: adm1GeoJSON })

      // ── Kilns and industry are low priority: loaded in the background, and only once asked for ──
      loadSourcesRef.current = async () => {
      // ── Brick kilns — secondary explanatory layer, reveals on zoom ──
      //    z<8.5: hidden. z8.5-10: subtle amber dots. z10+: chimney icons. z12+: hover popups.
      try {
        const kilnsGeoJSON = await loadKilnsGeoJSON()  // shared with the Sources panel; parsed once
        map.addSource('brick-kilns', { type: 'geojson', data: kilnsGeoJSON })

        // Generate chimney icon (SVG → canvas → map image)
        const chimneyImg = await new Promise<HTMLImageElement>((resolve) => {
          const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="28" viewBox="0 0 24 28">
            <!-- Chimney stack -->
            <rect x="8" y="6" width="8" height="16" rx="1" fill="#b45309" stroke="#92400e" stroke-width="0.8"/>
            <!-- Chimney top rim -->
            <rect x="6.5" y="4" width="11" height="3" rx="1" fill="#d97706" stroke="#92400e" stroke-width="0.6"/>
            <!-- Base/foundation -->
            <rect x="5" y="22" width="14" height="4" rx="1" fill="#78716c" stroke="#57534e" stroke-width="0.6"/>
            <!-- Smoke puffs -->
            <circle cx="12" cy="2.5" r="2" fill="#d97706" opacity="0.5"/>
            <circle cx="15" cy="1.5" r="1.5" fill="#d97706" opacity="0.35"/>
            <circle cx="9.5" cy="1" r="1.2" fill="#d97706" opacity="0.25"/>
          </svg>`
          const img = new Image()
          img.onload = () => resolve(img)
          img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
        })
        if (!map.hasImage('kiln-chimney')) {
          map.addImage('kiln-chimney', chimneyImg, { sdf: false })
        }

        // Soft glow halo — ambient presence at medium zoom
        map.addLayer({
          id: 'brick-kilns-glow', type: 'circle', source: 'brick-kilns',
          minzoom: 8.5,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 8.5, 3, 10, 6, 12, 10, 14, 14],
            'circle-color': '#d97706',
            'circle-opacity': ['interpolate', ['linear'], ['zoom'],
              8.5, 0,
              9.5, 0.04,
              10.5, 0.08,
              12, 0.1,
            ],
            'circle-blur': 1,
          },
        })

        // Small amber dots — from province zoom (z7) until the icons take over (z10)
        map.addLayer({
          id: 'brick-kilns-dots', type: 'circle', source: 'brick-kilns',
          minzoom: 7,
          maxzoom: 11,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 1.2, 8.5, 1.9, 10, 2.5],
            'circle-color': '#d97706',
            'circle-opacity': ['interpolate', ['linear'], ['zoom'],
              7, 0.5,
              10.5, 0.5,
            ],
          },
        })

        // Chimney icons — appear at z10+ as the dots phase out
        map.addLayer({
          id: 'brick-kilns-layer', type: 'symbol', source: 'brick-kilns',
          minzoom: 10,
          layout: {
            'icon-image': 'kiln-chimney',
            'icon-size': ['interpolate', ['linear'], ['zoom'], 10, 0.4, 12, 0.65, 14, 0.9],
            'icon-allow-overlap': true,
            'icon-ignore-placement': true,
          },
          paint: {
            'icon-opacity': ['interpolate', ['linear'], ['zoom'],
              10, 0.3,
              11, 0.6,
              12, 0.85,
            ],
          },
        })

        // Sources sit under the station markers, which stay readable on top
        if (map.getLayer('stations-label')) {
          for (const id of ['brick-kilns-glow', 'brick-kilns-dots', 'brick-kilns-layer']) map.moveLayer(id, 'stations-label')
        }

        // Hover popup — z10+
        const kilnPopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '220px', className: 'pointer-events-none' })

        map.on('mouseenter', 'brick-kilns-layer', (e) => {
          if (!e.features?.[0] || map.getZoom() < 10) return
          map.getCanvas().style.cursor = 'pointer'
          const props = e.features[0].properties!
          const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number]
          kilnPopup.setLngLat(coords).setHTML(`
            <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">
              <div style="font-weight:600;color:#b45309;margin-bottom:4px">Brick Kiln ${esc(props.id || '')}</div>
              <div>PM₂.₅: <b>${esc(props.pm25_t_yr ?? '—')} t/yr</b></div>
              <div>Fuel: <b style="text-transform:capitalize">${esc(props.fuel || '—')}</b></div>
              <div>State: <b>${esc(props.state || '—')}</b></div>
              ${props.pop1km ? `<div style="color:#64748b;font-size:11px;margin-top:2px">Pop within 1km: ${Number(props.pop1km).toLocaleString()}</div>` : ''}
              <div style="color:#94a3b8;font-size:10px;margin-top:4px;max-width:220px">${esc(INVENTORY_NOTE)}</div>
            </div>
          `).addTo(map)
        })

        map.on('mouseleave', 'brick-kilns-layer', () => {
          map.getCanvas().style.cursor = ''
          kilnPopup.remove()
        })

        for (const layerId of ['brick-kilns-layer', 'brick-kilns-dots']) {
          map.on('click', layerId, (e) => {
            if (hitsStation(map, e)) return
            const id = e.features?.[0]?.properties?.id
            if (id != null) onFeatureClickRef.current?.({ kind: 'kiln', id: String(id) })
          })
        }
      } catch (e) {
        console.warn('[BrickKilns] Failed to load:', e)
      }

      // ── Industrial emission sources (power plants, cement, steel, etc.) ──
      try {
        const srcData = await loadEmissionSources()  // shared with the Sources panel; parsed once

        const INDUSTRY_LAYERS = [
          { key: 'power_plants', color: '#ef4444', label: 'Power Plant' },
          { key: 'cement_plants', color: '#8b5cf6', label: 'Cement Plant' },
          { key: 'steel_sites', color: '#6366f1', label: 'Steel Site' },
          { key: 'sugar_mills', color: '#10b981', label: 'Sugar Mill' },
          { key: 'industrial_sites', color: '#64748b', label: 'Industrial' },
          { key: 'mines_quarries', color: '#78716c', label: 'Mine/Quarry' },
        ]

        // SVG icon paths for each category (rendered into canvas → addImage)
        const INDUSTRY_ICONS: Record<string, (color: string) => string> = {
          power_plants: (c) => `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>`,
          cement_plants: (c) => `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 20h20"/><path d="M5 20V8l4-4v16"/><path d="M9 20V4l5 4v12"/><path d="M14 20V8l5 4v8"/></svg>`,
          steel_sites: (c) => `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v8"/><path d="m4.93 10.93 1.41 1.41"/><path d="M2 18h2"/><path d="M20 18h2"/><path d="m19.07 10.93-1.41 1.41"/><path d="M22 22H2"/><path d="m8 6 4-4 4 4"/><path d="M16 18a4 4 0 0 0-8 0"/></svg>`,
          sugar_mills: (c) => `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 20h10"/><path d="M10 20c5.5-2.5.8-6.4 3-10"/><path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/><path d="M14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/></svg>`,
          mines_quarries: (c) => `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 20l10-10"/><path d="M16 8l-2-2"/><path d="M22 2l-6 6"/><path d="M6 18L2 22"/><path d="M18 10l4-4"/><path d="m14 4 6 6"/><circle cx="12" cy="12" r="2"/></svg>`,
          industrial_sites: (c) => `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/></svg>`,
        }

        // Register SVG icons with Mapbox as images
        for (const layer of INDUSTRY_LAYERS) {
          const svgFn = INDUSTRY_ICONS[layer.key]
          if (!svgFn) continue
          const svg = svgFn('#ffffff')
          const img = new Image(28, 28)
          img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg)
          await new Promise<void>((resolve) => {
            img.onload = () => {
              if (!map.hasImage(`icon-${layer.key}`)) {
                map.addImage(`icon-${layer.key}`, img, { sdf: false })
              }
              resolve()
            }
            img.onerror = () => resolve()
          })
        }

        const industryPopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '220px', className: 'pointer-events-none' })

        for (const layer of INDUSTRY_LAYERS) {
          if (!srcData[layer.key]?.features?.length) continue
          const srcId = `industry-${layer.key}`
          const layerId = `industry-${layer.key}-layer`

          map.addSource(srcId, { type: 'geojson', data: srcData[layer.key] })

          // A fine dot from province zoom (z7), growing into a glow behind the icon
          map.addLayer({
            id: `${layerId}-bg`, type: 'circle', source: srcId,
            minzoom: 7,
            layout: { visibility: 'none' },
            paint: {
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 1.5, 8, 2.5, 10, 10, 12, 14],
              'circle-color': layer.color,
              'circle-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.5, 8, 0.5, 8.5, 0.15, 10, 0.25, 12, 0.3],
              'circle-blur': ['interpolate', ['linear'], ['zoom'], 7, 0, 8, 0, 8.5, 0.8],
            },
          })

          // Symbol icon layer
          map.addLayer({
            id: layerId, type: 'symbol', source: srcId,
            minzoom: 7,
            layout: {
              visibility: 'none',
              'icon-image': `icon-${layer.key}`,
              'icon-size': ['interpolate', ['linear'], ['zoom'], 7, 0.35, 10, 0.6, 12, 0.85],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
            },
            paint: {
              'icon-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0, 8.5, 0.5, 10, 0.85, 12, 1],
            },
          })
          if (map.getLayer('stations-label')) {
            map.moveLayer(`${layerId}-bg`, 'stations-label')
            map.moveLayer(layerId, 'stations-label')
          }

          map.on('mouseenter', layerId, (e) => {
            if (!e.features?.[0]) return
            map.getCanvas().style.cursor = 'pointer'
            const props = e.features[0].properties!
            const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number]
            const lines = [`<div style="font-weight:600;color:${layer.color};margin-bottom:4px">${layer.label}</div>`]
            if (props.name) lines.push(`<div><b>${esc(props.name)}</b></div>`)
            if (props.fuel) lines.push(`<div>Fuel: <b>${esc(props.fuel)}</b></div>`)
            if (props.capacity_mw) lines.push(`<div>Capacity: <b>${esc(props.capacity_mw)} MW</b></div>`)
            if (props.capacity_mtpa) lines.push(`<div>Capacity: <b>${esc(props.capacity_mtpa)} Mt/yr</b></div>`)
            if (props.province) lines.push(`<div style="color:#64748b;font-size:11px">${esc(props.province)}</div>`)
            lines.push(`<div style="color:#94a3b8;font-size:10px;margin-top:4px;max-width:220px">${esc(INVENTORY_NOTE)}</div>`)
            industryPopup.setLngLat(coords).setHTML(
              `<div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">${lines.join('')}</div>`
            ).addTo(map)
          })
          map.on('mouseleave', layerId, () => {
            map.getCanvas().style.cursor = ''
            industryPopup.remove()
          })
          map.on('click', layerId, (e) => {
            const feat = e.features?.[0]
            if (!feat || hitsStation(map, e)) return
            const [lng, lat] = (feat.geometry as GeoJSON.Point).coordinates
            onFeatureClickRef.current?.({ kind: 'industry', categoryKey: layer.key, name: feat.properties?.name ?? undefined, lng, lat })
          })
        }
      } catch (e) {
        console.warn('[Industry] Failed to load:', e)
      }
        setSourcesReady(true)
      }

      // 2. District fill layer (transparent, for interaction)
      map.addLayer({
        id: 'districts-fill', type: 'fill', source: 'pakistan-districts',
        paint: { 'fill-color': 'transparent', 'fill-opacity': 0 }
      })

      // 3. District hover highlight
      map.addLayer({
        id: 'districts-hover', type: 'fill', source: 'pakistan-districts',
        paint: {
          'fill-color': '#ffffff',
          'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.3, 0]
        }
      })

      // 4. District selection highlight
      map.addLayer({
        id: 'districts-selected', type: 'fill', source: 'pakistan-districts',
        paint: {
          'fill-color': '#3b82f6',
          'fill-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 0.4, 0]
        }
      })

      // 5. District borders
      map.addLayer({
        id: 'districts-borders', type: 'line', source: 'pakistan-districts',
        paint: {
          'line-color': ['case',
            ['boolean', ['feature-state', 'selected'], false], '#475569',
            ['boolean', ['feature-state', 'hover'], false], '#64748b',
            '#94a3b8'],
          'line-width': ['case',
            ['boolean', ['feature-state', 'selected'], false], 1.5,
            ['boolean', ['feature-state', 'hover'], false], 1,
            0.3],
          'line-opacity': 0.5
        }
      })

      // 6. Province borders
      map.addLayer({
        id: 'province-borders', type: 'line', source: 'pakistan-adm1',
        paint: { 'line-color': '#94a3b8', 'line-width': 1, 'line-opacity': 0.7 }
      })


      // ── Active fires (FIRMS VIIRS) ──
      await loadPakBoundary() // ensure Pakistan boundary is ready for point-in-polygon filtering

      map.addSource('fires', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })

      map.addLayer({
        id: 'fires-glow',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'frp'], 0, 12, 50, 24, 200, 40],
          'circle-color': '#ff8c00',
          'circle-opacity': 0.15,
          'circle-blur': 1,
        },
        layout: { visibility: 'none' },
      })

      map.addLayer({
        id: 'fires-layer',
        type: 'circle',
        source: 'fires',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'frp'], 0, 3, 50, 6, 200, 10],
          'circle-color': [
            'match', ['get', 'confidence'],
            'h', '#ff2200',
            'high', '#ff2200',
            '#ff8c00',
          ],
          'circle-opacity': 0.85,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(0,0,0,0.3)',
        },
        layout: { visibility: 'none' },
      })

      // Fire hover popup
      const firePopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '230px', className: 'pointer-events-none' })

      map.on('mouseenter', 'fires-layer', (e) => {
        if (!e.features?.[0]) return
        map.getCanvas().style.cursor = 'pointer'
        const props = e.features[0].properties!
        const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number]
        firePopup.setLngLat(coords).setHTML(`
          <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">
            <div style="font-weight:600;color:#ea580c;margin-bottom:4px">Fire<span style="font-weight:500;color:#64748b"> · ${esc(props.region ?? 'Pakistan')}</span></div>
            <div>FRP: <b>${esc(props.frp)} MW</b> <span style="color:#94a3b8">(burning intensity, not PM2.5)</span></div>
            ${Number(props.merged) > 1 ? `<div>Seen by <b>${esc(props.merged)}</b> detections (satellites merged)</div>` : ''}
            <div>Confidence: <b style="text-transform:capitalize">${esc(props.confidence)}</b></div>
            <div>Satellite: <b>${esc(props.satellite)}</b> VIIRS</div>
            <div style="color:#64748b;font-size:11px;margin-top:2px">Acquired ${esc(props.acq_datetime_utc ? formatPkt(props.acq_datetime_utc) : props.acq_date)}</div>
          </div>
        `).addTo(map)
      })

      map.on('mouseleave', 'fires-layer', () => {
        map.getCanvas().style.cursor = ''
        firePopup.remove()
      })

      fireSourceAdded.current = true

      // Sync fire data if it arrived before map loaded
      if (firesRef.current) {
        const src = map.getSource('fires') as mapboxgl.GeoJSONSource | undefined
        if (src) {
          const filtered = {
            ...firesRef.current,
            features: firesRef.current.features.filter(f => {
              const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates
              return isInsidePakistan(lng, lat)
            }),
          }
          src.setData(filtered as GeoJSON.FeatureCollection)
        }
      }

      // ── Hover: district + urban grid readout ──
      let hoveredId: string | null = null

      // Fetch urban grid JSON once per city (cached)
      const ensureUrbanGrid = (cityKey: string) => {
        if (urbanGridsRef.current.has(cityKey) || urbanGridLoadingRef.current.has(cityKey)) return
        urbanGridLoadingRef.current.add(cityKey)
        fetch(`${API_BASE}/api/v1/ops/downscaler/grid/${cityKey}/${selectedDateRef.current}`)
          .then(r => r.ok ? r.json() : null)
          .then(data => {
            if (!data) return
            urbanGridsRef.current.set(cityKey, {
              resolution: data.grid?.resolution || 0.01,
              bounds: data.grid?.bounds || {},
              shape: data.grid?.shape || [0, 0],
              pm25: data.pm25 || [],
            })
          })
          .catch(() => {})
          .finally(() => urbanGridLoadingRef.current.delete(cityKey))
      }

      // O(1) grid lookup
      const lookupUrbanPM25 = (cityKey: string, lat: number, lng: number): number | null => {
        const grid = urbanGridsRef.current.get(cityKey)
        if (!grid || !grid.pm25.length) return null
        const { bounds, shape, resolution } = grid
        const row = Math.floor((lat - bounds.south) / resolution)
        const col = Math.floor((lng - bounds.west) / resolution)
        if (row < 0 || row >= shape[0] || col < 0 || col >= shape[1]) return null
        const idx = row * shape[1] + col
        return grid.pm25[idx]
      }

      // Combined mousemove: district hover + urban grid readout
      map.on('mousemove', (e) => {
        const zoom = map.getZoom()
        const { lng, lat } = e.lngLat

        // Urban grid hover at high zoom
        if (zoom >= 8) {
          const city = URBAN_CITIES.find(c =>
            lng >= c.bounds[0] && lng <= c.bounds[2] &&
            lat >= c.bounds[1] && lat <= c.bounds[3]
          )
          if (city) {
            ensureUrbanGrid(city.key)
            const val = lookupUrbanPM25(city.key, lat, lng)
            if (val != null) {
              setHoverPM25({ pm25: val, lat, lon: lng, label: '1km Downscaler' })
            } else {
              setHoverPM25(null)
            }
          } else {
            setHoverPM25(null)
          }
        } else {
          setHoverPM25(null)
        }
      })

      // District hover
      map.on('mousemove', 'districts-fill', (e) => {
        if (e.features && e.features.length > 0) {
          const feature = e.features[0]
          const newId = feature.properties?.shapeName
          if (hoveredId !== newId) {
            if (hoveredId) map.setFeatureState({ source: 'pakistan-districts', id: hoveredId }, { hover: false })
            hoveredId = newId
            map.setFeatureState({ source: 'pakistan-districts', id: newId }, { hover: true })
            setHoveredDistrict(newId)
          }
        }
      })

      map.on('mouseleave', 'districts-fill', () => {
        if (hoveredId) {
          map.setFeatureState({ source: 'pakistan-districts', id: hoveredId }, { hover: false })
          hoveredId = null
        }
        setHoveredDistrict(null)
        setHoverPM25(null)
        map.getCanvas().style.cursor = ''
      })

      // Click a district: highlight it, then show its modelled PM2.5 and the stations inside it
      let districtId: string | null = null
      let pointAbort: AbortController | null = null
      const clearDistrict = () => {
        if (districtId) map.setFeatureState({ source: 'pakistan-districts', id: districtId }, { selected: false })
        districtId = null
        pointAbort?.abort()
        setSelectedDistrict(null)
      }
      clearDistrictRef.current = clearDistrict
      map.on('click', async (e) => {
        const hits = map.queryRenderedFeatures(e.point)
        // Station, kiln and industry markers open their own panels
        // Stations, kilns, industry, outlook cities and heat sources open their own cards
        if (hits.some(f => f.layer?.id === 'stations-label' || f.layer?.id === 'hawa-outlook-city' || f.layer?.id === 'hawa-heat' || f.layer?.id.startsWith('industry-') || f.layer?.id.startsWith('brick-kilns'))) return
        const feature = hits.find(f => f.layer?.id === 'districts-fill')
        if (!feature) { clearDistrict(); return }
        const name = String(feature.properties?.shapeName ?? '')
        if (districtId) map.setFeatureState({ source: 'pakistan-districts', id: districtId }, { selected: false })
        districtId = name
        map.setFeatureState({ source: 'pakistan-districts', id: name }, { selected: true })

        // Rendered geometry is cut at tile edges: use the full district outline
        const geom = (districtsGeoJSON.features as GeoJSON.Feature[]).find(f => f.properties?.shapeName === name)?.geometry ?? feature.geometry
        const ring = geom.type === 'Polygon' ? geom.coordinates[0]
          : geom.type === 'MultiPolygon' ? geom.coordinates.reduce((a, b) => (a[0].length > b[0].length ? a : b))[0]
          : null
        const [lon, lat] = ring ? ringCentre(ring) : [e.lngLat.lng, e.lngLat.lat]
        const stations = stationsByIdRef.current.filter(st => {
          const x = st.lon ?? st.longitude, y = st.lat ?? st.latitude
          return x != null && y != null && pointInGeometry(x, y, geom)
        })

        const sel = surfaceRef.current
        const params = [sel.smoothed && 'smoothed=true', sel.model !== 'backbone' && `model=${sel.model}`].filter(Boolean).map(p => '&' + p).join('')
        pointAbort?.abort()
        const ac = new AbortController()
        pointAbort = ac
        // The district's centre first; where the centre has no estimate, the spot that was clicked
        let pm25: number | null = null
        for (const [y, x] of [[lat, lon], [e.lngLat.lat, e.lngLat.lng]]) {
          try {
            const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/tiles/${sel.selectedDate}/point?lat=${y}&lon=${x}${params}`, { signal: ac.signal })
            if (res.ok) pm25 = (await res.json()).pm25 ?? null
          } catch {
            if (ac.signal.aborted) return
          }
          if (pm25 != null) break
        }
        if (ac.signal.aborted || districtId !== name) return
        setSelectedDistrict({ name, pm25, stations })
      })

      setMapLoaded(true)
      } catch (err) {
        // A failed layer must not leave the spinner up forever or take the page down.
        console.warn('[map] layer setup failed', err)
        setMapLoaded(true)
        onMapUnavailableRef.current?.('layers-failed')
      }
    })

    return () => {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [])

  // "You are here" puck
  useEffect(() => {
    if (!mapRef.current || !mapLoaded || !userLocation) return
    const el = document.createElement('div')
    el.setAttribute('role', 'img')
    el.setAttribute('aria-label', 'Your location')
    el.style.cssText = 'width:16px;height:16px;border-radius:50%;background:#2563eb;border:3px solid #fff;box-shadow:0 1px 6px rgba(15,23,42,0.45);'
    const marker = new mapboxgl.Marker({ element: el, anchor: 'center' }).setLngLat([userLocation.lng, userLocation.lat]).addTo(mapRef.current)
    return () => { marker.remove() }
  }, [userLocation, mapLoaded])

  // Station markers are GL layers (one source, three layers), not DOM nodes: panning and zooming
  // no longer reposition ~1000 elements per frame and React is not involved in drawing them.
  const stationsByIdRef = useRef<StationReading[]>([])
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current

    const features: GeoJSON.Feature[] = []
    stations.forEach((stn, i) => {
      const lat = stn.lat ?? stn.latitude
      const lon = stn.lon ?? stn.longitude
      if (lat == null || lon == null || stn.pm25 == null) return
      const band = pm25ToBand(stn.pm25)
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [lon, lat] },
        properties: {
          i,
          label: String(Math.round(stn.pm25)),
          pm25: stn.pm25,
          color: bandColor(band),
          band: normalizeBand(band),
          // White figures on red, purple and brown discs; ring and diamond markers have a white fill
          text: stn.basis === 'neighbours' || stn.basis === 'prior' ? '#0f172a' : cardTextColor(band),
          // forecast readings: 'model' | 'neighbours' | 'prior'; live readings have none
          basis: stn.basis ?? 'model',
          // Marker shape: live (filled), estimated from neighbours (ring), model only (diamond), stale (fainter)
          shape: stn.basis === 'neighbours' ? 'ring' : stn.basis === 'prior' ? 'diamond' : stn.stale ? 'stale' : 'fill',
        },
      })
    })
    stationsByIdRef.current = stations
    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }

    const existing = map.getSource('stations') as mapboxgl.GeoJSONSource | undefined
    if (existing) {
      // New readings: the markers update in place (no blink), which reads smoothly during a replay
      existing.setData(data)
      return
    }

    map.addSource('stations', { type: 'geojson', data })
    for (const k of ['good', 'moderate', 'unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous']) {
      for (const shape of ['fill', 'ring', 'diamond', 'stale'] as const) {
        const id = `station-${shape}-${k}`
        if (map.hasImage(id)) continue
        const { data: img, options } = makeMarkerImage(bandColor(k), shape)
        map.addImage(id, img, options)
      }
    }
    // One symbol layer: number inside a round marker. Markers never hide each other (collision
    // hiding made them flicker while zooming); they shrink at country level, and the numbers
    // appear once there is room to read them. Higher PM2.5 draws on top.
    map.addLayer({
      id: 'stations-label', type: 'symbol', source: 'stations', minzoom: 4,
      layout: {
        'icon-image': ['concat', 'station-', ['get', 'shape'], '-', ['get', 'band']],
        'icon-size': ['interpolate', ['linear'], ['zoom'], 3.6, 0.2, 5, 0.27, 6.5, 0.42, 8, 0.72, 9, 0.85, 10, 1], // small dots at country zoom, full size with numbers from zoom 8
        'text-field': ['step', ['zoom'], '', 8, ['get', 'label']],
        'text-size': ['interpolate', ['linear'], ['zoom'], 8, 11, 10, 12],
        'text-font': ['DIN Pro Regular', 'Arial Unicode MS Regular'],
        'symbol-sort-key': ['get', 'pm25'],
        'icon-allow-overlap': true,
        'text-allow-overlap': true,
        'icon-ignore-placement': true,
        'text-ignore-placement': true,
      },
      paint: {
        'text-color': ['get', 'text'],
        // Forecast stations without live readings behind them are shown faded
        'icon-opacity': 1,
        'text-opacity': ['match', ['get', 'shape'], 'stale', 0.55, 1],
        'icon-opacity-transition': { duration: 250, delay: 0 },
        'text-opacity-transition': { duration: 250, delay: 0 },
      },
    })

    let hoveredIdx = -1
    map.on('mousemove', 'stations-label', (e) => {
      map.getCanvas().style.cursor = 'pointer'
      const idx = e.features?.[0]?.properties?.i
      if (typeof idx !== 'number' || idx === hoveredIdx) return
      hoveredIdx = idx
      setHoveredStation(stationsByIdRef.current[idx] ?? null)
    })
    map.on('click', 'stations-label', (e) => {
      const idx = e.features?.[0]?.properties?.i
      if (typeof idx !== 'number') return
      const stn = stationsByIdRef.current[idx]
      if (stn) onFeatureClickRef.current?.({ kind: 'station', station: stn })
    })
    map.on('mouseleave', 'stations-label', () => {
      map.getCanvas().style.cursor = ''
      hoveredIdx = -1
      setHoveredStation(null)
    })
  }, [stations, mapLoaded])

  // A new day or model makes the open district's reading stale
  useEffect(() => { clearDistrictRef.current?.() }, [selectedDate, model])

  // The page asks for the space back
  useEffect(() => { if (closeDistrictSignal) clearDistrictRef.current?.() }, [closeDistrictSignal])
  const districtOpen = !!selectedDistrict
  const onDistrictOpenChangeRef = useRef(onDistrictOpenChange)
  onDistrictOpenChangeRef.current = onDistrictOpenChange
  useEffect(() => { onDistrictOpenChangeRef.current?.(districtOpen) }, [districtOpen])

  // Start loading kilns and industry the first time either layer is switched on
  useEffect(() => {
    if (!mapLoaded || sourcesStartedRef.current || !(showKilns || showIndustry)) return
    sourcesStartedRef.current = true
    void loadSourcesRef.current?.()
  }, [mapLoaded, showKilns, showIndustry])

  // Toggle brick kiln layer visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    const vis = showKilns ? 'visible' : 'none'
    for (const id of ['brick-kilns-layer', 'brick-kilns-glow', 'brick-kilns-dots']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis)
    }
  }, [showKilns, mapLoaded, sourcesReady])

  // Toggle industry layers visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    for (const key of ['power_plants', 'cement_plants', 'steel_sites', 'sugar_mills', 'industrial_sites', 'mines_quarries']) {
      // Mines and quarries have no switch of their own: they follow industrial sites
      const wanted = key === 'mines_quarries' ? 'industrial_sites' : key
      const vis = showIndustry && (!industryKeys || industryKeys.includes(wanted)) ? 'visible' : 'none'
      const layerId = `industry-${key}-layer`
      if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', vis)
      if (map.getLayer(`${layerId}-bg`)) map.setLayoutProperty(`${layerId}-bg`, 'visibility', vis)
    }
  }, [showIndustry, industryKeys, mapLoaded, sourcesReady])

  // Toggle fire layers visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded || !fireSourceAdded.current) return
    const vis = showFires ? 'visible' : 'none'
    for (const id of ['fires-glow', 'fires-glow-1', 'fires-glow-2', 'fires-layer', 'fires-icon']) {
      if (mapRef.current.getLayer(id)) mapRef.current.setLayoutProperty(id, 'visibility', vis)
    }
  }, [showFires, mapLoaded])

  // Sync fire data to the map: the page sends the report's fires (deduplicated, high/nominal),
  // each tagged with its region and the number of detections merged into it
  useEffect(() => {
    if (!mapRef.current || !mapLoaded || !fireSourceAdded.current) return
    const src = mapRef.current.getSource('fires') as mapboxgl.GeoJSONSource | undefined
    if (!src) return
    src.setData((firesData?.features.length ? firesData : { type: 'FeatureCollection', features: [] }) as GeoJSON.FeatureCollection)
  }, [firesData, mapLoaded])

  // A new day or model: the hover readout's cached city grids are stale
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    // Clear cached grids (date changed, grids are stale)
    urbanGridsRef.current.clear()
    urbanGridLoadingRef.current.clear()

    setHoverPM25(null)
  }, [selectedDate, smoothed, model, mapLoaded])

  useEffect(() => { if (!satelliteOn) setHoverPM25(null) }, [satelliteOn])

  useEffect(() => {
    const map = mapRef.current
    if (map?.getLayer('stations-label')) map.setLayoutProperty('stations-label', 'visibility', showStations ? 'visible' : 'none')
  }, [showStations, stations, mapLoaded])

  // ── Redesign layers (mapViz) ──
  const liveMap = mapLoaded ? mapRef.current : null
  useBasemapTuning(liveMap, mapLoaded)
  useEstimateSurface(liveMap, mapLoaded, { grid: estimateGrid, visible: satelliteOn })
  useCitySurfaces(liveMap, mapLoaded, { cities: URBAN_CITIES, date: selectedDate, visible: satelliteOn })
  // Smoke outlook: a city opens its card, and its upwind cone is drawn for the lead in view
  const [outlookCity, setOutlookCity] = useState<string | null>(null)
  // The card opens on today; the other days are one click away
  const [outlookLead, setOutlookLead] = useState('D+0')
  useEffect(() => { if (!showSmoke) setOutlookCity(null) }, [showSmoke])
  // One detail card at a time: a district closes the outlook card, an outlook city closes the district card
  useEffect(() => { if (selectedDistrict) setOutlookCity(null) }, [selectedDistrict])
  useSmokeOutlook(liveMap, mapLoaded, { cities: outlookCities, enabled: showSmoke, selected: outlookCity, onSelect: c => { clearDistrictRef.current?.(); setOutlookCity(c); setOutlookLead('D+0') } })
  const { data: cityOutlook, isLoading: cityOutlookLoading } = useQuery({
    queryKey: ['fires-outlook-city', outlookCity],
    queryFn: () => fetchCityOutlook(outlookCity as string),
    enabled: !!outlookCity,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
  const outlookPoint = outlookCities.find(c => c.city === outlookCity)
  const leadData = cityOutlook?.leads?.find(l => l.lead === outlookLead)
  const cone = useMemo(() => {
    const from = leadData?.wind_850?.from_deg
    if (!outlookPoint || !leadData || from == null) return null
    return {
      lon: outlookPoint.lon, lat: outlookPoint.lat, fromDeg: from,
      radiusKm: Math.min(200, leadData.reach_km ?? 200),
      color: OUTLOOK_BAND_COLOR[(leadData.band ?? 'none') as keyof typeof OUTLOOK_BAND_COLOR],
      fires: (leadData.top_fires ?? []).map(f => ({ lon: f.lon, lat: f.lat })),
    }
  }, [outlookPoint, leadData])
  useOutlookCone(liveMap, mapLoaded, showSmoke ? cone : null)
  useHeatSources(liveMap, mapLoaded, { rows: heatSources, enabled: showFires, windowDays: heatWindowDays })
  useSmokePlumes(liveMap, mapLoaded, { fires: firesData?.features ?? NO_PLUME_FIRES, enabled: showPlumes })
  useFireAnimation(liveMap, mapLoaded, { enabled: showFires, data: firesData })

  // Population density
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    if (map.getLayer('population-layer')) map.removeLayer('population-layer')
    if (map.getSource('population')) map.removeSource('population')
    if (!showPopulation) return
    map.addSource('population', {
      type: 'raster',
      tiles: [`${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png?model=population`],
      tileSize: 256,
      minzoom: 4,
      maxzoom: 14,
      bounds: [60.8, 23.6, 77.9, 37.1],
    })
    map.addLayer({
      id: 'population-layer',
      type: 'raster',
      source: 'population',
      slot: 'middle',
      paint: { 'raster-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.5, 10, 0.6, 14, 0.5] },
    })
  }, [showPopulation, selectedDate, mapLoaded])

  // Wind: the texture is fetched the first time it is turned on
  useEffect(() => {
    if (!showWind || wind) return
    let mounted = true
    ;(async () => {
      try {
        const field = await loadWindField()
        if (field && mounted) setWind({ image: field.image, meta: field.meta })
      } catch (err) {
        console.warn('Wind data fetch failed:', err)
      }
    })()
    return () => { mounted = false }
  }, [showWind, wind])

  // Wind particles outside Pakistan only: inside it, the smoke plumes show where the air goes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded || !wind || !showWind) return
    let renderer: WindParticleRenderer | null = null
    let cancelled = false
    loadCountryPolygons().then(pakistan => {
      if (cancelled || !mapRef.current) return
      try {
        renderer = new WindParticleRenderer(mapRef.current, wind.image, wind.meta, { excludePolygons: pakistan })
        renderer.start()
      } catch (err) {
        console.warn('Wind renderer failed:', err)
      }
    })
    return () => { cancelled = true; renderer?.destroy() }
  }, [wind, showWind, mapLoaded])

  const glass = {
    background: 'rgba(255,255,255,0.82)',
    backdropFilter: 'blur(20px) saturate(180%)',
    WebkitBackdropFilter: 'blur(20px) saturate(180%)',
    border: '1px solid rgba(15,23,42,0.08)',
    boxShadow: '0 8px 32px rgba(15,23,42,0.14)',
  } as const
  const enter = { initial: { opacity: 0, y: -6 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -6 }, transition: { duration: 0.22, ease: [0.2, 0.8, 0.2, 1] as const } }
  const district = selectedDistrict && (() => {
    const band = selectedDistrict.pm25 != null ? classifyPm25(selectedDistrict.pm25) : null
    const rows = [...selectedDistrict.stations].sort((x, y) => y.pm25 - x.pm25)
    return { band, rows }
  })()

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Left-hand map cards in one column: they stack and shrink, never overlap.
          Bottom padding keeps clear of the timeline. */}
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 flex w-[332px] max-w-full flex-col items-start gap-2 p-3 pb-[104px] md:p-4 md:pb-[76px]">
        {leftSlot && <div className="pointer-events-auto shrink-0">{leftSlot}</div>}

        {/* What the PM2.5 surface colours mean */}
        <AnimatePresence initial={false}>
          {mapLoaded && !hideLegend && satelliteOn && (
            <m.div
              key="legend"
              {...enter}
              role="group"
              aria-label="Map key"
              className="w-[210px] shrink-0 rounded-xl px-3 py-2 md:w-[236px]"
              style={{ ...glass, background: 'rgba(255,255,255,0.5)', boxShadow: '0 4px 16px rgba(15,23,42,0.08)' }}
            >
              {satelliteOn && (
                <>
                  <div className="flex items-baseline justify-between gap-2 text-[11px] font-medium text-slate-800">
                    <span className="truncate">PM2.5 estimate, {formatDateOnly(selectedDate, { month: 'short', day: 'numeric' })}</span>
                    <span className="shrink-0 text-slate-600">µg/m³</span>
                  </div>
                  <div
                    className="mt-1.5 h-2 rounded-full"
                    role="img"
                    aria-label={`Satellite estimate colour scale, ${SURFACE_RANGE.min} to ${SURFACE_RANGE.max} µg/m³`}
                    style={{ background: SURFACE_GRADIENT }}
                  />
                  <div className="mt-1 flex justify-between text-[10px] tabular-nums text-slate-600">
                    {SURFACE_TICKS.map((t, i) => (
                      <span key={t}>{i === 0 ? `≤${t}` : i === SURFACE_TICKS.length - 1 ? `${t}+` : t}</span>
                    ))}
                  </div>
                  <AnimatePresence initial={false}>
                    {inCityDetail && (
                      <m.p
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        className="overflow-hidden pt-1 text-[10px] leading-snug text-slate-600"
                      >
                        City detail layer: same colours for {CITY_RANGE.min} to {CITY_RANGE.max} µg/m³
                      </m.p>
                    )}
                  </AnimatePresence>
                </>
              )}
            </m.div>
          )}
        </AnimatePresence>

        {/* Smoke outlook for the clicked city */}
        <AnimatePresence>
          {showSmoke && outlookCity && (
            <m.section key="outlook" {...enter} aria-label={`Smoke outlook for ${outlookCity}`} className="pointer-events-auto flex min-h-0 w-full max-w-[300px] flex-col overflow-hidden rounded-2xl bg-white text-slate-900 shadow-[0_8px_32px_rgba(15,23,42,0.18)] max-md:max-w-none">
              <OutlookCard
                city={outlookCity}
                data={cityOutlook}
                loading={cityOutlookLoading}
                lead={outlookLead}
                onLead={setOutlookLead}
                onClose={() => setOutlookCity(null)}
              />
            </m.section>
          )}
        </AnimatePresence>

        {/* Clicked district: modelled PM2.5 and the stations inside it */}
        <AnimatePresence>
          {selectedDistrict && district && (() => {
            const { band, rows } = district
            return (
              <m.section
                key="district"
                {...enter}
                aria-label={`${selectedDistrict.name} district`}
                className="pointer-events-auto flex min-h-0 w-full max-w-[300px] flex-col overflow-hidden rounded-2xl bg-white text-slate-900 shadow-[0_8px_32px_rgba(15,23,42,0.18)] max-md:max-w-none"
              >
            <div className="shrink-0" style={{ background: band?.color ?? '#f1f5f9', color: band ? cardTextColor(band.key) : '#0f172a' }}>
              <div className="flex items-center justify-between gap-2 px-4 pt-3.5">
                <h3 className="text-[15px] font-semibold tracking-tight truncate">{selectedDistrict.name}</h3>
                <button
                  onClick={() => clearDistrictRef.current?.()}
                  aria-label="Close district panel"
                  className="-mr-1.5 rounded-lg p-1.5 opacity-70 hover:bg-black/10 hover:opacity-100 transition-[background-color,opacity]"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="px-4 pt-1 pb-3.5">
                <div className="text-xs opacity-75">
                  Modelled PM₂.₅{selectedDate ? `, satellite estimate for ${formatDateOnly(selectedDate, { month: 'short', day: 'numeric' })}` : ''}
                </div>
                {/* Reading and category as type, with the band dial: no pill on top of the band colour */}
                <div className="mt-2 flex items-center gap-3.5">
                  <div className="shrink-0">
                    <span className="text-[40px] leading-[0.9] font-semibold tabular-nums tracking-tight">
                      {selectedDistrict.pm25 != null ? Math.round(selectedDistrict.pm25) : '—'}
                    </span>
                    <span className="ml-1 text-xs font-medium opacity-75">µg/m³</span>
                  </div>
                  {band && (
                    <>
                      <span className={`ml-1 min-w-0 flex-1 font-semibold text-balance ${band.label.length > 16 ? 'text-[13px] leading-snug' : 'text-[15px] leading-tight'}`}>{band.label}</span>
                      <GaugeIcon band={band.key} aqi={pm25ToAqi(selectedDistrict.pm25)} color={cardTextColor(band.key)} />
                    </>
                  )}
                </div>
              </div>
            </div>
            {rows.length > 0 && (
              <div className="min-h-0 flex flex-col">
                <div className="px-4 pt-2.5 pb-1 text-xs font-semibold text-slate-600">
                  {rows.length} station{rows.length > 1 ? 's' : ''}, {(stationCaption ?? 'PM2.5 daily mean').replace(/^./, c => c.toLowerCase())}
                </div>
                <ul className="overflow-y-auto overscroll-contain scrollbar-hide px-2 pb-2">
                  {rows.map((stn, i) => {
                    const b = classifyPm25(stn.pm25)
                    return (
                      <li key={i}>
                        {/* Opens the station, as a click on its marker does, and moves the map to it */}
                        <button
                          onClick={() => {
                            onFeatureClickRef.current?.({ kind: 'station', station: stn })
                            const lon = stn.lon ?? stn.longitude, lat = stn.lat ?? stn.latitude
                            const map = mapRef.current
                            if (map && lon != null && lat != null) map.easeTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 11), duration: 900 })
                          }}
                          aria-label={`Open ${stn.name}`}
                          className="group flex w-full items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-slate-900/[0.05] focus-visible:bg-slate-900/[0.05]"
                        >
                          <span className="truncate text-slate-800 group-hover:text-slate-950">{stn.name}</span>
                          <span className="min-w-[40px] shrink-0 rounded-full px-2.5 py-0.5 text-center text-xs font-semibold tabular-nums" style={{ background: b.color, color: b.textColor }} title={b.label}>
                            {Math.round(stn.pm25)}
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
              </m.section>
            )
          })()}
        </AnimatePresence>

        {/* Station hover card (desktop): last in the column, so it sits low and the district card above it shrinks to fit */}
        <AnimatePresence>
          {hoveredStation && (
            <m.div
              key="hover"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
              className="mt-auto w-[300px] shrink-0 max-md:hidden"
            >
              <AqiCard
                pm25={hoveredStation.pm25}
                title={hoveredStation.name}
                subtitle={hoveredStation.city}
                caption={[
                  stationCaption ?? (hoveredStation.valid_hours != null ? `${hoveredStation.valid_hours}-hour mean PM2.5` : 'Daily mean PM2.5'),
                  hoveredStation.basis === 'neighbours' ? 'Estimated from nearby stations (no live data here)'
                    : hoveredStation.basis === 'prior' ? 'Model estimate only (no live data nearby)' : null,
                ].filter(Boolean).join(' · ')}
              />
            </m.div>
          )}
        </AnimatePresence>

        {/* Urban grid hover readout */}
        <AnimatePresence>
          {hoverPM25 && !hoveredStation && !selectedDistrict && (
            <m.div
              key="urban"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.16 }}
              className="mt-auto shrink-0 rounded-xl px-3 py-2"
              style={glass}
            >
              <div className="text-[11px] text-emerald-700 font-semibold tracking-wide">{hoverPM25.label}</div>
              <div className="flex items-baseline gap-1 mt-0.5">
                <span className="text-xl font-semibold tabular-nums text-slate-900">{hoverPM25.pm25.toFixed(1)}</span>
                <span className="text-xs text-slate-600">µg/m³</span>
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {!mapLoaded && (
          <m.div
            key="loading"
            exit={{ opacity: 0 }}
            transition={{ duration: 0.35 }}
            className="absolute inset-0 flex items-center justify-center bg-slate-100"
          >
            <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}

const COMPASS_WORDS: Record<string, string> = {
  N: 'north', NNE: 'north-north-east', NE: 'north-east', ENE: 'east-north-east', E: 'east', ESE: 'east-south-east', SE: 'south-east', SSE: 'south-south-east',
  S: 'south', SSW: 'south-south-west', SW: 'south-west', WSW: 'west-south-west', W: 'west', WNW: 'west-north-west', NW: 'north-west', NNW: 'north-north-west',
}
const BAND_STEPS: OutlookBand[] = ['low', 'elevated', 'high', 'very_high']

/** A small figure with its label, for the outlook card's three tiles. */
function Stat({ value, label, children }: { value: React.ReactNode; label: string; children?: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl bg-slate-900/[0.04] px-2.5 py-2">
      <div className="flex items-center gap-1 truncate text-[15px] font-semibold tabular-nums text-slate-900">{children}{value}</div>
      <div className="mt-0.5 truncate text-[11px] leading-tight text-slate-600">{label}</div>
    </div>
  )
}

/**
 * One city's smoke outlook (fire report §9), read in a glance: the band for the day in view on a four-step meter,
 * one plain sentence and three figures; the strongest fires and the method sit under "Details".
 */
function OutlookCard({ city, data, loading, lead, onLead, onClose }: {
  city: string
  data: Awaited<ReturnType<typeof fetchCityOutlook>> | undefined
  loading: boolean
  lead: string
  onLead: (lead: string) => void
  onClose: () => void
}) {
  const [showDetails, setShowDetails] = useState(false)
  const leads = data?.leads ?? []
  const l = leads.find(x => x.lead === lead) ?? leads[0]
  const band = (l?.band ?? 'none') as OutlookBand
  const level = BAND_STEPS.indexOf(band) + 1 // 0 for none
  const fmt = (n: number | null | undefined) => (n == null ? '—' : Math.round(n).toLocaleString('en-US'))
  const dayWord = !l ? '' : l.lead === 'D+0' ? 'today' : l.lead === 'D+1' ? 'tomorrow' : `on ${formatDateOnly(l.day, { weekday: 'long' })}`
  const fires = l ? (l.fires_reachable ?? l.fires_in_cone ?? 0) : 0
  const wind = l?.wind_850

  // The plain sentence: where the wind comes from, how many fires, and where most of them are
  const sentence = (() => {
    if (!l) return ''
    if (band === 'none' || !fires) return `Little or no fire upwind of ${city} ${dayWord}.`
    const from = wind?.from_compass ? COMPASS_WORDS[wind.from_compass] ?? wind.from_compass : null
    const top = l.top_fires ?? []
    const counts = new Map<string, number>()
    for (const f of top) { const k = f.district ?? f.country; counts.set(k, (counts.get(k) ?? 0) + 1) }
    const place = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
    const hours = top.length ? Math.round(top.reduce((a, f) => a + f.transport_h, 0) / top.length) : null
    return `${from ? `Wind from the ${from}` : 'The wind'} carries smoke toward ${city} from ${fmt(fires)} fires${place ? `, most near ${place}` : ''}${hours != null ? `, about ${hours} hour${hours === 1 ? '' : 's'} away` : ''}.`
  })()

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex items-start justify-between gap-2 px-4 pt-3.5">
        <div className="min-w-0">
          <h3 className="truncate text-[15px] font-semibold leading-tight tracking-tight">{city}</h3>
          <div className="mt-0.5 text-xs text-slate-500">Smoke outlook</div>
        </div>
        <button onClick={onClose} aria-label="Close smoke outlook" className="-mr-1.5 -mt-0.5 rounded-lg p-1.5 text-slate-500 transition-colors hover:bg-slate-900/5 hover:text-slate-900">
          <X size={16} />
        </button>
      </div>

      {loading && <div className="px-4 py-4 text-xs text-slate-500">Loading the outlook…</div>}
      {!loading && (!data || data.status === 'unavailable' || !leads.length) && (
        <div className="px-4 py-4 text-xs text-slate-600">{data?.message ?? 'No smoke outlook for this city yet.'}</div>
      )}

      {l && (
        <div className="min-h-0 overflow-y-auto overscroll-contain scrollbar-hide px-4 pb-3.5">
          {/* Days: each with its band, so they compare without clicking */}
          <div className="mt-2.5 grid grid-cols-4 gap-1 rounded-xl bg-slate-900/[0.04] p-1" role="tablist" aria-label="Day">
            {leads.map(x => {
              const on = x.lead === l.lead
              const b = (x.band ?? 'none') as OutlookBand
              return (
                <button
                  key={x.lead}
                  role="tab"
                  aria-selected={on}
                  onClick={() => onLead(x.lead)}
                  className={`relative rounded-lg px-1 py-1.5 text-center transition-colors ${on ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900'}`}
                >
                  {on && <m.span layoutId="outlook-day" transition={{ type: 'spring', stiffness: 450, damping: 36 }} className="absolute inset-0 rounded-lg bg-white shadow-sm" />}
                  <span className="relative block text-[11px] font-semibold">{x.lead === 'D+0' ? 'Today' : formatDateOnly(x.day, { weekday: 'short' })}</span>
                  <span className="relative mt-0.5 flex items-center justify-center gap-1 text-[10px] text-slate-500">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: OUTLOOK_BAND_COLOR[b] }} />
                    {b === 'very_high' ? 'V. high' : OUTLOOK_BAND_LABEL[b]}
                  </span>
                </button>
              )
            })}
          </div>

          {/* The answer: band, its place on the scale, and one sentence */}
          <div className="mt-3.5 flex items-end justify-between gap-3">
            <div>
              <div className="text-[22px] font-semibold leading-none tracking-tight" style={{ color: level ? undefined : '#64748b' }}>{OUTLOOK_BAND_LABEL[band]}</div>
              <div className="mt-1 text-xs text-slate-500">fires upwind {dayWord}</div>
            </div>
            <div className="flex shrink-0 gap-1 pb-0.5" role="img" aria-label={`${OUTLOOK_BAND_LABEL[band]}, ${level} of 4 on the outlook scale`}>
              {BAND_STEPS.map((s, i) => (
                <span key={s} className="h-2 w-6 rounded-full transition-colors duration-300" style={{ background: i < level ? OUTLOOK_BAND_COLOR[s] : 'rgba(15,23,42,0.08)' }} />
              ))}
            </div>
          </div>
          <p className="mt-2.5 text-[13px] leading-snug text-slate-700">{sentence}</p>
          {l.status === 'no_forecast' && <p className="mt-1 text-xs text-amber-700">No wind forecast for this day.</p>}

          {/* Three figures */}
          <div className="mt-3 grid grid-cols-3 gap-1.5">
            <Stat value={<>{fmt(l.upwind_load_mw)}<span className="text-[11px] font-medium text-slate-500">MW</span></>} label="fire power upwind" />
            <Stat value={wind?.from_compass ?? '—'} label={wind?.speed_ms != null ? `wind, ${wind.speed_ms.toFixed(1)} m/s` : 'wind'}>
              {wind?.from_deg != null && (
                <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 shrink-0 text-slate-700" style={{ transform: `rotate(${(wind.from_deg + 180) % 360}deg)` }} aria-hidden>
                  <path d="M8 1.5 L12 8 H9.2 V14.5 H6.8 V8 H4 Z" fill="currentColor" />
                </svg>
              )}
            </Stat>
            <Stat value={fmt(fires)} label={`fires in the cone`} />
          </div>

          {/* The numbers behind it */}
          <button
            onClick={() => setShowDetails(v => !v)}
            aria-expanded={showDetails}
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-slate-600 transition-colors hover:text-slate-900"
          >
            {showDetails ? 'Fewer details' : 'Strongest fires and method'}
            <ChevronDown size={14} className={`transition-transform duration-200 ${showDetails ? 'rotate-180' : ''}`} aria-hidden />
          </button>
          <AnimatePresence initial={false}>
            {showDetails && (
              <m.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
                className="overflow-hidden"
              >
                {(l.top_fires?.length ?? 0) > 0 && (
                  <ul className="mt-2 divide-y divide-slate-900/[0.06]">
                    {l.top_fires!.slice(0, 3).map((f, i) => (
                      <li key={i} className="flex items-center justify-between gap-3 py-1.5">
                        <div className="min-w-0">
                          <div className="truncate text-[13px] font-medium text-slate-800">{f.district ?? f.country}</div>
                          <div className="text-[11px] text-slate-500">{Math.round(f.km)} km {f.direction ?? ''}, about {Math.round(f.transport_h)} h away</div>
                        </div>
                        <div className="shrink-0 text-xs font-semibold tabular-nums text-slate-700">{Math.round(f.frp_mw)} MW</div>
                      </li>
                    ))}
                  </ul>
                )}
                {l.by_country && Object.keys(l.by_country).length > 0 && (
                  <div className="mt-1.5 text-[11px] text-slate-500">
                    Fires in the cone: {Object.entries(l.by_country).filter(([, n]) => n > 0).map(([c, n]) => `${c} ${n}`).join(', ')}
                  </div>
                )}
                <p className="mt-2 text-[11px] leading-snug text-slate-500">
                  The band measures the fire power upwind: fires within ±60° of the wind at 850 hPa and within a day&apos;s travel ({Math.round(Math.min(200, l.reach_km ?? 200))} km), from today&apos;s and yesterday&apos;s fires, assumed to keep burning.
                  {data?.generated_at ? ` Issued ${formatPkt(data.generated_at)}.` : ''}
                </p>
              </m.div>
            )}
          </AnimatePresence>

          {data?.status === 'stale' && <p className="mt-2 text-xs text-amber-700">This outlook is more than six hours old.</p>}
        </div>
      )}
    </div>
  )
}
