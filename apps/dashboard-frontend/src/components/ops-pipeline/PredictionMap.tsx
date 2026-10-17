"use client"

import { useRef, useState, useEffect } from 'react'
import { canRenderMap, type MapUnavailableReason } from '@/lib/webgl'
import { INVENTORY_NOTE, loadEmissionSources, loadKilnsGeoJSON } from '@/lib/staticLayers'
import { formatPkt } from '@/lib/time'
import { bandKey, markerClass, normalizeBand, bandColor } from '@/lib/aqi'
import { esc } from '@/lib/html'
import { useRouter } from 'next/navigation'
import { Loader2, X } from 'lucide-react'
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
const INITIAL_ZOOM = 3.5

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
  onMapUnavailable?: (reason: MapUnavailableReason) => void
  onMapReady?: (flyTo: (lng: number, lat: number, zoom?: number) => void) => void
}

interface SelectedDistrict {
  name: string
  pm25: number | null
  stations: StationReading[]
}

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

function bandToMarkerClass(band: string): string {
  switch (normalizeBand(band)) {
    case 'good': return 'bg-good'
    case 'moderate': return 'bg-moderate'
    case 'unhealthy_sensitive': return 'bg-unhealthy-sensitive'
    case 'unhealthy': return 'bg-unhealthy'
    case 'very_unhealthy': return 'bg-very-unhealthy'
    case 'hazardous': return 'bg-hazardous'
    default: return 'bg-no-reading'
  }
}

const BAND_COLORS: Record<string, string> = new Proxy({}, { get: (_t, k: string) => bandColor(k) })

function createMarkerEl(value: number | null | undefined, colorClass: string): HTMLDivElement {
  const container = document.createElement('div')
  container.className = 'aqi-marker-container point'
  container.style.cssText = 'width:28px;display:flex;flex-direction:column;align-items:center;'

  const marker = document.createElement('div')
  marker.className = `aqi-marker ${colorClass}`
  marker.textContent = value != null ? `${Math.round(value)}` : '-'

  const stem = document.createElement('div')
  stem.className = 'aqi-stem'
  stem.style.cssText = 'width:1.5px;height:0px;background:rgba(0,0,0,0.25);transition:height 0.3s;'

  const dot = document.createElement('div')
  dot.className = 'aqi-ground-dot'
  dot.style.cssText = 'width:4px;height:2px;border-radius:50%;background:rgba(0,0,0,0.15);transition:opacity 0.3s;opacity:0;'

  container.appendChild(marker)
  container.appendChild(stem)
  container.appendChild(dot)
  return container
}

