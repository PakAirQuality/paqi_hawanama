"use client"

import { useRef, useState, useEffect } from 'react'
import { canRenderMap, type MapErrorEvent, type MapUnavailableReason } from '@/lib/webgl'
import { INVENTORY_NOTE, loadEmissionSources, loadKilnsGeoJSON } from '@/lib/staticLayers'
import { formatPkt } from '@/lib/time'
import { bandKey, normalizeBand, bandColor, classifyPm25 } from '@/lib/aqi'
import { esc } from '@/lib/html'
import { AqiCard } from '@/components/shared/AqiCard'
import { WindParticleRenderer, type WindMetadata } from '@/components/analyst-desk/WindParticleLayer'
import { Loader2 } from 'lucide-react'
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
}

interface PredictionMapProps {
  selectedDate: string
  smoothed?: boolean
  model?: 'backbone' | 'support_aware'
  showKilns?: boolean
  showIndustry?: boolean
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

/** Station markers draw above kilns and industry, so a click on one belongs to the station. */
function hitsStation(map: mapboxgl.Map, e: mapboxgl.MapMouseEvent): boolean {
  return !!map.getLayer('stations-label') && map.queryRenderedFeatures(e.point, { layers: ['stations-label'] }).length > 0
}

// Zoom range: a whole-country view at the lowest level (fits a phone), street level at the highest
const MIN_ZOOM = 3.6
const MAX_ZOOM = 16

const PAKISTAN_BOUNDS: [[number, number], [number, number]] = [[60.8, 23.5], [77.9, 37.2]]
const SUMMARY_CARD_PX = 380 // the floating card's width plus its margin
const PANEL_SETTLE_MS = 350 // the side panel's spring has finished by then

export function PredictionMap({ selectedDate, smoothed = false, model = 'backbone', showKilns = true, showIndustry = false, showFires = false, firesData = null, stations: stationsProp, onMapUnavailable, onMapReady, onFeatureClick, userLocation, panelOpen = false, showStations = true, showSurface = true, showWind = false, showPopulation = false, stationCaption }: PredictionMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [, setHoveredDistrict] = useState<string | null>(null)
  const [hoverPM25, setHoverPM25] = useState<HoverPM25 | null>(null)

  // Station markers
  const [stations, setStations] = useState<StationReading[]>([])
  const [hoveredStation, setHoveredStation] = useState<StationReading | null>(null)

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
      attributionControl: true,
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
      const [districtsGeoJSON, adm1GeoJSON, dissolvedGeoJSON] = await Promise.all([
        fetch('/pakistan_districts.geojson').then(r => r.json()),
        fetch('/pakistan_adm1.geojson').then(r => r.json()),
        fetch('/pakistan_adm2_dissolved.geojson').then(r => r.json()),
      ])

      // Add sources
      map.addSource('pakistan-districts', { type: 'geojson', data: districtsGeoJSON, promoteId: 'shapeName' })
      map.addSource('pakistan-adm1', { type: 'geojson', data: adm1GeoJSON })
      map.addSource('pakistan-boundary', { type: 'geojson', data: dissolvedGeoJSON })

      // National COG tile source
      const params = [smoothed && 'smoothed=true', model !== 'backbone' && `model=${model}`].filter(Boolean).join('&')
      const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png${params ? '?' + params : ''}`
      map.addSource('pm25-tiles', {
        type: 'raster',
        tiles: [tileUrl],
        tileSize: 256,
        bounds: [60.45, 23.25, 77.95, 37.35],
        minzoom: 0,
        maxzoom: 12,
      })

      // 1. National PM2.5 raster — the hero layer
      //    Far: strong presence. Close: yields to downscaler + contextual layers.
      map.addLayer({
        id: 'pm25-raster',
        type: 'raster',
        source: 'pm25-tiles',
        slot: 'middle',
        paint: {
          'raster-opacity': [
            'interpolate', ['linear'], ['zoom'],
            3, 0.7,
            7, 0.65,
            9, 0.4,
            12, 0.2,
          ],
          'raster-resampling': 'linear',
        },
      })

      // ── Urban 1km downscaler layers (overlay at high zoom) ──
      for (const city of URBAN_CITIES) {
        const srcId = `urban-${city.key}`
        const layerId = `urban-${city.key}-layer`
        try {
          map.addSource(srcId, {
            type: 'raster',
            tiles: [
              `${API_BASE}/api/v1/ops/downscaler/tiles/${city.key}/${selectedDate}/{z}/{x}/{y}.png?smoothed=true`,
            ],
            tileSize: 256,
            minzoom: 9,
            maxzoom: 15,
            bounds: city.bounds,
          })
          map.addLayer({
            id: layerId,
            type: 'raster',
            source: srcId,
            minzoom: 9,
            paint: {
              'raster-opacity': [
                'interpolate', ['linear'], ['zoom'],
                9, 0,
                10, 0.35,
                11, 0.55,
                13, 0.65,
                15, 0.5,
              ],
            },
            slot: 'middle',
          })
        } catch (e) {
          console.warn(`[Urban] Failed to add ${layerId}:`, e)
        }
      }

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

        // Small amber dots — the earliest hint (z8.5-10)
        map.addLayer({
          id: 'brick-kilns-dots', type: 'circle', source: 'brick-kilns',
          minzoom: 8.5,
          maxzoom: 11,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 8.5, 1, 10, 2.5],
            'circle-color': '#d97706',
            'circle-opacity': ['interpolate', ['linear'], ['zoom'],
              8.5, 0,
              9.5, 0.25,
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

        // Hover popup — z10+
        const kilnPopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '220px' })

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

        const industryPopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '220px' })

        for (const layer of INDUSTRY_LAYERS) {
          if (!srcData[layer.key]?.features?.length) continue
          const srcId = `industry-${layer.key}`
          const layerId = `industry-${layer.key}-layer`

          map.addSource(srcId, { type: 'geojson', data: srcData[layer.key] })

          // Background glow circle
          map.addLayer({
            id: `${layerId}-bg`, type: 'circle', source: srcId,
            minzoom: 7,
            layout: { visibility: 'none' },
            paint: {
              'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 4, 10, 10, 12, 14],
              'circle-color': layer.color,
              'circle-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0, 8.5, 0.15, 10, 0.25, 12, 0.3],
              'circle-blur': 0.8,
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

      // 7. Country outline
      map.addLayer({
        id: 'country-outline', type: 'line', source: 'pakistan-boundary',
        paint: { 'line-color': '#64748b', 'line-width': 1.5, 'line-opacity': 0.9 }
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
      const firePopup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, maxWidth: '200px' })

      map.on('mouseenter', 'fires-layer', (e) => {
        if (!e.features?.[0]) return
        map.getCanvas().style.cursor = 'pointer'
        const props = e.features[0].properties!
        const coords = (e.features[0].geometry as GeoJSON.Point).coordinates.slice() as [number, number]
        firePopup.setLngLat(coords).setHTML(`
          <div style="font-family:system-ui,-apple-system,sans-serif;font-size:12px;line-height:1.5">
            <div style="font-weight:600;color:#ea580c;margin-bottom:4px">Satellite fire detection</div>
            <div>FRP: <b>${esc(props.frp)} MW</b> <span style="color:#94a3b8">(radiative power)</span></div>
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
          text: '#0f172a',
        },
      })
    })
    stationsByIdRef.current = stations
    const data: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features }

    const existing = map.getSource('stations') as mapboxgl.GeoJSONSource | undefined
    if (existing) {
      // New day: dip the markers, swap the data, bring them back (reads as one soft change)
      if (map.getLayer('stations-label')) {
        map.setPaintProperty('stations-label', 'icon-opacity', 0.15)
        map.setPaintProperty('stations-label', 'text-opacity', 0.15)
      }
      existing.setData(data)
      const t = setTimeout(() => {
        if (!map.getLayer('stations-label')) return
        map.setPaintProperty('stations-label', 'icon-opacity', 1)
        map.setPaintProperty('stations-label', 'text-opacity', 1)
      }, 180)
      return () => clearTimeout(t)
    }

    map.addSource('stations', { type: 'geojson', data })
    for (const k of ['good', 'moderate', 'unhealthy_sensitive', 'unhealthy', 'very_unhealthy', 'hazardous']) {
      const id = `station-pill-${k}`
      if (map.hasImage(id)) continue
      const { data: img, options } = makeCircleImage(bandColor(k))
      map.addImage(id, img, options)
    }
    // One symbol layer: number inside a round marker. Markers never hide each other (collision
    // hiding made them flicker while zooming); they shrink at country level, and the numbers
    // appear once there is room to read them. Higher PM2.5 draws on top.
    map.addLayer({
      id: 'stations-label', type: 'symbol', source: 'stations', minzoom: 4,
      layout: {
        'icon-image': ['concat', 'station-pill-', ['get', 'band']],
        'icon-size': ['interpolate', ['linear'], ['zoom'], 4, 0.42, 6, 0.6, 8, 0.85, 10, 1],
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
    const vis = showIndustry ? 'visible' : 'none'
    for (const key of ['power_plants', 'cement_plants', 'steel_sites', 'sugar_mills', 'industrial_sites', 'mines_quarries']) {
      const layerId = `industry-${key}-layer`
      if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', vis)
      if (map.getLayer(`${layerId}-bg`)) map.setLayoutProperty(`${layerId}-bg`, 'visibility', vis)
    }
  }, [showIndustry, mapLoaded, sourcesReady])

  // Toggle fire layers visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded || !fireSourceAdded.current) return
    const vis = showFires ? 'visible' : 'none'
    for (const id of ['fires-glow', 'fires-layer']) {
      if (mapRef.current.getLayer(id)) mapRef.current.setLayoutProperty(id, 'visibility', vis)
    }
  }, [showFires, mapLoaded])

  // Sync fire data to map source (await boundary load for Pakistan filtering)
  useEffect(() => {
    if (!mapRef.current || !mapLoaded || !fireSourceAdded.current) return
    const src = mapRef.current.getSource('fires') as mapboxgl.GeoJSONSource | undefined
    if (!src) return
    if (firesData && firesData.features.length > 0) {
      ;(async () => {
        await loadPakBoundary()
        src.setData({
          ...firesData,
          features: firesData.features.filter(f => {
            const [lng, lat] = (f.geometry as GeoJSON.Point).coordinates
            return isInsidePakistan(lng, lat)
          }),
        } as GeoJSON.FeatureCollection)
      })()
    } else {
      src.setData({ type: 'FeatureCollection', features: [] })
    }
  }, [firesData, mapLoaded])

  // Update tile sources when date/smoothed/model changes
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current

    // ── Update national tiles ──
    const params = [smoothed && 'smoothed=true', model !== 'backbone' && `model=${model}`].filter(Boolean).join('&')
    const tileUrl = `${API_BASE}/api/v1/ops/pipeline/tiles/${selectedDate}/{z}/{x}/{y}.png${params ? '?' + params : ''}`

    if (map.getLayer('pm25-raster')) map.removeLayer('pm25-raster')
    if (map.getSource('pm25-tiles')) map.removeSource('pm25-tiles')

    map.addSource('pm25-tiles', {
      type: 'raster',
      tiles: [tileUrl],
      tileSize: 256,
      bounds: [60.45, 23.25, 77.95, 37.35],
      minzoom: 0,
      maxzoom: 12,
    })
    map.addLayer({
      id: 'pm25-raster',
      type: 'raster',
      source: 'pm25-tiles',
      slot: 'middle',
      paint: {
        'raster-opacity': [
          'interpolate', ['linear'], ['zoom'],
          3, 0.7,
          7, 0.65,
          9, 0.4,
          12, 0.2,
        ],
        'raster-resampling': 'linear',
      },
    })

    // ── Update urban tiles ──
    for (const city of URBAN_CITIES) {
      const srcId = `urban-${city.key}`
      const layerId = `urban-${city.key}-layer`
      try {
        if (map.getLayer(layerId)) map.removeLayer(layerId)
        if (map.getSource(srcId)) map.removeSource(srcId)

        map.addSource(srcId, {
          type: 'raster',
          tiles: [`${API_BASE}/api/v1/ops/downscaler/tiles/${city.key}/${selectedDate}/{z}/{x}/{y}.png?smoothed=true`],
          tileSize: 256,
          minzoom: 9,
          maxzoom: 15,
          bounds: city.bounds,
        })
        map.addLayer({
          id: layerId,
          type: 'raster',
          source: srcId,
          minzoom: 9,
          paint: {
            'raster-opacity': [
              'interpolate', ['linear'], ['zoom'],
              9, 0,
              10, 0.35,
              11, 0.55,
              13, 0.65,
              15, 0.5,
            ],
          },
          slot: 'middle',
        })
      } catch (e) {
        console.warn(`[Urban] Failed to update ${layerId}:`, e)
      }
    }

    // Clear cached grids (date changed, grids are stale)
    urbanGridsRef.current.clear()
    urbanGridLoadingRef.current.clear()

    setHoverPM25(null)
  }, [selectedDate, smoothed, model, mapLoaded])

  // Declared after the tile effect, which re-creates these layers visible
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapLoaded) return
    const vis = showSurface ? 'visible' : 'none'
    for (const id of ['pm25-raster', ...URBAN_CITIES.map(c => `urban-${c.key}-layer`)]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis)
    }
    if (!showSurface) setHoverPM25(null)
  }, [showSurface, selectedDate, smoothed, model, mapLoaded])

  useEffect(() => {
    const map = mapRef.current
    if (map?.getLayer('stations-label')) map.setLayoutProperty('stations-label', 'visibility', showStations ? 'visible' : 'none')
  }, [showStations, stations, mapLoaded])

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
        const [texture, metadata] = await Promise.all([
          fetch(`${API_BASE}/api/v1/data-sources/wind/texture`),
          fetch(`${API_BASE}/api/v1/data-sources/wind/metadata`),
        ])
        if (!texture.ok || !metadata.ok) return
        const [blob, meta] = await Promise.all([texture.blob(), metadata.json()])
        const image = new Image()
        image.crossOrigin = 'anonymous'
        await new Promise<void>((resolve, reject) => {
          image.onload = () => resolve()
          image.onerror = () => reject(new Error('Failed to decode wind texture'))
          image.src = URL.createObjectURL(blob)
        })
        if (mounted) setWind({ image, meta })
      } catch (err) {
        console.warn('Wind data fetch failed:', err)
      }
    })()
    return () => { mounted = false }
  }, [showWind, wind])

  useEffect(() => {
    if (!mapRef.current || !mapLoaded || !wind || !showWind) return
    let renderer: WindParticleRenderer | null = null
    try {
      renderer = new WindParticleRenderer(mapRef.current, wind.image, wind.meta)
      renderer.start()
    } catch (err) {
      console.warn('Wind renderer failed:', err)
    }
    return () => renderer?.destroy()
  }, [wind, showWind, mapLoaded])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Station hover tooltip */}
      {hoveredStation && (
        <div className="absolute bottom-20 left-4 z-20 w-[300px] pointer-events-none max-md:hidden">
          <AqiCard
            pm25={hoveredStation.pm25}
            title={hoveredStation.name}
            subtitle={hoveredStation.city}
            caption={stationCaption ?? (hoveredStation.valid_hours != null ? `${hoveredStation.valid_hours}-hour mean PM2.5` : 'Daily mean PM2.5')}
          />
        </div>
      )}

      {/* Urban grid hover readout */}
      {hoverPM25 && !hoveredStation && (
        <div className="absolute bottom-16 left-4 z-20 bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-slate-200/60 px-3 py-2">
          <div className="text-[11px] text-emerald-600 font-semibold tracking-wide">{hoverPM25.label}</div>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-xl font-bold text-slate-900">{hoverPM25.pm25.toFixed(1)}</span>
            <span className="text-xs text-slate-500">µg/m³</span>
          </div>
        </div>
      )}

      {/* District hover tooltip removed — district name visible on click in sidebar */}

      {!mapLoaded && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-100">
          <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
        </div>
      )}
    </div>
  )
}