export function PredictionMap({ selectedDate, smoothed = false, model = 'backbone', showKilns = true, showIndustry = false, showFires = false, firesData = null, stations: stationsProp, onMapUnavailable, onMapReady }: PredictionMapProps) {
  const router = useRouter()
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapRef = useRef<mapboxgl.Map | null>(null)
  const [mapLoaded, setMapLoaded] = useState(false)
  const [hoveredDistrict, setHoveredDistrict] = useState<string | null>(null)
  const [selectedDistrict, setSelectedDistrict] = useState<SelectedDistrict | null>(null)
  const [hoverPM25, setHoverPM25] = useState<HoverPM25 | null>(null)

  // Station markers
  const markersRef = useRef<mapboxgl.Marker[]>([])
  const [stations, setStations] = useState<StationReading[]>([])
  const stationsRef = useRef<StationReading[]>([])
  const [hoveredStation, setHoveredStation] = useState<StationReading | null>(null)

  // Fire layer refs
  const fireSourceAdded = useRef(false)
  const firesRef = useRef(firesData)
  firesRef.current = firesData

  // Current selection for handlers registered once at map creation (the district click
  // used to read the first render's date and model for the rest of the session).
  const selRef = useRef({ selectedDate, model, smoothed })
  selRef.current = { selectedDate, model, smoothed }
  const onMapUnavailableRef = useRef(onMapUnavailable)
  onMapUnavailableRef.current = onMapUnavailable
  const zoomHandlerRef = useRef<(() => void) | null>(null)
  const pointAbortRef = useRef<AbortController | null>(null)

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
      stationsRef.current = stationsProp
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
          stationsRef.current = s
        } else {
          setStations([])
          stationsRef.current = []
        }
      } catch {
        setStations([])
        stationsRef.current = []
      }
    }
    fetchStations()
  }, [selectedDate, stationsProp])

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
      zoom: INITIAL_ZOOM,
      minZoom: 2,
      maxZoom: 15,
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
    map.on('error', (ev: any) => {
      const status = ev?.error?.status ?? ev?.error?.statusCode
      if (status === 404 || status === 400) return
      if (ev?.sourceId || ev?.tile) return
      console.warn('[map] error', ev?.error?.message ?? ev)
    })
    map.getCanvas().addEventListener('webglcontextlost', () => {
      onMapUnavailableRef.current?.('context-lost')
    })

    // Expose flyTo callback to parent
    onMapReady?.((lng: number, lat: number, zoom?: number) => {
      map.flyTo({ center: [lng, lat], zoom: zoom ?? 12, duration: 1200 })
    })

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
        }
      } catch (e) {
        console.warn('[Industry] Failed to load:', e)
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
            features: firesRef.current.features.filter((f: any) => {
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
          map.getCanvas().style.cursor = 'pointer'
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

      // Click handler - select district and fetch PM2.5
      let selectedId: string | null = null

      map.on('click', 'districts-fill', async (e) => {
        if (!e.features || e.features.length === 0) return
        const feature = e.features[0]
        const districtName = feature.properties?.shapeName
        const newId = districtName

        if (selectedId) map.setFeatureState({ source: 'pakistan-districts', id: selectedId }, { selected: false })
        selectedId = newId
        map.setFeatureState({ source: 'pakistan-districts', id: newId }, { selected: true })

        let centroid: [number, number]
        if (feature.geometry.type === 'Polygon') {
          centroid = getCentroid((feature.geometry as any).coordinates[0])
        } else if (feature.geometry.type === 'MultiPolygon') {
          const largest = (feature.geometry as any).coordinates.reduce((a: any, b: any) =>
            a[0].length > b[0].length ? a : b
          )
          centroid = getCentroid(largest[0])
        } else {
          centroid = [e.lngLat.lng, e.lngLat.lat]
        }

        // Find stations in this district by city name match
        const districtLower = (districtName ?? '').toLowerCase()
        const districtStations = stationsRef.current.filter(s => {
          const city = (s.city ?? '').toLowerCase()
          return city.includes(districtLower) || districtLower.includes(city)
        })

        try {
          // Read the live selection (not the first render's) and cancel any earlier point query
          const sel = selRef.current
          const extraParams = [sel.smoothed && 'smoothed=true', sel.model !== 'backbone' && `model=${sel.model}`].filter(Boolean).map(p => '&' + p).join('')
          pointAbortRef.current?.abort()
          const ac = new AbortController()
          pointAbortRef.current = ac
          const res = await fetch(
            `${API_BASE}/api/v1/ops/pipeline/tiles/${sel.selectedDate}/point?lat=${centroid[1]}&lon=${centroid[0]}${extraParams}`,
            { signal: ac.signal }
          )
          if (res.ok) {
            const data = await res.json()
            setSelectedDistrict({ name: districtName, pm25: data.pm25, stations: districtStations })
          } else {
            setSelectedDistrict({ name: districtName, pm25: null, stations: districtStations })
          }
        } catch {
          setSelectedDistrict({ name: districtName, pm25: null, stations: districtStations })
        }
      })

      map.on('click', (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ['districts-fill'] })
        if (features.length === 0 && selectedId) {
          map.setFeatureState({ source: 'pakistan-districts', id: selectedId }, { selected: false })
          selectedId = null
          setSelectedDistrict(null)
        }
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
      pointAbortRef.current?.abort()
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [])

  // Dedicated BAM reference-monitor marker — always shown, opens the /bam QC page.
  // Independent of the daily-aggregate `stations` list (BAM isn't in it).
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    const BAM_LAT = 24.837633
    const BAM_LON = 67.103668
    const el = document.createElement('div')
    el.style.cssText = 'cursor:pointer; display:flex; flex-direction:column; align-items:center;'
    el.title = 'BAM 1006 (Karachi) — click for QC/QA status'
    el.innerHTML = `
      <div style="background:#7c3aed;color:#fff;font:600 10px/1 ui-sans-serif,system-ui;
                  padding:4px 7px;border-radius:9999px;box-shadow:0 1px 4px rgba(0,0,0,.35);
                  border:2px solid #fff;letter-spacing:.3px;white-space:nowrap;">BAM ▸</div>
      <div style="width:2px;height:8px;background:#7c3aed;"></div>`
    el.addEventListener('click', (e) => {
      e.stopPropagation()
      router.push('/bam')
    })
    const marker = new mapboxgl.Marker({ element: el, anchor: 'bottom' })
      .setLngLat([BAM_LON, BAM_LAT])
      .addTo(map)
    return () => { marker.remove() }
  }, [mapLoaded, router])

  // Render station markers
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return

    // Remove old markers
    markersRef.current.forEach(m => m.remove())
    markersRef.current = []

    const map = mapRef.current!

    for (const stn of stations) {
      const lat = stn.lat ?? stn.latitude
      const lon = stn.lon ?? stn.longitude
      if (lat == null || lon == null || stn.pm25 == null) continue

      const band = pm25ToBand(stn.pm25)
      const colorClass = bandToMarkerClass(band)
      const el = createMarkerEl(stn.pm25, colorClass)

      el.addEventListener('mouseenter', () => setHoveredStation(stn))
      el.addEventListener('mouseleave', () => setHoveredStation(null))

      const marker = new mapboxgl.Marker({ element: el, anchor: 'center' })
        .setLngLat([lon, lat])

      markersRef.current.push(marker)
    }

    // Zoom-based visibility + stem animation (same as analyst desk)
    const updateVisibility = () => {
      const zoom = map.getZoom()
      const visible = zoom >= 4
      const close = zoom >= 10
      for (const marker of markersRef.current) {
        if (visible) {
          marker.addTo(map)
          const el = marker.getElement()
          const stem = el.querySelector('.aqi-stem') as HTMLElement
          const dot = el.querySelector('.aqi-ground-dot') as HTMLElement
          if (stem) stem.style.height = close ? '18px' : '0px'
          if (dot) dot.style.opacity = close ? '1' : '0'
        } else {
          marker.remove()
        }
      }
    }
    updateVisibility()
    // One zoom listener at a time (they used to accumulate on every date change)
    if (zoomHandlerRef.current) map.off('zoom', zoomHandlerRef.current)
    zoomHandlerRef.current = updateVisibility
    map.on('zoom', updateVisibility)
  }, [stations, mapLoaded])

  // Toggle brick kiln layer visibility
  useEffect(() => {
    if (!mapRef.current || !mapLoaded) return
    const map = mapRef.current
    const vis = showKilns ? 'visible' : 'none'
    for (const id of ['brick-kilns-layer', 'brick-kilns-glow', 'brick-kilns-dots']) {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis)
    }
  }, [showKilns, mapLoaded])

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
  }, [showIndustry, mapLoaded])

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
          features: firesData.features.filter((f: any) => {
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

    setSelectedDistrict(null)
    setHoverPM25(null)
  }, [selectedDate, smoothed, model, mapLoaded])

  return (
    <div className="relative w-full h-full">
      <div ref={mapContainer} className="w-full h-full" />

      {/* Station hover tooltip */}
      {hoveredStation && (
        <div className="absolute top-6 left-6 z-20 bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-slate-200/60 px-3 py-2.5 min-w-[160px]">
          <div className="text-xs font-semibold text-slate-800">{hoveredStation.name}</div>
          <div className="text-[10px] text-slate-500 mt-0.5">{hoveredStation.city}</div>
          <div className="flex items-baseline gap-1 mt-1.5">
            <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: BAND_COLORS[pm25ToBand(hoveredStation.pm25)] || '#9ca3af' }} />
            <span className="text-lg font-bold text-slate-900">{hoveredStation.pm25.toFixed(1)}</span>
            <span className="text-xs text-slate-500">µg/m³</span>
          </div>
          <div className="text-[10px] text-slate-400 mt-1">
            Daily Mean (QA){hoveredStation.valid_hours != null ? ` · ${hoveredStation.valid_hours}h` : ''}
          </div>
        </div>
      )}

      {/* Urban grid hover readout */}
      {hoverPM25 && !selectedDistrict && !hoveredStation && (
        <div className="absolute bottom-16 left-4 z-20 bg-white/95 backdrop-blur-sm rounded-lg shadow-lg border border-slate-200/60 px-3 py-2">
          <div className="text-[10px] text-emerald-600 font-semibold uppercase tracking-wide">{hoverPM25.label}</div>
          <div className="flex items-baseline gap-1 mt-0.5">
            <span className="text-xl font-bold text-slate-900">{hoverPM25.pm25.toFixed(1)}</span>
            <span className="text-xs text-slate-500">µg/m³</span>
          </div>
        </div>
      )}

      {/* Selected district info panel */}
      {selectedDistrict && (
        <div className="absolute top-6 left-6 z-20 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl border border-slate-200/60 overflow-hidden min-w-[200px]">
          <div className="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200">
            <h3 className="text-sm font-bold text-slate-800">{selectedDistrict.name}</h3>
            <button onClick={() => setSelectedDistrict(null)} className="ml-3 text-slate-400 hover:text-slate-600">
              <X size={14} />
            </button>
          </div>
          <div className="px-4 py-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide font-medium">PM₂.₅ Prediction</div>
            <div className="flex items-baseline gap-1.5 mt-1">
              <span className="text-3xl font-bold" style={{ color: selectedDistrict.pm25 != null ? BAND_COLORS[pm25ToBand(selectedDistrict.pm25)] : '#94a3b8' }}>
                {selectedDistrict.pm25 !== null ? selectedDistrict.pm25.toFixed(1) : '—'}
              </span>
              <span className="text-sm text-slate-500">μg/m³</span>
            </div>
            {selectedDistrict.stations.length > 0 && (
              <div className="mt-2 pt-2 border-t border-slate-100">
                <div className="text-[10px] text-slate-500 uppercase tracking-wide font-medium mb-1">
                  Observed ({selectedDistrict.stations.length} station{selectedDistrict.stations.length > 1 ? 's' : ''})
                </div>
                {selectedDistrict.stations.map((stn, i) => (
                  <div key={i} className="flex items-center justify-between text-[11px] py-0.5">
                    <span className="text-slate-600 truncate max-w-[120px]">{stn.name}</span>
                    <span className="font-semibold tabular-nums ml-2" style={{ color: BAND_COLORS[pm25ToBand(stn.pm25)] }}>
                      {stn.pm25.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* District hover tooltip removed — district name visible on click in sidebar */}

      {!mapLoaded && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-100">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      )}
    </div>
  )
}

function getCentroid(ring: number[][]): [number, number] {
  let x = 0, y = 0
  for (const coord of ring) {
    x += coord[0]
    y += coord[1]
  }
  return [x / ring.length, y / ring.length]
}
